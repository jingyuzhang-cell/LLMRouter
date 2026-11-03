"""Independent terminal Q/E/K scorer (frozen interface, offline, zero model calls).

INPUT
  run_trace : jsonl per node per attempt + planning + retrieval accounting + wall window
              (schema: traces_schema/trace_schema.json)
  deliverable : json produced by the system under evaluation for one task
  task_id : public task record (tasks/tasks_frozen.jsonl)

OUTPUT  Q/E/K with full sub-metric breakdown. Definitions are frozen in
PROTOCOL_EVAL_V1.md; any change requires re-freezing with a new version tag.

Q (quality, [0,1]) = .55*coverage + .25*citation_accuracy + .20*unknown_compliance
                    - hallucination_penalty (capped .15)
  coverage        = (full + .5*partial) / n_silver        (silver-tier match)
  citation_acc    = correct-doc citations / cited covered facts
  unknown_compl   = boundary items explicitly marked UNKNOWN (probe keywords)
  hallucination   = dates asserted outside silver∪evidence (each -.05, cap -.15)
E (efficiency, VECTOR — never collapsed): tokens & wall-time, full-cost accounting
  {C_model_first, C_model_repair, C_planning, C_retrieval_chars, C_program_ms,
   L_service_s, L_wall_s}  (+ derived totals; reuse must be marked and costs 0 new)
K (reliability & deadline):
  {schema_conformance, first_attempt_contract_rate, repair_count, aborted,
   deadline_compliance} ; run verdict COMPLETE / INCOMPLETE / ABORTED
"""
import json
import re
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from bench_common import norm, all_dates  # noqa: E402

BOUNDARY_PROBES = {'社交媒体': ['热度', '社交媒体', '舆情情感', '传播'], '股价': ['股价走势', '股价因果', '实际股价'],
                   '退市': ['退市整理期'], '资金流水': ['资金流水'], '完整表格': ['完整表格', '具体调减金额的完整'],
                   '问答条目': ['问答条目']}


def load_task(task_id):
    for l in (BENCH / 'tasks' / 'tasks_frozen.jsonl').read_text().splitlines():
        t = json.loads(l)
        if t['task_id'] == task_id:
            return t
    raise KeyError(task_id)


def load_silver(task_id):
    return json.loads((BENCH / 'scoring' / 'silver' / f'{task_id}.silver.json').read_text())


def evidence_dates(task):
    dates = set()
    for d in task['evidence_doc_ids']:
        dates |= set(all_dates((BENCH / 'evidence' / 'texts' / f'{d}.txt').read_text()))
    dates |= {f['answer'] for f in load_silver(task['task_id'])['silver'] if f['answer_type'] == 'date'}
    return dates


def _tier(fact, text):
    t = norm(text)
    if fact['answer_type'] == 'date':
        # compare the RAW ISO answer against extracted ISO dates (norm would strip '-')
        return 'full' if str(fact['answer']) in all_dates(text) else False
    a = norm(fact['answer'])
    if fact['answer_type'] == 'amount':
        return 'full' if (a in t or a.rstrip('元%股') in t) else False
    if a in t:
        return 'full'
    segs = [s for s in re.split(r'[，,。;；:：、（）()\s]+', fact['answer']) if len(s) >= 5]
    return 'partial' if any(norm(s) in t for s in segs) else False


def _unknown_compliance(task, deliverable_text):
    items = task['unknown_boundary']
    if not items:
        return 1.0, []
    marks = [ln for ln in re.split(r'[。\n；;]', deliverable_text)
             if re.search(r'UNKNOWN|无法确认|未能确认|证据(集)?未(含|覆盖)', ln)]
    ok = 0
    per = []
    for item in items:
        probes = next((v for k, v in BOUNDARY_PROBES.items() if k in item), ['。'])
        hit = any(all(p in ln or any(q in ln for q in probes) for p in []) or
                  any(p in ln for p in probes) for ln in marks)
        ok += int(hit)
        per.append({'item': item[:40], 'marked': hit})
    return ok / len(items), per


