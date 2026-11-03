#!/usr/bin/env python3
"""RQ2_P2R_V3 runner (2x2 factorial, improved-delivery cells HomImp/HetImp).

Implements RQ2_P2R_V3_PREREGISTRATION_V1_1.md exactly; reuses V2 runner pieces
(prompts, parsing, signals, budget ledger, RunStore) without modifying frozen
files. Real mode requires --real AND env STAGE_D_REAL_CALLS_AUTHORIZED=1 AND
STAGE_D_GLM_KEY (identical safety gates to V2). Mock mode = zero real calls.

Changes vs V2 runner (all preregistered):
  D1: delivery-critical nodes get max_tokens = 2000 + 150*n_upstream_facts
      (fid-deduped facts actually serialized into the node prompt), cap 6000;
      actual per-node max_tokens recorded.
  D2: delivery-critical nodes get the frozen evidence-faithful output contract
      appended to the system prompt (quote = verbatim span, parent_fid field,
      split-or-unknown rule; no length caps; no identifiers in quote).
  Instrumentation: base AND reroll outputs both persisted per node (ok/facts/
      score) with adoption decision, for node-level before/after pairing.
  Interleaving: HomImp/HetImp executed per (task, rep) in the same session.
  Model metadata: transport wrapper records the server-returned `model` field
      into the ledger (request bodies copied verbatim from frozen transports).
Cells HomImp = V2 B mechanism (all DS) and HetImp = V2 C mechanism
(GLM on reason/verification/report) under improved delivery; base cells reuse
frozen V2 records (read-only).
"""
import os, sys, json, time, argparse, threading, hashlib, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import (MATS, TASKS, REPS, YUAN_PER_CALL, DEDUP_CAP,
                            MIN_CALLS_PER_EXEC, HETERO_GLM_KINDS,
                            REROLL_GLM_KINDS, SYS_COMMON, node_prompt,
                            verify_prompt, parse_facts, signals, score_node,
                            Runner as V2Runner)

DELIVERY_KINDS = {'reason', 'verification', 'report', 'merge'}
MAXTOK_BASE = 2000
D1_PER_FACT = 150
D1_CAP = 6000
MAXTOK_VERIFY = 2000

# D2 output contract, frozen verbatim in RQ2_P2R_V3_PREREGISTRATION_V1_1.md §2.2
D2_CONTRACT = """
输出契约（交付关键节点）：
1. facts 数组每条对象字段：fid（本条事实标识）、value（事实值，一条事实只陈述一个可验证结论，禁止拼贴多条）、doc（证据文档 id）、quote（支持该事实的原文证据跨度）、parent_fid（若本条承接自上游节点输出，填上游事实的 fid；否则省略）、summary（可选，不超过 20 字的展示摘要）。
2. quote 必须是 doc 所示文档中连续的原文片段，逐字复制，不得截断、改写、翻译或使用任何标识符、节点名、自述文字代替。
3. 选取能完整支持 value 的最小连续原文跨度；没有字数上限。若任何单一连续跨度无法完整支持 value：要么把 value 拆分为多条事实（各自带独立 quote），要么把该条移入 unknown。禁止为迁就长度而压缩或改写证据。
4. 上游已给出的事实默认不重复列出。如确需保留：逐字复制上游的 value/doc/quote（保持完全一致以便去重），并填 parent_fid 指向上游 fid；不得为上游事实伪造新的或改写的 quote。
5. 无法确认的项列入 unknown 数组。"""

GLM_MODEL_ID = 'GLM-5.3-Flash'
GLM_ENDPOINT = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
DS_MODEL_ID = 'deepseek-flash'
DS_ENDPOINT = 'https://api.deepseek.com'


