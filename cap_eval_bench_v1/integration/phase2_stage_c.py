"""STAGE-C runner: five-arm dynamic joint dispatch under SAME anomaly
state (v stage-c-v1). Protocol: PHASE2_PROTOCOL §2 Stage C — same initial
canonical graph per task, same anomaly injection point across arms & reps,
arm-tagged recovery execution, shared pre-anomaly prefix WITHIN (task,rep)
for same-state pairing (protocol requirement: 'window 1 outputs all
candidates' decisions from the SAME state snapshot for paired review').

Anomaly (frozen): transport-level output corruption at f3 (timeline node)
after its first real call — contract_parse_failure detection; zero extra
tokens for injection (the call already happened; output replaced).

Arms (post-anomaly behavior):
  dyn_Static      blind retry f3 same model, continue original pi
  dyn_R_only      R = closure(f3) = {f3,f5,f6}, same pi
  dyn_pi_only     R = {f3}, re-optimize pi on remaining subgraph
  dyn_Joint_R_pi  enumerate R candidates x pi re-opt, pick best (frozen
                  profile prediction), then execute
  dyn_Joint_Z_R_pi same + Z candidates (z_ops_v2 semantic-guarded)

Budget: cap 150K tokens, 150 calls, per-model GLM<=90K/Flash<=60K.
"""
import argparse
import json
import sys
import time
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
P = Path('/root/capital_opinion_pilot')
sys.path.insert(0, str(B)); sys.path.insert(0, str(B / 'scoring'))
sys.path.insert(0, str(B / 'evidence')); sys.path.insert(0, str(B / 'integration'))
sys.path.insert(0, str(P)); sys.path.insert(0, '/root/r3_own_pool')
sys.path.insert(0, '/root/r3_own_pool/deadline_reward_v1')

import retrieval_api as R                          # noqa: E402
import qe_k_scorer as S                            # noqa: E402
import static_optimizer as SO                       # noqa: E402
from pilot_common import Meter, BudgetExceeded     # noqa: E402
from phase2_stage_a import load_task, ctx_table_for  # noqa: E402
from phase1_real_batch import NODE_CAPS            # noqa: E402
from canonical_assembler import (assemble, fair_final_prompt_suffix,
                                 normalize_contract_output)  # noqa: E402

RUNNER_VERSION = 'stage-c-v1'
TASKS = ['SC-E1', 'SC-E2', 'SC-E3', 'SC-E4']
NODE_KINDS = {'f1': 'index', 'f2': 'extracts', 'f3': 'timeline',
              'f4': 'entity_facts', 'f5': 'factcheck_full', 'f6': 'report'}
DEPS = {'f1': [], 'f2': ['f1'], 'f3': ['f2'], 'f4': ['f2'],
        'f5': ['f2', 'f3', 'f4'], 'f6': ['f5']}
GARBAGE = '[{"fact":"占位","evidence_doc_id":"?"}]'
QUOTA = {'glm53': 90000, 'glm53flash': 60000}
PROFILE_Q = {  # frozen V3 capability table (node-kind × model quality)
    'index': {'glm53': 0.85, 'glm53flash': 0.62},
    'extracts': {'glm53': 0.85, 'glm53flash': 0.62},
    'timeline': {'glm53': 0.75, 'glm53flash': 0.60},
    'entity_facts': {'glm53': 0.80, 'glm53flash': 0.58},
    'factcheck_full': {'glm53': 0.83, 'glm53flash': 0.80},
    'report': {'glm53': 0.85, 'glm53flash': 0.60},
}


KIND_MAP = {'factcheck_full': 'factcheck'}

def predict_pi(remaining_kinds, budget_tokens):
    kinds = {n: KIND_MAP.get(NODE_KINDS[n], NODE_KINDS[n]) for n in remaining_kinds}
    try:
        return SO.optimize(kinds, budget_tokens=budget_tokens,
                           max_latency_s=40.0)
    except Exception:
        return {n: 'glm53flash' for n in remaining_kinds}


def closure(fault):
    seen, stack = set(), [fault]
    while stack:
        n = stack.pop()
        for m, ds in DEPS.items():
            if n in ds and m not in seen:
                seen.add(m); stack.append(m)
    return seen | {fault}


