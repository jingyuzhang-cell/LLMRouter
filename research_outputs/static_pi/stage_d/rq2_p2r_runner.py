#!/usr/bin/env python3
"""RQ2_P2R_V1 thin runner: A/B/C arms over frozen E05-E08 (V1.5 materials).
Reuses frozen components from stage_d_executor (GlobalBudget ledger, RunStore
checkpointing, glm/deepseek transports). New orchestration only; frozen executor
file untouched. Mock mode = zero real calls (default). Real mode additionally
requires --real AND env STAGE_D_REAL_CALLS_AUTHORIZED=1 AND STAGE_D_GLM_KEY.

Arms (per RQ2_REAL_GO_APPLICATION.md):
  A: DS static baseline (no re-roll, no verify)
  B: DS base + runtime-signal same-model re-roll + semantic verify
  C: hetero base (reason/verification/report -> GLM) + hetero re-roll + verify
3 reps x 4 tasks (E05-E08). All calls priced into the ledger.
"""
import os, sys, json, time, argparse, threading
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from stage_d_executor import GlobalBudget, RunStore, stage_d_real_transport

MATS = json.load(open(HERE / 'rq1_tasks' / 'rq1_tasks_materials.json'))
FACTS = json.load(open(HERE / 'rq1_tasks' / 'facts_E05_E08.json'))
DOCS_DIR = Path('/root/cap_eval_bench_v1/evidence/texts')
TASKS = ['E05', 'E06', 'E07', 'E08']
ARMS = ['A', 'B', 'C']
REPS = 3
HETERO_GLM_KINDS = {'reason', 'verification', 'report'}
REROLL_GLM_KINDS = {'reason', 'verification', 'report'}
YUAN_PER_CALL = {'glm53flash': 0.04, 'deepseek': 0.0129}
MAXTOK = 2000
DEDUP_CAP = 64          # safety valve only; observed max unique/exec = 27, never binds
MIN_CALLS_PER_EXEC = 90  # stop at execution boundary, never mid-execution

SYS_COMMON = ("你是资本市场调查助理。只输出一个 JSON 对象，不要输出其他文字。"
              "输出格式：{\"facts\":[{\"fid\":\"...\",\"value\":\"...\",\"doc\":\"doc1\","
              "\"quote\":\"原文引用\"}],\"unknown\":[\"无法确认的项\"]}。"
              "每条事实必须给出处文档 id 与原文引用(quote)；找不到则列入 unknown。")

def node_prompt(task, node, upstream_outputs):
    t = MATS['tasks'][task]
    docs = []
    for dr in node.get('doc_refs', []):
        d = next(x for x in t['docs'] if x['doc_id'] == dr)
        p = DOCS_DIR / d['file']
        docs.append(f"[{dr}] {d['title']}\n" + (p.read_text('utf-8') if p.exists() else '(缺失)'))
    ctx = '\n\n'.join(docs) if docs else ''
    up = ''
    ru = node.get('reference_upstream')
    if ru:
        parts = []
        for n in ru.get('from_nodes', []):
            if n in upstream_outputs:
                parts.append(f"上游节点 {n} 的事实：\n" + json.dumps(
                    upstream_outputs[n], ensure_ascii=False))
        up = '\n\n'.join(parts)
    q = f"调查问题：{t['question']}\n公司：{t['company']}"
    return (f"{q}\n\n节点任务（{node['kind']}）：{node['task']}\n"
            f"{('' if not ctx else chr(10) + '文档：' + chr(10) + ctx)}"
            f"{('' if not up else chr(10) + chr(10) + up)}\n\n按系统格式输出 JSON。")

def verify_prompt(fact, quote, doc_title):
    return (f"判断以下证据是否支持该事实结论。事实：{fact}\n证据（{doc_title}）：{quote}\n"
            f"只输出 JSON：{{\"supported\": true}} 或 {{\"supported\": false}}")

def parse_facts(text):
    try:
        i = text.find('{'); j = text.rfind('}')
        d = json.loads(text[i:j + 1])
        facts = d.get('facts', [])
        return (isinstance(facts, list), facts, d.get('unknown', []))
    except Exception:
        return (False, [], [])