def v3_real_transport(alias, system, user, max_tokens, timeout_s):
    """Verbatim request bodies from frozen transports (glm_low_call /
    openai_call); additionally returns the server `model` field."""
    if alias == 'glm53flash':
        body = {"model": GLM_MODEL_ID, "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "reasoning_effort": "low"}
        req = urllib.request.Request(
            GLM_ENDPOINT,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST")
        key = os.environ.get("STAGE_D_GLM_KEY", "").strip()
        req.add_header("content-type", "application/json")
        req.add_header("x-api-key", key)
        req.add_header("authorization", "Bearer " + key)
        req.add_header("anthropic-version", "2023-06-01")
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            d = json.loads(r.read().decode())
        return {"text": "".join(b.get("text", "") for b in d.get("content", [])
                                if isinstance(b, dict) and b.get("type") == "text"),
                "in": d["usage"]["input_tokens"],
                "out": d["usage"]["output_tokens"],
                "stop": d.get("stop_reason"),
                "lat": round(time.monotonic() - t0, 2),
                "model": d.get("model")}
    body = {"model": DS_MODEL_ID, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"}}
    req = urllib.request.Request(
        DS_ENDPOINT + '/chat/completions',
        data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " +
                   os.environ.get("DEEPSEEK_API_KEY", ""))
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    c = d["choices"][0]["message"].get("content", "")
    if isinstance(c, list):
        c = "".join(x.get("text", "") for x in c if isinstance(x, dict))
    u = d["usage"]
    return {"text": c, "in": u.get("prompt_tokens", u.get("input_tokens", 0)),
            "out": u.get("completion_tokens", u.get("output_tokens", 0)),
            "stop": d["choices"][0].get("finish_reason", ''),
            "lat": round(time.monotonic() - t0, 2), "model": d.get("model")}


def n_upstream_facts(upstream, from_nodes):
    """Frozen D1 rule: fid-deduped fact count actually serialized into the
    node input prompt (only facts from referenced upstream nodes count)."""
    fids = set()
    for n in from_nodes:
        for f in upstream.get(n, []):
            if isinstance(f, dict) and f.get('fid'):
                fids.add(str(f['fid']))
    return len(fids)


class V3Runner(V2Runner):

    def call(self, arm, task, rep, node_id, role, model, system, user,
             max_tokens):
        est = YUAN_PER_CALL[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(min(len(user), 12000), max_tokens)
        t0 = time.monotonic()
        if self.real:
            r = v3_real_transport(model, system, user, max_tokens, 180)
            text, tin, tout = r['text'], r['in'], r['out']
            stop, lat, model_resp = r['stop'], r['lat'], r.get('model')
        else:
            text = json.dumps({"facts": [{"fid": node_id, "value": "mock",
                                          "doc": "doc1",
                                          "quote": "mock quote"}],
                               "unknown": []}, ensure_ascii=False)
            tin, tout, stop, lat, model_resp = len(user), 64, 'end_turn', 0.01, None
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = {'ts': time.time(), 'arm': arm, 'task': task, 'rep': rep,
               'node': node_id, 'role': role, 'model': model,
               'model_resp': model_resp, 'max_tokens': max_tokens,
               'in': tin, 'out': tout, 'yuan': est, 'stop': stop, 'lat': lat,
               'prompt_sha': hashlib.sha256(
                   (system + '||' + user).encode()).hexdigest()[:16]}
        with self.ledger_lock:
            with open(self.ledger_path, 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return text, rec

    def run_exec(self, arm, task, rep):
        # arm 'B'->HomImp, 'C'->HetImp (recorded with cell names)
        cell = 'HomImp' if arm == 'B' else 'HetImp'
        exec_id = f"{cell}|{task}|r{rep}"
        if self.store.completed(exec_id):
            return None
        self.store.begin(exec_id)
        t = MATS['tasks'][task]
        upstream = {}
        node_recs = []
        verify_map = {}
        dedup_stats = {'unique': 0, 'verify_calls': 0, 'reused': 0,
                       'cap_hits': 0}
        for node in t['nodes']:
            kind = node['kind']
            delivery = kind in DELIVERY_KINDS
            base_model = ('glm53flash' if (arm == 'C' and
                                           kind in HETERO_GLM_KINDS)
                          else 'deepseek')
            sysp = SYS_COMMON + (D2_CONTRACT if delivery else '')
            userp = node_prompt(task, node, upstream)
            if delivery:
                ru = node.get('reference_upstream') or {}
                nup = n_upstream_facts(upstream, ru.get('from_nodes', []))
                mt = min(D1_CAP, MAXTOK_BASE + D1_PER_FACT * nup)
            else:
                nup, mt = 0, MAXTOK_BASE
            text, rec = self.call(arm, task, rep, node['node_id'], 'base',
                                  base_model, sysp, userp, mt)
            node_recs.append(rec)
            ok, facts, unk = parse_facts(text)
            base_out = {'ok': ok, 'facts': facts, 'unknown': unk,
                        'score': score_node(facts), 'model': base_model,
                        'max_tokens': mt, 'n_upstream_facts': nup}
            sig = signals(node, ok, facts)
            chosen = {'model': base_model, 'facts': facts, 'unknown': unk,
                      'rerolled': False}
            reroll_out = None
            if (sig['exec'] or sig['prod'] or sig['cite']):
                rr_model = ('glm53flash' if (arm == 'C' and
                                             kind in REROLL_GLM_KINDS)
                            else base_model)
                text2, rec2 = self.call(arm, task, rep, node['node_id'],
                                        'reroll', rr_model, sysp, userp, mt)
                node_recs.append(rec2)
                ok2, facts2, unk2 = parse_facts(text2)
                reroll_out = {'ok': ok2, 'facts': facts2, 'unknown': unk2,
                              'score': score_node(facts2), 'model': rr_model,
                              'max_tokens': mt}
                if score_node(facts2) > score_node(facts):
                    chosen = {'model': rr_model, 'facts': facts2,
                              'unknown': unk2, 'rerolled': True}
            adopted = 'reroll' if chosen.get('rerolled') else 'base'
            verifies = []
            for f in chosen['facts']:
                if not isinstance(f, dict) or not f.get('quote'):
                    continue
                key = (str(f.get('fid', '')), str(f.get('value', '')),
                       str(f.get('doc', '')), str(f.get('quote', '')))
                if key in verify_map:
                    verifies.append({'fact': f,
                                     'supported': verify_map[key],
                                     'reused': True})
                    dedup_stats['reused'] += 1
                    continue
                if len(verify_map) >= DEDUP_CAP:
                    verify_map[key] = False
                    verifies.append({'fact': f, 'supported': False,
                                     'reused': False, 'cap_hit': True})
                    dedup_stats['cap_hits'] += 1
                    continue
                vt, vrec = self.call(arm, task, rep, node['node_id'],
                                     'verify', 'glm53flash', SYS_COMMON,
                                     verify_prompt(
                                         str(f.get('value', f.get('fid', ''))),
                                         str(f['quote']),
                                         str(f.get('doc', ''))),
                                     MAXTOK_VERIFY)
                try:
                    verdict = json.loads(
                        vt[vt.find('{'):vt.rfind('}') + 1]).get('supported',
                                                                False)
                except Exception:
                    verdict = False
                verify_map[key] = bool(verdict)
                dedup_stats['verify_calls'] += 1
                verifies.append({'fact': f, 'supported': bool(verdict),
                                 'reused': False})
                node_recs.append(vrec)
            dedup_stats['unique'] = len(verify_map)
            upstream[node['node_id']] = chosen['facts']
            node_recs.append({'node_id': node['node_id'], 'kind': kind,
                              'delivery': delivery, 'signals': sig,
                              'chosen': chosen, 'verifies': verifies,
                              'base_output': base_out,
                              'reroll_output': reroll_out,
                              'adopted': adopted})
        record = {'exec_id': exec_id, 'arm': arm, 'cell': cell, 'task': task,
                  'rep': rep, 'nodes': node_recs, 'dedup': dedup_stats,
                  'budget_left': self.gb.left()}
        self.store.commit(record)
        return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'rq2_p2r_v3_config.json'))
    ap.add_argument('--out', default=str(HERE / 'rq2_p2r_v3_runs'))
    ap.add_argument('--real', action='store_true')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--cells', default='HomImp,HetImp')
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    cells = [x.strip() for x in a.cells.split(',') if x.strip()]
    bad = [x for x in cells if x not in ('HomImp', 'HetImp')]
    if bad:
        raise SystemExit(f'REFUSED: unknown cells {bad}')
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
            raise SystemExit('REFUSED: real mode requires '
                             'STAGE_D_REAL_CALLS_AUTHORIZED=1')
        if not os.environ.get('STAGE_D_GLM_KEY', '').strip():
            raise SystemExit('REFUSED: STAGE_D_GLM_KEY not set')
        print('REAL MODE — caps:', cfg['calls'], cfg['tokens'], cfg['yuan'])
    else:
        print('MOCK MODE — zero real calls')
    r = V3Runner(cfg, a.out, a.real)
    done = skipped = 0
    stopped = False
    for task in TASKS:                       # interleaved per (task, rep)
        for rep in range(1, REPS + 1):
            for cell in cells:
                arm = 'B' if cell == 'HomImp' else 'C'
                exec_id = f"{cell}|{task}|r{rep}"
                if r.store.completed(exec_id):
                    skipped += 1
                    continue
                if a.limit is not None and done >= a.limit:
                    stopped = True
                    break
                left = r.gb.left()
                if left['calls_left'] < MIN_CALLS_PER_EXEC:
                    print(f"STOP before {exec_id}: calls_left="
                          f"{left['calls_left']} < {MIN_CALLS_PER_EXEC}")
                    stopped = True
                    break
                rec = r.run_exec(arm, task, rep)
                if rec is not None:
                    done += 1
                    print(f"  {exec_id} done, calls_left="
                          f"{r.gb.left()['calls_left']}")
            if stopped:
                break
        if stopped:
            break
    print(f"BATCH DONE: executed={done} skipped={skipped} "
          f"stopped_early={stopped} budget={r.gb.left()}")


if __name__ == '__main__':
    main()
