"""STAGE-B runner: five-arm static-allocation comparison on FROZEN graphs (v stage-b-v1).

Arms: homo_strong / homo_cheap / alloc_rule / alloc_router / alloc_static_opt.
Design frozen in STAGE_B_PLAN v1.2: same canonical graph per task across arms & reps
(allocation effect isolated), same retrieval budget/terminal contract/assembler/scorer,
NO cross-arm reuse (arm-tagged purposes), per-model quota hard stops (GLM<=130K,
Flash<=90K), zero mid-batch code changes. Refuses to execute without --authorize-stage-b.
"""
import argparse
import json
import sys
import time
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
P = Path('/root/capital_opinion_pilot')
sys.path.insert(0, str(B))
sys.path.insert(0, str(B / 'scoring'))
sys.path.insert(0, str(B / 'evidence'))
sys.path.insert(0, str(B / 'integration'))
sys.path.insert(0, str(P))
sys.path.insert(0, '/root/r3_own_pool')

import retrieval_api as R                        # noqa: E402
import qe_k_scorer as S                          # noqa: E402
import metric_mapping_v1_1 as M                  # noqa: E402
from pilot_common import Meter, BudgetExceeded   # noqa: E402
from bench_common import sha                     # noqa: E402
from canonical_assembler import (assemble, fair_final_prompt_suffix,  # noqa: E402
                                 normalize_contract_output)
import static_optimizer as SO                    # noqa: E402
from phase2_stage_a import SYSTEM_NODE, FINAL_CAP, load_task, ctx_table_for  # noqa: E402
from phase1_real_batch import NODE_CAPS          # noqa: E402

RUNNER_VERSION = 'stage-b-v1'
TASKS = ['T-P2', 'T-D1']
NODE_KINDS = {'f1': 'index', 'f2': 'extracts', 'f3': 'timeline', 'f4': 'entity_facts',
              'f5': 'factcheck_full', 'f6': 'report'}
KIND_OF = {'index': 'index', 'extracts': 'extracts', 'timeline': 'timeline',
           'entity_facts': 'entity_facts', 'factcheck_full': 'factcheck', 'report': 'report'}
DEPS = {'f1': [], 'f2': ['f1'], 'f3': ['f2'], 'f4': ['f2'], 'f5': ['f2', 'f3', 'f4'], 'f6': ['f5']}
PORTS = {'index': ['evidence_index'], 'extracts': ['doc_extracts'], 'timeline': ['timeline'],
         'entity_facts': ['entity_facts'], 'factcheck_full': ['verified_facts'], 'report': ['report']}
QUOTA = {'glm53': 130000, 'glm53flash': 90000}


def assignments_for(task):
    kinds = {n: KIND_OF[k] for n, k in NODE_KINDS.items()}
    homo_strong_c = sum(SO.COST[k]['glm53'] for k in kinds.values())
    sopt = SO.optimize(kinds, budget_tokens=int(homo_strong_c * 0.75), max_latency_s=40.0,
                       quota_flash=90000)
    return {'homo_strong': {n: 'glm53' for n in NODE_KINDS},
            'homo_cheap': {n: 'glm53flash' for n in NODE_KINDS},
            'alloc_rule': {n: ('glm53' if v == 'glm53' else 'glm53flash')
                           for n, v in SO.rule_assignment(kinds).items()},
            'alloc_router': {n: ('glm53' if v == 'glm53' else 'glm53flash')
                             for n, v in SO.router_assignment(kinds).items()},
            'alloc_static_opt': {n: ('glm53' if v == 'glm53' else 'glm53flash')
                                 for n, v in sopt['assignment'].items()}}, sopt


