"""Integration-layer metric mapping (ADDENDUM v1.1) — frozen v1 outputs -> unified taxonomy.

MOTIVATION (integration ruling): the name "E" collided across systems. Unified names:
  Q          terminal content quality (+ sub-metrics)              <- v1 Q (unchanged)
  E_evidence source location & evidence SUFFICIENCY (support-verified) <- NEW, derived
  K          output contract & legality                             <- v1 K.contract parts
  C          full cost                                              <- v1 E.cost parts
  L          true end-to-end wall clock                             <- v1 E.latency parts
  Reliability execution reliability / completion / on-time          <- v1 K.reliability parts

This module NEVER modifies qe_k_scorer.py or PROTOCOL_EVAL_V1.md (their hashes stay
frozen); it is a versioned adapter. The v1 sub-metric `citation_accuracy` is
"citation presence at the right doc"; v1.1 adds the two support-verified measures:
  evidence_support_rate   — of covered facts, the share whose SUPPORTING EVIDENCE
                            (silver quote) actually appears in the chunks THIS run
                            retrieved (what the system really had access to);
  citation_support_rate   — of covered facts with a citation, the share whose CITED
                            DOCUMENT contains the supporting evidence.
  retrieval_self_sufficiency — silver-quote coverage of the run's retrieved chunks,
                            reported STANDALONE so retrieval advantage is never
                            mistaken for scheduling advantage (ruling §3-1).
"""
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / 'scoring'))
sys.path.insert(0, str(BENCH / 'evidence'))
from bench_common import norm                       # noqa: E402
import qe_k_scorer as S                             # noqa: E402
import retrieval_api as R                           # noqa: E402

FIELD_MAP = {  # explicit v1 -> unified mapping (documentation-as-code)
    'Q.value': 'Q.value', 'Q.coverage': 'Q.sub.coverage',
    'Q.citation_accuracy': 'Q.sub.citation_presence_rate (v1; superseded-by E_evidence.citation_support_rate)',
    'Q.unknown_compliance': 'Q.sub.unknown_compliance',
    'Q.hallucination_penalty': 'Q.sub.hallucination_penalty',
    'E.C_model_first': 'C.model_first', 'E.C_model_repair': 'C.model_repair',
    'E.C_planning': 'C.planning', 'E.C_retrieval_chars': 'C.retrieval_chars',
    'E.C_retrieval_calls': 'C.retrieval_calls', 'E.C_program_ms': 'C.program_ms',
    'E.C_total_tokens': 'C.total_tokens',
    'E.L_service_s': 'L.service_s', 'E.L_wall_s': 'L.wall_s', 'E.reuse_events': 'C.reuse_events',
    'K.schema_conformance': 'Reliability.schema_conformance', 'K.verdict': 'Reliability.verdict',
    'K.deadline_compliance': 'Reliability.deadline_compliance',
    'K.first_attempt_contract_rate': 'K.first_attempt_contract_rate',
    'K.repair_count': 'K.repair_count', 'K.attempts_total': 'K.attempts_total',
}


def run_retrieval_chunks(run_id):
    """Chunk texts this run actually retrieved, from the retrieval audit log."""
    chunks = []
    logf = BENCH / 'evidence' / 'retrieval_log.jsonl'
    if not logf.exists():
        return chunks
    for line in logf.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get('run_id') == run_id:
            for cid in e['chunk_ids']:
                doc_id, ci = cid.split('#c')
                idx = R.build_chunk_index([doc_id])
                c = next(x for x in idx if x['chunk_id'] == cid)
                chunks.append(c)
    return chunks


def e_evidence(task, run_id, deliverable_text):
    silver = S.load_silver(task['task_id'])['silver']
    tiers = {f['fact_id']: S._tier(f, deliverable_text) for f in silver}
    covered = [f for f in silver if tiers[f['fact_id']]]
    got_chunks = run_retrieval_chunks(run_id)
    retrieved_text = norm(''.join(c['text'] for c in got_chunks))
    doc_texts = {d: norm((BENCH / 'evidence' / 'texts' / f'{d}.txt').read_text())
                 for d in task['evidence_doc_ids']}
    sup = sup_cited = cited_n = 0
    for f in covered:
        quote = norm(f['quote'])
        if quote in retrieved_text:
            sup += 1
        frag = f['answer'][:4] if f['answer_type'] == 'date' else norm(f['answer'])[:6]
        j = deliverable_text.find(frag)
        window = deliverable_text[max(0, j - 130):j + 170] if j >= 0 else deliverable_text
        cites = [d for d in task['evidence_doc_ids'] if d in window] or \
                [d for d in task['evidence_doc_ids'] if d in deliverable_text]
        if not cites:
            continue
        cited_n += 1
        if any(quote in doc_texts[d] for d in cites):
            sup_cited += 1
    self_suff = sum(1 for f in silver if norm(f['quote']) in retrieved_text)
    return {'evidence_support_rate': round(sup / len(covered), 4) if covered else None,
            'citation_support_rate': round(sup_cited / cited_n, 4) if cited_n else None,
            'retrieval_self_sufficiency': f'{self_suff}/{len(silver)}',
            'retrieval_self_sufficiency_rate': round(self_suff / len(silver), 4),
            'note': 'support = silver quote verbatim in the run-retrieved chunks / cited doc; '
                    'self-sufficiency is reported standalone so retrieval advantage is never '
                    'attributed to scheduling'}


def unified(score_run_result, run_trace):
    task = S.load_task(score_run_result['task_id'])
    deliverable_text = json.dumps(score_run_result.get('_deliverable', {}), ensure_ascii=False)
    v1q, v1e, v1k = score_run_result['Q'], score_run_result['E'], score_run_result['K']
    return {'schema': 'unified_metrics_v1_1', 'task_id': score_run_result['task_id'],
            'run_id': score_run_result.get('run_id'), 'system_id': score_run_result.get('system_id'),
            'Q': {'value': v1q['Q'], 'sub': {'coverage': v1q['coverage'],
                                             'citation_presence_rate_v1': v1q['citation_accuracy'],
                                             'unknown_compliance': v1q['unknown_compliance'],
                                             'hallucination_penalty': v1q['hallucination_penalty']}},
            'E_evidence': e_evidence(task, run_trace.get('run_id'), deliverable_text),
            'K': {'first_attempt_contract_rate': v1k['first_attempt_contract_rate'],
                  'repair_count': v1k['repair_count'], 'attempts_total': v1k['attempts_total'],
                  'missing_required_fields': v1k.get('missing_required_fields')},
            'C': {'model_first': v1e['C_model_first'], 'model_repair': v1e['C_model_repair'],
                  'planning': v1e['C_planning'], 'retrieval_chars': v1e['C_retrieval_chars'],
                  'retrieval_calls': v1e['C_retrieval_calls'], 'program_ms': v1e['C_program_ms'],
                  'total_tokens': v1e['C_total_tokens'], 'reuse_events': v1e.get('reuse_events', 0),
                  'price': 'UNKNOWN (subscription; tokens are the basis)'},
            'L': {'service_s': v1e['L_service_s'], 'wall_s': v1e['L_wall_s']},
            'Reliability': {'schema_conformance': v1k['schema_conformance'],
                            'verdict': v1k['verdict'],
                            'deadline_compliance': v1k['deadline_compliance']},
            'reference_label': 'SILVER (machine-built; not gold)'}


def score_unified(run_trace, deliverable):
    r = S.score_run(run_trace, deliverable)
    r['_deliverable'] = deliverable
    return unified(r, run_trace)