def score_quality(task, deliverable_text, silver, edates):
    tiers = {f['fact_id']: _tier(f, deliverable_text) for f in silver}
    full = sum(1 for v in tiers.values() if v == 'full')
    partial = sum(1 for v in tiers.values() if v == 'partial')
    coverage = (full + 0.5 * partial) / max(1, len(silver))
    # citations: doc_id mentions near each covered fact answer
    cited_ok = cited_n = 0
    for f in silver:
        if not tiers[f['fact_id']]:
            continue
        frag = f['answer'][:4] if f['answer_type'] == 'date' else norm(f['answer'])[:6]
        j = deliverable_text.find(frag)
        window = deliverable_text[max(0, j - 130):j + 170] if j >= 0 else deliverable_text
        cites = [d for d in task['evidence_doc_ids'] if d in window] or \
                [d for d in task['evidence_doc_ids'] if d in deliverable_text]
        if not cites:
            continue
        cited_n += 1
        cited_ok += int(f['evidence_doc'] in cites)
    citation_acc = cited_ok / cited_n if cited_n else None
    uc, per_uc = _unknown_compliance(task, deliverable_text)
    bad_dates = [d for d in all_dates(deliverable_text)
                 if d not in edates and d > '2015-01-01']
    hp = min(0.15, 0.05 * len(bad_dates))
    Q = 0.55 * coverage + 0.25 * (citation_acc if citation_acc is not None else 0.0) \
        + 0.20 * uc - hp
    return {'Q': round(max(0.0, Q), 4), 'coverage': round(coverage, 4),
            'tiers': {k: v for k, v in tiers.items()}, 'coverage_full': full,
            'coverage_partial': partial, 'citation_accuracy': round(citation_acc, 4) if citation_acc is not None else None,
            'unknown_compliance': round(uc, 4), 'unknown_detail': per_uc,
            'hallucination_dates': bad_dates[:6], 'hallucination_penalty': hp,
            'reference_label': 'SILVER (machine-built; not gold)'}


def score_efficiency(trace):
    nodes = trace.get('nodes', [])
    first = sum(n['usage']['in'] + n['usage']['out'] for n in nodes if n.get('attempt') == 1)
    repair = sum(n['usage']['in'] + n['usage']['out'] for n in nodes if n.get('attempt', 1) > 1)
    plan = trace.get('planning', {})
    plan_tok = plan.get('usage', {}).get('in', 0) + plan.get('usage', {}).get('out', 0) if plan else 0
    ret = trace.get('retrieval', {})
    return {'C_model_first': first, 'C_model_repair': repair, 'C_planning': plan_tok,
            'C_retrieval_chars': ret.get('chars_injected', 0),
            'C_retrieval_calls': ret.get('calls', 0),
            'C_program_ms': trace.get('program_ms', 0),
            'C_total_tokens': first + repair + plan_tok,
            'L_service_s': round(sum(n.get('latency_s', 0) for n in nodes)
                                 + (plan.get('latency_s') or 0), 3),
            'L_wall_s': trace.get('wall_s'),
            'reuse_events': trace.get('reuse_events', 0),
            'note': 'E is a VECTOR; never collapse to a scalar for cross-system claims'}


def score_reliability(task, trace, deliverable):
    nodes = trace.get('nodes', [])
    n_att = len(nodes)
    first_ok = sum(1 for n in nodes if n.get('attempt') == 1 and n.get('parse_status') == 'OK')
    required = [f['field'] for f in task['deliverable_schema'] if f['required']]
    present = [f for f in required if deliverable and deliverable.get(f) not in (None, '', [], {})]
    schema_conf = len(present) / len(required) if required else 1.0
    deadline_ok = (trace.get('wall_s') is not None and trace['wall_s'] <= task['deadline_s'])
    aborted = trace.get('status') == 'ABORTED'
    verdict = 'ABORTED' if aborted else ('COMPLETE' if schema_conf == 1.0 else 'INCOMPLETE')
    return {'schema_conformance': round(schema_conf, 4),
            'first_attempt_contract_rate': round(first_ok / max(1, n_att), 4),
            'attempts_total': n_att, 'repair_count': sum(1 for n in nodes if n.get('attempt', 1) > 1),
            'deadline_compliance': bool(deadline_ok), 'verdict': verdict,
            'missing_required_fields': [f for f in required if f not in present]}


def score_run(run_trace, deliverable):
    task = load_task(run_trace['task_id'])
    silver = load_silver(task['task_id'])['silver']
    edates = evidence_dates(task)
    text = json.dumps(deliverable, ensure_ascii=False)
    return {'run_id': run_trace.get('run_id'), 'system_id': run_trace.get('system_id'),
            'task_id': task['task_id'],
            'Q': score_quality(task, text, silver, edates),
            'E': score_efficiency(run_trace),
            'K': score_reliability(task, run_trace, deliverable)}