def run_node_b(meter, run_id, tid, uid, kind, model, subtask, data, inject_terms,
               spent):
    task = load_task(tid)
    user = ('Execute the subtask. Return only COMPACT JSON matching output ports:\n'
            + json.dumps({'subtask': subtask, 'inputs': data, 'output_ports': PORTS[NODE_KINDS[uid]]},
                         ensure_ascii=False))
    final_node = NODE_KINDS[uid] == 'report'
    if final_node:
        user += fair_final_prompt_suffix(tid)
    if inject_terms and NODE_KINDS[uid] == 'extracts':
        chunks, used = R.retrieve(tid, run_id, inject_terms, 3200)
        user += '\n\n检索注入证据（逐字片段）：\n' + '\n--\n'.join(
            f"[{c['doc_id']}@{c['start']}-{c['end']}] {c['text']}" for c in chunks)
    cap = FINAL_CAP if final_node else NODE_CAPS.get(NODE_KINDS[uid], 448)
    schema_fields = {f['field'] for f in task['deliverable_schema']}
    ent = None
    rec = None
    for attempt in (1, 2):
        if spent[model] + 900 > QUOTA[model]:   # conservative per-model quota guard
            return None, None, spent
        try:
            rec, txt = meter.call(model, SYSTEM_NODE, user + (f'\n\n上次失败：{ent}' if ent else ''),
                                  max_tokens=cap, purpose=f'{run_id}:{uid}:a{attempt}', timeout_s=60)
        except BudgetExceeded:
            return None, None, spent
        spent[model] = rec['usage']['input_tokens'] + rec['usage']['output_tokens'] + spent.get(model, 0) \
            if isinstance(spent, dict) else spent[model]
        try:
            if final_node:
                obj, meta = normalize_contract_output(
                    txt, sorted(schema_fields | {'unknown_marks'}))
                obj = {'report': obj}
            else:
                obj, meta = normalize_contract_output(txt, PORTS[NODE_KINDS[uid]])
            entry = {'node_id': uid, 'kind': NODE_KINDS[uid], 'model': model, 'attempt': attempt,
                     'call_id': rec['call_id'],
                     'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']},
                     'latency_s': rec['latency_s'], 'parse_status': 'OK',
                     'contract_normalization': meta,
                     'truncated': rec['stop_reason'] == 'max_tokens'}
            return obj, entry, spent
        except Exception as e:
            ent = f'{e}'[:100]
    return None, {'node_id': uid, 'kind': NODE_KINDS[uid], 'model': model, 'attempt': 2,
                  'usage': {'in': rec['usage']['input_tokens'] if rec else 0,
                            'out': rec['usage']['output_tokens'] if rec else 0},
                  'latency_s': rec['latency_s'] if rec else 0.0,
                  'parse_status': f'FAIL:{ent}', 'truncated': None}, spent


def run_arm(meter, tid, arm, assign, sopt_meta, rep, spent):
    task = load_task(tid)
    run_id = f'SB-{arm}-{tid}-r{rep}'
    t0 = time.monotonic()
    terms = [w for w in task['question'].replace('，', ' ').replace('：', ' ').split() if len(w) >= 2][:12] + \
        ['处罚', '停牌', '换股', '差错更正']
    outputs, trace_nodes, injected, failed = {}, [], 0, None
    for uid in ['f1', 'f2', 'f3', 'f4', 'f5', 'f6']:
        data = {}
        for d in DEPS[uid]:
            port = 'evidence_index' if NODE_KINDS[d] == 'index' else (
                'doc_extracts' if NODE_KINDS[d] == 'extracts' else
                'timeline' if NODE_KINDS[d] == 'timeline' else
                'entity_facts' if NODE_KINDS[d] == 'entity_facts' else 'verified_facts')
            outputs_port = {'index': 'evidence_index', 'extracts': 'doc_extracts',
                            'timeline': 'timeline', 'entity_facts': 'entity_facts',
                            'factcheck_full': 'verified_facts'}[NODE_KINDS[d]]
            data[outputs_port if NODE_KINDS[d] != 'factcheck_full' else 'doc_extracts'] = outputs[d][outputs_port] \
                if NODE_KINDS[d] != 'factcheck_full' else outputs[d]['verified_facts']
        # factcheck consumes extracts+timeline+entity; report consumes verified_facts
        if NODE_KINDS[uid] == 'factcheck_full':
            data = {'doc_extracts': outputs['f2']['doc_extracts'],
                    'timeline': outputs['f3']['timeline'],
                    'entity_facts': outputs['f4']['entity_facts']}
        elif NODE_KINDS[uid] == 'report':
            data = {'verified_facts': outputs['f5']['verified_facts']}
        elif NODE_KINDS[uid] in ('timeline', 'entity_facts'):
            data = {'doc_extracts': outputs['f2']['doc_extracts']}
        elif NODE_KINDS[uid] == 'extracts':
            data = {'evidence_index': outputs['f1']['evidence_index']}
        obj, entry, spent = run_node_b(meter, run_id, tid, uid, NODE_KINDS[uid], assign[uid],
                                       SUBTASKS[NODE_KINDS[uid]], data,
                                       inject_terms=terms, spent=spent)
        if entry:
            trace_nodes.append(entry)
        if obj is None:
            if entry is None:
                failed = f'quota stop at {uid}'
            else:
                failed = f'node {uid} failed contract'
            break
        outputs[uid] = obj
        if NODE_KINDS[uid] == 'extracts':
            injected = 3200
    raw_final = outputs.get('f6', {}).get('report', '') if 'f6' in outputs else ''
    deliverable = assemble(task, raw_final)
    trace = {'run_id': run_id, 'system_id': arm, 'task_id': tid,
             'config_hash': sha({'runner': RUNNER_VERSION, 'arm': arm,
                                 'assignment': assign, 'optimizer_meta': sopt_meta if arm == 'alloc_static_opt' else None}),
             'status': 'COMPLETE' if not failed else 'INCOMPLETE',
             'planning': {'calls': 0, 'usage': {'in': 0, 'out': 0}, 'latency_s': 0.0,
                          'note': 'static optimizer computed offline (0 model calls)' if arm == 'alloc_static_opt' else 'fixed assignment'},
             'retrieval': {'calls': 1 if injected else 0, 'chars_injected': injected},
             'nodes': trace_nodes, 'reuse_events': 0,
             'program_ms': 5.0 if arm == 'alloc_static_opt' else 0.0,
             'wall_s': round(time.monotonic() - t0, 3),
             'deliverable_ref': f'stage_b/{run_id}/deliverable.json',
             'notes': f'STAGE-B REAL run arm={arm}; frozen graph; assignment={assign}'
                      + (f'; FAILED={failed}' if failed else '')}
    out = B / 'stage_b' / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / 'trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=1))
    (out / 'deliverable.json').write_text(json.dumps(deliverable, ensure_ascii=False, indent=1))
    v1 = S.score_run(trace, deliverable)
    uni = M.score_unified(trace, deliverable)
    (out / 'scores.json').write_text(json.dumps(
        {'v1': {k: v1[k] for k in ('Q', 'E', 'K')}, 'unified': uni}, ensure_ascii=False, indent=1))
    return {'run_id': run_id, 'arm': arm, 'task': tid, 'status': trace['status'],
            'Q': v1['Q']['Q'], 'coverage': v1['Q']['coverage'], 'verdict': v1['K']['verdict'],
            'C_total': uni['C']['total_tokens'], 'L_service': uni['L']['service_s'],
            'truncated_nodes': [n['node_id'] for n in trace_nodes if n.get('truncated')],
            'failed_reason': failed}