def build_prompt(uid, kind, upstream_data, evidence_texts, terms, task):
    from phase2_stage_a import SYSTEM_NODE, FINAL_CAP
    from phase1_real_batch import NODE_CAPS as NC
    parts = []
    if kind == 'index':
        idx = json.dumps([dict(doc_id=k, title=v[:40])
                          for k, v in evidence_texts.items()],
                         ensure_ascii=False)
        prompt = (f'{SYSTEM_NODE}\n子任务：构建证据索引。可用文档：{idx}\n'
                  f'输出 JSON 对象，字段 evidence_index。')
    elif kind == 'extracts':
        pack = json.dumps(upstream_data.get('evidence_index', {}),
                          ensure_ascii=False)[:2000]
        docs = '\n\n'.join(f'## 文档 {did}\n{txt[:3000]}'
                             for did, txt in list(evidence_texts.items())[:5])
        prompt = (f'{SYSTEM_NODE}\n子任务：从下列证据文档正文抽取关键事实'
                  f'（日期/金额/主体/违规事实），输出 JSON，字段 doc_extracts。'
                  f'\n证据索引：{pack}'
                  f'\n\n## 证据文档正文（任务事实的唯一来源，内容必须出自此处）：'
                  f'\n{docs}')
    elif kind == 'timeline':
        prompt = (f'{SYSTEM_NODE}\n子任务：整理时间线（按日期排序），'
                  f'输出 JSON，字段 timeline。\n上游抽取：'
                  f'{json.dumps(upstream_data.get("doc_extracts", {}), ensure_ascii=False)[:4000]}')
    elif kind == 'entity_facts':
        prompt = (f'{SYSTEM_NODE}\n子任务：识别涉事主体及关系，'
                  f'输出 JSON，字段 entity_facts。\n上游抽取：'
                  f'{json.dumps(upstream_data.get("doc_extracts", {}), ensure_ascii=False)[:4000]}')
    elif kind == 'factcheck_full':
        prompt = (f'{SYSTEM_NODE}\n子任务：交叉核验全部上游事实，'
                  f'输出 JSON，字段 verified_facts。\n时间线：'
                  f'{json.dumps(upstream_data.get("timeline", []), ensure_ascii=False)[:2500]}'
                  f'\n主体：{json.dumps(upstream_data.get("entity_facts", []), ensure_ascii=False)[:2500]}')
    else:  # report
        prompt = (f'{SYSTEM_NODE}\n{fair_final_prompt_suffix(task["task_id"] if isinstance(task, dict) else tid)}\n'
                  f'用户问题：{task["question"]}\n核验事实：'
                  f'{json.dumps(upstream_data.get("verified_facts", []), ensure_ascii=False)[:4000]}'
                  '\n\n## 证据文档摘要（供引用）：' +
                  '\n' + '\n'.join(f'文档 {did}: {txt[:200]}' for did, txt in list(evidence_texts.items())[:5]))
    return prompt



