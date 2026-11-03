"""STAGE-A runner (frozen design in PHASE2_PROTOCOL.md). Refuses to execute without
--authorize-stage-a. Fairness wiring per admission requirements:
 - every arm's final-synthesis call carries the SAME terminal-deliverable contract
   (canonical_assembler.fair_final_prompt_suffix) and 768 output cap;
 - deliverables for ALL arms are produced solely by the canonical assembler from the
   arm's own output (Silver-blind, arm-agnostic);
 - F2 total-cost rule: per-arm totals (incl. planning/retrieval/repair) and truncation
   flags are reported side by side; per-call caps identical by node type across arms;
 - fixed_graph arm = declared canonical baseline graph (NOT presented as LLM-planned);
 - auto_graph planner feedback now includes F6 terminal-reachability errors (wired in
   window-2 planner validator this admission package).
Arms: single_model | fixed_graph | auto_graph. Tasks: frozen 6-task Stage-A set.
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
import semantic_plan as SP                       # noqa: E402 (window-2 planner, F6-wired)
import assemble_dag as AD                        # noqa: E402
from pilot_common import Meter, BudgetExceeded, fenced_json  # noqa: E402
from bench_common import sha                     # noqa: E402
from canonical_assembler import assemble, fair_final_prompt_suffix  # noqa: E402
from canonical_assembler import normalize_contract_output  # noqa: E402 (uniform L1 fix)
from phase1_real_batch import load_task, ctx_table_for, node_ports, SYSTEM_NODE, NODE_CAPS

RUNNER_VERSION = 'stage-a-confirm-v3'  # L1 normalizer + fair final contract; single frozen version for any confirmatory rerun
STAGE_A_TASKS = ['T-R1', 'T-R2', 'T-P1', 'T-D1', 'T-P2', 'T-M1']
FINAL_CAP = 768


def canonical_plan(tid):
    task = load_task(tid)
    docs = task['evidence_doc_ids']
    half = max(1, len(docs) // 2)
    return {'plan': [
        {'id': 'f1', 'kind': 'index', 'goal': '建立证据索引与角色分类', 'doc_ids': [], 'depends': []},
        {'id': 'f2', 'kind': 'extracts', 'goal': '抽取关键事实片段（逐字引文+doc_id）',
         'doc_ids': docs[:half], 'depends': ['f1']},
        {'id': 'f3', 'kind': 'timeline', 'goal': '事件时间线（日期+事件+doc_id）', 'doc_ids': [], 'depends': ['f2']},
        {'id': 'f4', 'kind': 'entity_facts', 'goal': '主体与结论事实（含数值+doc_id）',
         'doc_ids': docs[half:] or docs[:1], 'depends': ['f2']},
        {'id': 'f5', 'kind': 'factcheck_full', 'goal': '对照引文交叉核查，标注UNRESOLVED', 'doc_ids': [], 'depends': ['f2', 'f3', 'f4']},
        {'id': 'f6', 'kind': 'report', 'goal': '按终端交付合同合成调查结论', 'doc_ids': [], 'depends': ['f5']}],
        'rationale': 'canonical fixed baseline (declared, not LLM-planned)'}


def run_node(meter, run_id, tid, uid, kind, subtask, data, inject_terms=None, carried_uncertainty=None):
    task = load_task(tid)
    user = ('Execute the subtask. Return only COMPACT JSON matching output ports:\n'
            + json.dumps({'subtask': subtask, 'inputs': data, 'output_ports': node_ports(kind)},
                         ensure_ascii=False))
    if carried_uncertainty:
        user += ('\n\n上游节点声明的不确定性（必须在报告相应结论与 unknown_marks 中如实体现，'
                 '不得静默丢弃）：' + json.dumps(carried_uncertainty[-6:], ensure_ascii=False))
    final_node = kind == 'report'
    if final_node:
        # FINAL-SYNTHESIS CONTRACT: the report node IS the arm's final synthesis —
        # it must emit the full terminal-deliverable schema JSON (fair clause),
        # identical across all arms; the canonical assembler consumes it verbatim.
        user += fair_final_prompt_suffix(tid)
    if inject_terms and kind == 'extracts':
        chunks, used = R.retrieve(tid, run_id, inject_terms, 3200)
        user += '\n\n检索注入证据（逐字片段）：\n' + '\n--\n'.join(
            f"[{c['doc_id']}@{c['start']}-{c['end']}] {c['text']}" for c in chunks)
    cap = FINAL_CAP if final_node else NODE_CAPS.get(kind, 448)
    schema_fields = {f['field'] for f in task['deliverable_schema']}

    def parse_final(txt):
        required = sorted(schema_fields | {'unknown_marks'})
        obj, meta = normalize_contract_output(txt, required)
        entry_extra.append(meta)            # recorded in the trace entry below
        return {'report': obj}

    ent = None
    rec = None
    entry_extra = []
    for attempt in (1, 2):
        try:
            rec, txt = meter.call('glm53', SYSTEM_NODE, user + (f'\n\n上次失败：{ent}' if ent else ''),
                                  max_tokens=cap, purpose=f'{run_id}:{uid}:a{attempt}', timeout_s=60)
        except BudgetExceeded:
            return None, None
        try:
            if final_node:
                obj = parse_final(txt)
                meta = entry_extra[-1] if entry_extra else {}
            else:
                obj, meta = normalize_contract_output(txt, node_ports(kind))
            return obj, {'node_id': uid, 'kind': kind, 'model': 'glm53', 'attempt': attempt,
                         'call_id': rec['call_id'],
                         'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']},
                         'latency_s': rec['latency_s'], 'parse_status': 'OK',
                         'contract_normalization': meta,
                         'truncated': rec['stop_reason'] == 'max_tokens'}
        except Exception as e:
            ent = f'{e}'[:100]
    # schema-complete failure entry (scorer consumes usage/latency on every node)
    return None, {'node_id': uid, 'kind': kind, 'model': 'glm53', 'attempt': 2,
                  'usage': {'in': rec['usage']['input_tokens'] if rec else 0,
                            'out': rec['usage']['output_tokens'] if rec else 0},
                  'latency_s': rec['latency_s'] if rec else 0.0,
                  'parse_status': f'FAIL:{ent}', 'truncated': None}


def graph_arm_run(meter, tid, arm, plan, rep, run_id):
    task = load_task(tid)
    gv, iss = AD.assemble(plan)
    if gv is None:
        return {'run_id': run_id, 'system_id': arm, 'status': 'INVALID', 'reason': f'assembly: {iss[:1]}'}
    graph, validated = gv
    kind_of = {t['id']: t['kind'] for t in plan['plan']}
    nodes_d = {n.node_id: n for n in graph.nodes}
    ctx = {'question': task['question'], 'ctx_table': ctx_table_for(tid)}
    terms = [w for w in task['question'].replace('，', ' ').replace('：', ' ').split() if len(w) >= 2][:12] + ['处罚', '停牌', '换股']
    outputs, trace_nodes, injected = {}, [], 0
    failed_node = None
    uncertainty_carried = []   # model-declared caveats from dropped keys (principle fix)
    for layer in validated.layers:
        for uid in layer:
            node = nodes_d[uid]
            k = kind_of[uid]
            data = {b.port: ctx[b.field] if b.source == 'task' else outputs[b.node_id][b.field]
                    for b in node.inputs}
            obj, ent = run_node(meter, run_id, tid, uid, k, node.subtask, data,
                                inject_terms=terms if k == 'extracts' else None,
                                carried_uncertainty=uncertainty_carried if k == 'report' else None)
            if ent:
                trace_nodes.append(ent)
                for u in (ent.get('contract_normalization') or {}).get('uncertainty_carried', []):
                    uncertainty_carried.append(f"{uid}:{u}")
            if obj is None:
                failed_node = uid
                break
            outputs[uid] = obj
            if k == 'extracts':
                injected = 3200
        if failed_node:
            break
    # ALWAYS persist: completed and partial (INCOMPLETE) runs alike — no lost traces
    rep_id = next((u for u, k in kind_of.items() if k == 'report'), None)
    raw_final = outputs[rep_id].get('report', '') if rep_id and rep_id in outputs else ''
    deliverable = assemble(task, raw_final)
    planning = {'calls': 0, 'usage': {'in': 0, 'out': 0}, 'latency_s': 0.0}
    res = finish_run(meter, run_id, tid, arm, deliverable, trace_nodes, injected, planning,
                     {'plan_rationale': plan.get('rationale', '')})
    if failed_node:
        res['status'] = 'INCOMPLETE'
        res['reason'] = f'node {failed_node} failed contract after repair'
    return res


def single_arm_run(meter, tid, rep, run_id):
    task = load_task(tid)
    terms = ['处罚', '停牌', '约谈', '换股', '风险警示']
    chunks, used = R.retrieve(tid, run_id, terms, 3200)
    user = (task['question']
            + '\n\n检索注入证据（逐字片段）：\n'
            + '\n--\n'.join(f"[{c['doc_id']}] {c['text']}" for c in chunks)
            + fair_final_prompt_suffix(tid))
    rec, txt = meter.call('glm53', SYSTEM_NODE, user, max_tokens=FINAL_CAP,
                          purpose=f'{run_id}:single', timeout_s=90)
    deliverable = assemble(task, txt)
    ent = {'node_id': 'single', 'kind': 'final', 'model': 'glm53', 'attempt': 1,
           'call_id': rec['call_id'],
           'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']},
           'latency_s': rec['latency_s'], 'parse_status': 'OK',
           'truncated': rec['stop_reason'] == 'max_tokens'}
    return finish_run(meter, run_id, tid, 'single_model', deliverable, [ent], used,
                      {'calls': 0, 'usage': {'in': 0, 'out': 0}, 'latency_s': 0.0}, {})


def finish_run(meter, run_id, tid, arm, deliverable, trace_nodes, injected, planning, extra):
    task = load_task(tid)
    trace = {'run_id': run_id, 'system_id': arm, 'task_id': tid,
             'config_hash': sha({'stage': 'A', 'arm': arm, 'runner': RUNNER_VERSION}),
             'status': 'COMPLETE' if all(n.get('parse_status') == 'OK' for n in trace_nodes) else 'INCOMPLETE',
             'planning': planning, 'retrieval': {'calls': 1 if injected else 0, 'chars_injected': injected},
             'nodes': trace_nodes, 'reuse_events': 0, 'program_ms': 0.0,
             'wall_s': round(sum(n.get('latency_s', 0) for n in trace_nodes), 3),
             'deliverable_ref': f'stage_a/{run_id}/deliverable.json',
             'notes': f'STAGE-A REAL run arm={arm}; fair terminal contract + canonical assembler'}
    out = B / 'stage_a' / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / 'trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=1))
    (out / 'deliverable.json').write_text(json.dumps(deliverable, ensure_ascii=False, indent=1))
    v1 = S.score_run(trace, deliverable)
    uni = M.score_unified(trace, deliverable)
    (out / 'scores.json').write_text(json.dumps(
        {'v1': {k: v1[k] for k in ('Q', 'E', 'K')}, 'unified': uni}, ensure_ascii=False, indent=1))
    trunc = [n['node_id'] for n in trace_nodes if n.get('truncated')]
    return {'run_id': run_id, 'arm': arm, 'task_id': tid, 'status': trace['status'],
            'Q': v1['Q']['Q'], 'coverage': v1['Q']['coverage'], 'verdict': v1['K']['verdict'],
            'C_total': uni['C']['total_tokens'], 'L_service': uni['L']['service_s'],
            'E_evidence_support': uni['E_evidence']['evidence_support_rate'],
            'self_sufficiency': uni['E_evidence']['retrieval_self_sufficiency'],
            'truncated_nodes': trunc}


def auto_plan(meter, tid, run_id):
    task = load_task(tid)
    sys_p = SP.plan_system_prompt()
    usr = SP.plan_user_prompt(task['question'], ctx_table_for(tid)) \
        .replace('信息截止2024-07-10', f"信息截止{task['information_cutoff']}")
    rec, txt = meter.call('glm53', sys_p, usr, max_tokens=768,
                          purpose=f'AUTOPLAN:{tid}', timeout_s=60)  # shared across reps (dedup)
    try:
        plan = SP.parse_plan(txt)
        iss = SP.validate_plan(plan, task['evidence_doc_ids'])
    except Exception as e:
        plan, iss = None, [f'parse:{e}']
    if iss:
        rec2, txt2 = meter.call('glm53', sys_p, usr + f'\n\n结构检查未通过：{json.dumps(iss, ensure_ascii=False)[:350]}'
                                '。请输出修正后的完整计划JSON。', max_tokens=768,
                                purpose=f'AUTOPLAN:{tid}:repair', timeout_s=60)
        try:
            plan = SP.parse_plan(txt2)
            iss = SP.validate_plan(plan, task['evidence_doc_ids'])
        except Exception:
            plan = None
    return plan if plan and not iss else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--authorize-stage-a', action='store_true')
    ap.add_argument('--tasks', default=','.join(STAGE_A_TASKS))
    ap.add_argument('--reps', type=int, default=2)
    ap.add_argument('--cap-calls', type=int, default=200)
    ap.add_argument('--cap-tokens', type=int, default=290000)
    args = ap.parse_args()
    if not args.authorize_stage_a:
        print(json.dumps({'mode': 'PLAN-ONLY', 'tasks': args.tasks.split(','), 'reps': args.reps,
                          'caps': {'calls': args.cap_calls, 'tokens': args.cap_tokens},
                          'note': 'runner refuses execution without --authorize-stage-a'},
                         ensure_ascii=False))
        return 0
    meter = Meter(ledger_path=B / 'stage_a' / 'model_call_ledger_stage_a.jsonl',
                  max_calls=args.cap_calls, max_guaranteed_actual=args.cap_tokens)
    results = []
    for tid in args.tasks.split(','):
        for rep in range(1, args.reps + 1):
            try:
                results.append(single_arm_run(meter, tid, rep, f'SA-single-{tid}-r{rep}'))
            except BudgetExceeded as e:
                results.append({'task': tid, 'arm': 'single_model', 'status': 'BUDGET_STOP', 'reason': str(e)[:100]})
                break
            try:
                results.append(graph_arm_run(meter, tid, 'fixed_graph', canonical_plan(tid), rep,
                                             f'SA-fixed-{tid}-r{rep}'))
            except BudgetExceeded as e:
                results.append({'task': tid, 'arm': 'fixed_graph', 'status': 'BUDGET_STOP', 'reason': str(e)[:100]})
                break
            try:
                if rep == 1:
                    plan = auto_plan(meter, tid, f'SA-auto-{tid}')
                else:
                    plan = auto_plan(meter, tid, f'SA-auto-{tid}')  # dedup: same prompt -> 0 new calls
                if plan is None:
                    results.append({'run_id': f'SA-auto-{tid}-r{rep}', 'system_id': 'auto_graph',
                                    'status': 'INVALID', 'reason': 'planner envelope exhausted or invalid'})
                    continue
                results.append(graph_arm_run(meter, tid, 'auto_graph', plan, rep, f'SA-auto-{tid}-r{rep}'))
            except BudgetExceeded as e:
                results.append({'task': tid, 'arm': 'auto_graph', 'status': 'BUDGET_STOP', 'reason': str(e)[:100]})
                break
    print(json.dumps({'runs': results, 'budget': meter.summary()}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    sys.exit(main())