SUBTASKS = {'index': '建立证据索引与角色分类（含公开日期）',
            'extracts': '抽取关键事实片段：逐字引文(<=40字)+doc_id+日期',
            'timeline': '事件时间线：日期(YYYY-MM-DD)+事件+doc_id',
            'entity_facts': '涉及主体与结论事实：数值+doc_id',
            'factcheck_full': '对照引文交叉核查（doc_extracts+timeline+entity_facts），标注UNRESOLVED',
            'report': '按终端交付合同合成调查结论'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--authorize-stage-b', action='store_true')
    ap.add_argument('--reps', type=int, default=2)
    ap.add_argument('--cap-calls', type=int, default=170)
    ap.add_argument('--cap-tokens', type=int, default=220000)
    args = ap.parse_args()
    if not args.authorize_stage_b:
        plans = {}
        for tid in TASKS:
            a, sopt = assignments_for(tid)
            plans[tid] = {'assignments': a, 'static_opt_meta': sopt}
        print(json.dumps({'mode': 'PLAN-ONLY (refuses without --authorize-stage-b)',
                          'assignments': plans, 'caps': {'calls': args.cap_calls,
                          'tokens': args.cap_tokens, 'per_model': QUOTA}}, ensure_ascii=False, indent=1))
        return 0
    meter = Meter(ledger_path=B / 'stage_b' / 'model_call_ledger_stage_b.jsonl',
                  max_calls=args.cap_calls, max_guaranteed_actual=args.cap_tokens)
    spent = {'glm53': 0, 'glm53flash': 0}
    results = []
    for tid in TASKS:
        assign_map, sopt = assignments_for(tid)
        for rep in range(1, args.reps + 1):
            for arm in ['homo_strong', 'homo_cheap', 'alloc_rule', 'alloc_router', 'alloc_static_opt']:
                try:
                    results.append(run_arm(meter, tid, arm, assign_map[arm], sopt, rep, spent))
                except BudgetExceeded as e:
                    results.append({'task': tid, 'arm': arm, 'status': 'BUDGET_STOP', 'reason': str(e)[:120]})
                    break
    print(json.dumps({'runner': RUNNER_VERSION, 'runs': results,
                      'per_model_spent': spent, 'budget': meter.summary()}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    sys.exit(main())