def signals(node, ok, facts):
    """Runtime-only observables: exec failure | production missing | citation missing."""
    if not ok:
        return {'exec': True, 'prod': False, 'cite': False}
    prod = len(facts) == 0 and node['kind'] != 'report'
    cite = any(not str(f.get('quote', '')).strip() or not str(f.get('doc', '')).strip()
               for f in facts if isinstance(f, dict))
    return {'exec': False, 'prod': bool(prod), 'cite': bool(cite)}

def score_node(facts_obj):
    return 2 * len([f for f in facts_obj if isinstance(f, dict) and f.get('quote') and f.get('doc')]) \
        + len([f for f in facts_obj if isinstance(f, dict)]) + 1

class Runner:
    def __init__(self, cfg, out_dir, real):
        self.cfg = cfg
        self.real = real
        self.out_dir = Path(out_dir)
        state = self.out_dir / 'state'
        state.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), state)
        self.store = RunStore(state, self.out_dir)
        self.ledger_lock = threading.Lock()
        self.ledger_path = self.out_dir / 'ledger.jsonl'

    def call(self, arm, task, rep, node_id, role, model, system, user):
        est = YUAN_PER_CALL[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(min(len(user), 12000), MAXTOK)
        t0 = time.monotonic()
        if self.real:
            r = stage_d_real_transport('glm53flash' if model == 'glm53flash' else 'deepseek',
                                       system, user, MAXTOK, 180)
            text, tin, tout, stop, lat = r['text'], r['in'], r['out'], r.get('stop'), r.get('lat')
        else:
            text = json.dumps({"facts": [{"fid": node_id, "value": "mock", "doc": "doc1",
                                          "quote": "mock quote"}], "unknown": []},
                              ensure_ascii=False)
            tin, tout, stop, lat = len(user), 64, 'end_turn', 0.01
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = {'ts': time.time(), 'arm': arm, 'task': task, 'rep': rep, 'node': node_id,
               'role': role, 'model': model, 'in': tin, 'out': tout, 'yuan': est,
               'stop': stop, 'lat': lat,
               'prompt_sha': __import__('hashlib').sha256(
                   (system + '||' + user).encode()).hexdigest()[:16]}
        with self.ledger_lock:
            with open(self.ledger_path, 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return text, rec

    def run_exec(self, arm, task, rep):
        exec_id = f"{arm}|{task}|r{rep}"
        if self.store.completed(exec_id):
            return None
        self.store.begin(exec_id)
        t = MATS['tasks'][task]
        upstream = {}
        node_recs = []
        verify_map = {}   # exact (fid,value,doc,quote) -> verdict, per execution
        dedup_stats = {'unique': 0, 'verify_calls': 0, 'reused': 0, 'cap_hits': 0}
        for node in t['nodes']:
            kind = node['kind']
            base_model = ('glm53flash' if (arm == 'C' and kind in HETERO_GLM_KINDS)
                          else 'deepseek')
            sysp = SYS_COMMON
            userp = node_prompt(task, node, upstream)
            text, rec = self.call(arm, task, rep, node['node_id'], 'base',
                                  base_model, sysp, userp)
            node_recs.append(rec)
            ok, facts, unk = parse_facts(text)
            sig = signals(node, ok, facts)
            chosen = {'model': base_model, 'facts': facts, 'unknown': unk, 'rerolled': False}
            if arm in ('B', 'C') and (sig['exec'] or sig['prod'] or sig['cite']):
                rr_model = ('glm53flash' if (arm == 'C' and kind in REROLL_GLM_KINDS)
                            else base_model if arm == 'B'
                            else 'deepseek')
                text2, rec2 = self.call(arm, task, rep, node['node_id'], 'reroll',
                                        rr_model, sysp, userp)
                ok2, facts2, unk2 = parse_facts(text2)
                take2 = score_node(facts2) > score_node(facts)
                if take2:
                    chosen = {'model': rr_model, 'facts': facts2, 'unknown': unk2,
                              'rerolled': True}
                node_recs.append(rec2)
            # dedup verification for cited facts (arms B/C): first occurrence pays,
            # later identical (fid,value,doc,quote) tuples reuse the first verdict.
            verifies = []
            if arm in ('B', 'C'):
                for f in chosen['facts']:
                    if not isinstance(f, dict) or not f.get('quote'):
                        continue
                    key = (str(f.get('fid', '')), str(f.get('value', '')),
                           str(f.get('doc', '')), str(f.get('quote', '')))
                    if key in verify_map:
                        verifies.append({'fact': f, 'supported': verify_map[key],
                                         'reused': True})
                        dedup_stats['reused'] += 1
                        continue
                    if len(verify_map) >= DEDUP_CAP:
                        verify_map[key] = False
                        verifies.append({'fact': f, 'supported': False,
                                         'reused': False, 'cap_hit': True})
                        dedup_stats['cap_hits'] += 1
                        continue
                    vt, vrec = self.call(arm, task, rep, node['node_id'], 'verify',
                                         'glm53flash', SYS_COMMON,
                                         verify_prompt(str(f.get('value', f.get('fid', ''))),
                                                       str(f['quote']), str(f.get('doc', ''))))
                    try:
                        verdict = json.loads(vt[vt.find('{'):vt.rfind('}') + 1]).get(
                            'supported', False)
                    except Exception:
                        verdict = False
                    verify_map[key] = bool(verdict)
                    dedup_stats['verify_calls'] += 1
                    verifies.append({'fact': f, 'supported': bool(verdict),
                                     'reused': False})
                    node_recs.append(vrec)
            dedup_stats['unique'] = len(verify_map)
            upstream[node['node_id']] = chosen['facts']
            node_out = {'node_id': node['node_id'], 'kind': kind, 'signals': sig,
                        'chosen': chosen, 'verifies': verifies}
            node_recs.append(node_out)
        record = {'exec_id': exec_id, 'arm': arm, 'task': task, 'rep': rep,
                  'nodes': node_recs, 'dedup': dedup_stats,
                  'budget_left': self.gb.left()}
        self.store.commit(record)
        return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'rq2_p2r_config.json'))
    ap.add_argument('--out', default=str(HERE / 'rq2_p2r_runs'))
    ap.add_argument('--real', action='store_true')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--arms', default=None,
                    help='comma-separated subset of A,B,C (default: config arms)')
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    arm_list = [x.strip() for x in (a.arms or ','.join(cfg.get('arms', ARMS))).split(',')
                if x.strip()]
    bad = [x for x in arm_list if x not in ARMS]
    if bad:
        raise SystemExit(f'REFUSED: unknown arms {bad}; valid={ARMS}')
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
            raise SystemExit('REFUSED: real mode requires STAGE_D_REAL_CALLS_AUTHORIZED=1')
        if not os.environ.get('STAGE_D_GLM_KEY', '').strip():
            raise SystemExit('REFUSED: STAGE_D_GLM_KEY not set')
        print('REAL MODE — caps:', cfg['calls'], cfg['tokens'], cfg['yuan'])
    else:
        print('MOCK MODE — zero real calls')
    r = Runner(cfg, a.out, a.real)
    done = skipped = 0
    stopped = False
    for arm in arm_list:
        for task in TASKS:
            for rep in range(1, REPS + 1):
                if a.limit is not None and done >= a.limit:
                    stopped = True
                    break
                exec_id = f"{arm}|{task}|r{rep}"
                if not r.store.completed(exec_id):
                    left = r.gb.left()
                    if left['calls_left'] < MIN_CALLS_PER_EXEC:
                        print(f"STOP before {exec_id}: calls_left={left['calls_left']} "
                              f"< {MIN_CALLS_PER_EXEC} (execution-boundary guard)")
                        stopped = True
                        break
                rec = r.run_exec(arm, task, rep)
                if rec is None:
                    skipped += 1
                else:
                    done += 1
                    print(f"  {exec_id} done, calls_left={r.gb.left()['calls_left']}")
            if stopped:
                break
        if stopped:
            break
    print(f"BATCH DONE: executed={done} skipped={skipped} stopped_early={stopped} "
          f"budget={r.gb.left()}")


if __name__ == '__main__':
    main()