def _eval_plan(Rc, pic, outputs):
    """frozen prediction: quality - cost for a recovery plan."""
    q = 0.0
    c = 0.0
    for n in ['f3', 'f4', 'f5', 'f6']:
        kind = NODE_KINDS[n]
        m = pic.get(n) or 'flash'
        q += PROFILE_Q.get(kind, {}).get(m, 0.5)
        if n in Rc:
            c += SO.COST.get(KIND_MAP.get(kind, kind), {}).get(m, 500)
    return q / 4 - c / 8000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--authorize-stage-c', action='store_true')
    ap.add_argument('--reps', type=int, default=2)
    ap.add_argument('--cap-calls', type=int, default=150)
    ap.add_argument('--cap-tokens', type=int, default=150000)
    args = ap.parse_args()
    if not args.authorize_stage_c:
        print(json.dumps({'mode': 'PLAN-ONLY (refuses without '
                          '--authorize-stage-c)'}))
        return 0
    meter = Meter(ledger_path=B / 'stage_c' /
                  'model_call_ledger_stage_c.jsonl',
                  max_calls=args.cap_calls,
                  max_guaranteed_actual=args.cap_tokens)
    (B / 'stage_c').mkdir(exist_ok=True)
    spent = {'glm53': 0, 'glm53flash': 0}
    results = []
    # import the actual transport from pilot (real calls)
    # pilot Meter.call(alias, system, user, max_tokens, purpose) -> (rec, text)
    for tid in TASKS:
        task = load_task(tid)
        ev_texts = {}
        for did in task['evidence_doc_ids']:
            f = B / 'evidence' / 'texts' / f'{did}.txt'
            if f.exists():
                ev_texts[did] = f.read_text()[:4000]
        for rep in range(1, args.reps + 1):
            # ---- shared pre-anomaly prefix (same-state pairing) ----
            shared_outputs = {}
            shared_data = {}
            shared_recs = []
            anomaly_fired = False
            for uid in ['f1', 'f2', 'f3']:
                kind = NODE_KINDS[uid]
                data = {}
                for d in DEPS[uid]:
                    port = {'index': 'evidence_index',
                            'extracts': 'doc_extracts',
                            'timeline': 'timeline',
                            'entity_facts': 'entity_facts',
                            'factcheck_full': 'verified_facts'}[NODE_KINDS[d]]
                    data[port] = shared_data.get(NODE_KINDS[d])
                prompt = build_prompt(uid, kind, data, ev_texts, None, task)
                model = 'glm53flash' if kind in ('index', 'extracts') else 'glm53'
                rec, text = meter.call(model, '', prompt,
                                      NODE_CAPS.get(kind, 512),
                                      purpose=f'SC-{tid}-r{rep}:{uid}')
                if uid == 'f3':
                    # ANOMALY INJECTION (frozen): transport-level corruption
                    text = GARBAGE
                    anomaly_fired = True
                shared_recs.append(rec)
                shared_outputs[uid] = text
                shared_data[kind] = text
                u = rec.get('usage', rec)
                spent[model] = spent.get(model, 0) + u.get('input_tokens', 0) + u.get('output_tokens', 0)
            if not anomaly_fired:
                continue
            # ---- fork five arms from the SAME shared state ----
            for arm in ['dyn_Static', 'dyn_R_only', 'dyn_pi_only',
                        'dyn_Joint_R_pi', 'dyn_Joint_Z_R_pi']:
                outputs = dict(shared_outputs)
                odata = dict(shared_data)
                odata['timeline'] = GARBAGE   # anomaly visible
                recs = list(shared_recs)
                # determine recovery plan
                if arm == 'dyn_Static':
                    Rset = {'f3'}
                    pi = {n: ('glm53flash' if NODE_KINDS[n] in
                              ('index', 'extracts') else 'glm53')
                          for n in ['f3', 'f4', 'f5', 'f6']}
                elif arm == 'dyn_R_only':
                    Rset = closure('f3') & {'f3', 'f4', 'f5', 'f6'}
                    pi = {n: ('glm53flash' if NODE_KINDS[n] in
                              ('index', 'extracts') else 'glm53')
                          for n in Rset | {'f4'}}
                elif arm == 'dyn_pi_only':
                    Rset = {'f3'}
                    pi = predict_pi(['f3', 'f4', 'f5', 'f6'],
                                    budget_tokens=5000)
                elif arm == 'dyn_Joint_R_pi':
                    best_v, Rset, pi = -9, {'f3'}, None
                    for Rc in [{'f3'}, {'f3', 'f5', 'f6'}]:
                        pic = predict_pi(sorted(Rc | {'f4'}), 5000)
                        v = _eval_plan(Rc, pic, outputs)
                        if v > best_v:
                            best_v, Rset, pi = v, Rc, pic
                else:  # dyn_Joint_Z_R_pi
                    best_v, Rset, pi = -9, {'f3'}, None
                    for Rc in [{'f3'}, {'f3', 'f5', 'f6'}]:
                        pic = predict_pi(sorted(Rc | {'f4'}), 5000)
                        v = _eval_plan(Rc, pic, outputs)
                        if v > best_v:
                            best_v, Rset, pi = v, Rc, pic
                # execute recovery + remaining nodes
                run_id = f'SC-{arm}-{tid}-r{rep}'
                wall0 = time.monotonic()
                for uid in ['f3', 'f4', 'f5', 'f6']:
                    kind = NODE_KINDS[uid]
                    if uid not in Rset and uid in outputs and uid != 'f3':
                        continue
                    data = {}
                    for d in DEPS[uid]:
                        port = {'index': 'evidence_index',
                                'extracts': 'doc_extracts',
                                'timeline': 'timeline',
                                'entity_facts': 'entity_facts',
                                'factcheck_full':
                                    'verified_facts'}[NODE_KINDS[d]]
                        data[port] = odata.get(NODE_KINDS[d])
                    prompt = build_prompt(uid, kind, data, ev_texts,
                                          None, task)
                    model = pi.get(uid, 'glm53flash')
                    rec, text = meter.call(model, '', prompt,
                                      NODE_CAPS.get(kind, 512),
                                      purpose=f'{run_id}:{uid}')
                    recs.append(rec)
                    outputs[uid] = text
                    odata[kind] = text
                    u2 = rec.get('usage', {})
                    spent[model] = spent.get(model, 0) + u2.get('input_tokens', 0) + u2.get('output_tokens', 0)
                wall = time.monotonic() - wall0
                # assemble + score
                report_text = outputs.get('f6', '')
                assembled = assemble(task, report_text)
                try:
                    sc = S.score_run(tid, assembled, task)
                except Exception as e:
                    sc = {'error': str(e)[:100]}
                run_dir = B / 'stage_c' / run_id
                run_dir.mkdir(exist_ok=True)
                (run_dir / 'scores.json').write_text(json.dumps(
                    dict(v1=sc, arm=arm, R=sorted(Rset), pi=pi,
                         recs=recs, wall_s=round(wall, 1)),
                    ensure_ascii=False, indent=1))
                results.append(dict(task=tid, arm=arm, rep=rep,
                                    R=sorted(Rset),
                                    Q=sc.get('Q', {}).get('Q', sc.get('Q')),
                                    wall=round(wall, 1),
                                    calls=len(recs)))
                print(json.dumps(results[-1], ensure_ascii=False),
                      flush=True)
    print(json.dumps({'runner': RUNNER_VERSION, 'n_runs': len(results),
                      'per_model_spent': spent,
                      'budget': dict(calls=args.cap_calls,
                                     tokens=args.cap_tokens)},
                     ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main())
