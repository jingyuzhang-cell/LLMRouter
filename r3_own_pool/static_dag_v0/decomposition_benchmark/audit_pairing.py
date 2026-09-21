"""Decomposition pairing audit: task-id set audit + per-record protocol audit.

Read-only. No model calls. Recomputable from frozen legacy artifacts.
Outputs:
  DECOMPOSITION_PAIRING_AUDIT.json
  decomposition_final_multihiertt_100.json
  decomposition_final_tatqa_200.json
"""
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
SD = ROOT / 'static_dag_v0'
OUT = SD / 'decomposition_benchmark'
BENCH_ROOT = SD  # legacy artifacts all live under static_dag_v0

FSC = SD / 'fresh_static_confirmation'
LIVE = SD / 'live_e2e'
TQB = SD / 'tatqa_benchmark'
SU = SD / 'scale_up'

MODELS = {
    'medium': {'path': 'Qwen2.5-7B-Instruct', 'served': 'Qwen/Qwen2.5-7B-Instruct'},
    'large': {'path': 'Qwen2.5-14B-Instruct-GPTQ-Int8', 'served': 'Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8'},
    'coder': {'path': 'Qwen2.5-Coder-7B-Instruct', 'served': 'Qwen/Qwen2.5-Coder-7B-Instruct'},
}
GEN_CFG = dict(temperature=0, top_p=1, max_tokens=512)


def decode(text):
    text = (text or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    return json.loads(text)


def parse_facts(answer):
    try:
        o = decode(answer)
        facts = o['facts']
        assert 0 < len(facts) <= 12
        for f in facts:
            assert type(f['value']) in (int, float)
            assert isinstance(f['evidence'], str) and f['evidence']
        return True
    except Exception:
        return False


def tq_n_ops(derivation):
    d = (derivation or '').strip()
    if not d:
        return 0
    plus = len(re.findall(r'[+*/]', d))
    minus = len(re.findall(r'(?<=[\d)])\s*-', d))
    return plus + minus


def mh_n_ops(program):
    return len(re.findall(r'\b(add|sub|mul|div)\b', program or ''))


def bucket(n):
    return '1-2' if n <= 2 else ('3' if n == 3 else '4+')


def main():
    mh = json.loads((FSC / 'TASKS.json').read_text())
    mh_uids = [t['uid'] for t in mh]
    tq_old = json.loads((TQB / 'TASKS.json').read_text())
    tq_new = json.loads((SU / 'TQ_TASKS.json').read_text())
    tq_uids = [t['uid'] for t in tq_old] + [t['uid'] for t in tq_new]
    assert len(set(mh_uids)) == 100 and len(set(tq_uids)) == 200

    rows = {json.loads(l)['key']: json.loads(l) for l in (SU / 'RESPONSES.jsonl').open()}
    mb = json.loads((LIVE / 'monolithic_baseline' / 'RESULTS.json').read_text())
    mh_mono_uids = [r['uid'] for r in mb['rows']] + [u for u in mh_uids[50:] if f'mh:{u}:mono' in rows]
    tq_mono_uids = [t['uid'] for t in tq_new if f'tq:{t["uid"]}:mono' in rows]

    # live_e2e traces (first 50 MH)
    live = {json.loads(l)['task_uid']: json.loads(l) for l in (LIVE / 'TRACES.jsonl').open()}
    live_gold_fallback = [u for u in mh_uids[:50]
                          if not live[u]['arms']['Static'].get('extraction_parse')]

    # FSC large-extraction parse status per MH task
    fsc_large = {}
    for line in (FSC / 'large_RESPONSES.jsonl').open():
        r = json.loads(line)
        if r.get('node_type') == 'extraction':
            fsc_large.setdefault(r['task_uid'], []).append(r)
    mh_ext_unparseable = [u for u in mh_uids
                          if not any(r.get('status') == 'delivered' and parse_facts(r['answer'])
                                     for r in fsc_large.get(u, []))]

    # TQ old-40 large-extraction parse status
    tqb_large = {}
    for line in (TQB / 'large_RESPONSES.jsonl').open():
        r = json.loads(line)
        if r.get('node_type') == 'extraction':
            tqb_large.setdefault(r['task_uid'], []).append(r)
    tq_old_ext_unparseable = [t['uid'] for t in tq_old
                              if not any(r.get('status') == 'delivered' and parse_facts(r['answer'])
                                         for r in tqb_large.get(t['uid'], []))]

    # TQ new-160 gold fallback (extraction parse failed at collection time)
    tq_new_fallback = [t['uid'] for t in tq_new
                       if not (rows.get(f'tq:{t["uid"]}:ext') or {}).get('status') == 'delivered'
                       or not parse_facts((rows.get(f'tq:{t["uid"]}:ext') or {}).get('answer'))]

    # old-40 reasoning prompts: verify all gold-fed
    gold_fed = 0
    for line in (TQB / 'medium_REQUESTS.jsonl').open():
        r = json.loads(line)
        if r.get('call_key', '').endswith(':rs'):
            if '"evidence": "gold"' in (r.get('prompt') or ''):
                gold_fed += 1
    assert gold_fed == 40

    audit = {
        'audit_version': '1.1',
        'created_unix': time.time(),
        'scope': 'strictly paired Monolithic-vs-DAG decomposition benchmark; task-id + protocol audit only; no model calls',
        'legacy_artifacts_preserved': {
            'MultiHiertt_mono_batch1': str(LIVE / 'monolithic_baseline' / 'RESULTS.json'),
            'MultiHiertt_mono_batch2': str(SU / 'RESPONSES.jsonl'),
            'MultiHiertt_dag_live_static': str(LIVE / 'TRACES.jsonl'),
            'MultiHiertt_dag_fsc_conditional': str(FSC / 'SCORED_MATRIX_EXEC.npz'),
            'TAT-QA_old40': str(TQB / 'TASKS.json'),
            'TAT-QA_new160': str(SU / 'TQ_TASKS.json'),
            'legacy_paired_analysis': str(SU / 'DECOMP_UTILITY.json'),
            'legacy_analysis_script': str(SD / 'scale_up_analyze.py'),
        },
        'model_versions_pinned': {
            k: dict(**v, provenance=str(ROOT / 'router_v2/label_repair_experiment/raw' / f'{k}_MODEL_PROVENANCE.json'))
            for k, v in MODELS.items()
        },
        'generation_config': GEN_CFG,
        'scorer_version': 'exec_calc (decompose_v1) for DAG; extract_value+close for mono; tolerance max(1e-4, 1e-4*|gold|)',
        'prompt_versions': {
            'extraction': 'eprompt v1 (tool_aware_v1.eprompt), verbatim across all four sources',
            'reasoning': 'sprompt v1 (tool_aware_v1.sprompt), verbatim; INPUT differs by source (gold vs actual)',
            'monolithic': 'MONO v1, identical template in monolithic_baseline.py and scale_up_collect.py; ctx truncated to 14000 chars',
        },
        'datasets': {},
    }

    # ---------- MultiHiertt ----------
    mh_groups = [
        dict(group='mh_mono_batch1_live_session', count=50, task_ids=mh_uids[:50],
             arm='monolithic', input_mode='question + full context (raw, no gold)',
             execution_mode='live', evidence_source='raw_context',
             model_version='Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8 (large)', prompt_version='MONO v1',
             scorer_version='extract_value + 1e-4 rel', status='reusable_for_paired_benchmark',
             note='collected in live_e2e server session; checkpoint SHA-pinned at engine startup'),
        dict(group='mh_mono_batch2_scaleup_session', count=50, task_ids=mh_uids[50:],
             arm='monolithic', input_mode='question + full context (raw, no gold)',
             execution_mode='live', evidence_source='raw_context',
             model_version='Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8 (large)', prompt_version='MONO v1',
             scorer_version='extract_value + 1e-4 rel', status='reusable_for_paired_benchmark',
             note='collected in scale_up server session; same prompt/model/checkpoint as batch1; legacy paired analysis used ONLY this batch (n=50)'),
        dict(group='mh_dag_live_static_first50', count=50, task_ids=mh_uids[:50],
             arm='dag', input_mode='actual extraction -> reasoning; GOLD fallback on extraction parse failure',
             execution_mode='live', evidence_source='actual_extraction + 4 gold-fallback tasks',
             model_version='reasoning model per task varies by frozen utility picks (medium 38 / coder 9 / large 3)',
             prompt_version='eprompt v1 + sprompt v1', scorer_version='exec_calc + 1e-4 rel',
             status='legacy_invalid_for_unified_benchmark',
             note='gold_fallback_task_ids=%s' % live_gold_fallback),
        dict(group='mh_dag_fsc_gold_conditioned_last50', count=50, task_ids=mh_uids[50:],
             arm='dag', input_mode='reasoning node fed GOLD facts by construction (conditional benchmark)',
             execution_mode='conditional_benchmark (not a live DAG)',
             evidence_source='gold_facts',
             model_version='Qwen/Qwen2.5-7B-Instruct (medium), column 0 of SCORED_MATRIX_EXEC',
             prompt_version='sprompt v1 with gold facts', scorer_version='frozen evaluator on gold-conditioned reasoning node',
             status='legacy_invalid_for_unified_benchmark',
             note='this group produced the legacy "+14.0pp" MH paired result (recomputed: mono 0.08 vs chain 0.22, diff +0.14 confirmed)'),
    ]
    mh_dag_set = set(mh_uids)
    mh_mono_set = set(mh_mono_uids)
    audit['datasets']['MultiHiertt'] = {
        'dataset': 'MultiHiertt',
        'dag_task_count': 100,
        'mono_task_count': len(mh_mono_set),
        'intersection_count': len(mh_dag_set & mh_mono_set),
        'dag_only_task_ids': sorted(mh_dag_set - mh_mono_set),
        'mono_only_task_ids': sorted(mh_mono_set - mh_dag_set),
        'duplicate_task_ids': [u for u, c in Counter(mh_uids).items() if c > 1],
        'dag_task_source': str(FSC / 'TASKS.json'),
        'split': 'audited unused MultiHiertt train (fresh holdout, not official test)',
        'protocol_group': mh_groups,
        'conclusion': ('mono exists for all 100 tasks (two sessions, same protocol); '
                       'NO task has a DAG arm under the unified protocol: '
                       'first 50 = live static with per-task varying models and 4 gold fallbacks; '
                       'last 50 = gold-conditioned conditional benchmark only. '
                       'Legacy paper number +14.0pp is a mono-vs-gold-conditioned-reasoning comparison, not a DAG comparison.'),
    }

    # ---------- TAT-QA ----------
    tq_groups = [
        dict(group='tq_old40_dag_gold_fed', count=40, task_ids=[t['uid'] for t in tq_old],
             arm='dag', input_mode='reasoning fed GOLD facts by construction (40/40 prompts verified evidence=gold)',
             execution_mode='live calls, gold-conditioned input', evidence_source='gold_facts',
             model_version='Qwen/Qwen2.5-7B-Instruct (medium)', prompt_version='sprompt v1 with gold facts',
             scorer_version='exec_calc with gold facts + 1e-4 rel (ext_r=None forces gold in legacy analysis)',
             status='legacy_invalid_for_unified_benchmark',
             note='no monolithic arm exists for these 40; large-extraction responses exist (2 unparseable: %s)' % tq_old_ext_unparseable),
        dict(group='tq_new160_dag_actual', count=160 - len(tq_new_fallback),
             task_ids=[t['uid'] for t in tq_new if t['uid'] not in tq_new_fallback],
             arm='dag', input_mode='actual large-extraction -> medium reasoning -> exec',
             execution_mode='live', evidence_source='actual_extraction',
             model_version='extraction Qwen2.5-14B-GPTQ-Int8 (large); reasoning Qwen2.5-7B (medium)',
             prompt_version='eprompt v1 + sprompt v1', scorer_version='exec_calc + 1e-4 rel',
             status='reusable_for_unified_benchmark'),
        dict(group='tq_new160_dag_gold_fallback', count=len(tq_new_fallback),
             task_ids=sorted(tq_new_fallback),
             arm='dag', input_mode='extraction parse failed -> reasoning fed GOLD literals (evidence=gold)',
             execution_mode='live', evidence_source='gold_facts (fallback)',
             model_version='extraction large; reasoning medium', prompt_version='eprompt v1 + sprompt v1',
             scorer_version='exec_calc + 1e-4 rel', status='legacy_invalid_for_unified_benchmark',
             note='recorded reasoning answers are gold-contaminated; must not be reused'),
        dict(group='tq_new160_mono', count=160, task_ids=[t['uid'] for t in tq_new],
             arm='monolithic', input_mode='question + full context (raw, no gold)',
             execution_mode='live', evidence_source='raw_context',
             model_version='Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8 (large)', prompt_version='MONO v1',
             scorer_version='extract_value + 1e-4 rel', status='reusable_for_paired_benchmark'),
    ]
    tq_dag_set = set(tq_uids)
    tq_mono_set = set(tq_mono_uids)
    audit['datasets']['TAT-QA'] = {
        'dataset': 'TAT-QA',
        'dag_task_count': 200,
        'mono_task_count': len(tq_mono_set),
        'intersection_count': len(tq_dag_set & tq_mono_set),
        'dag_only_task_ids': sorted(tq_dag_set - tq_mono_set),
        'mono_only_task_ids': sorted(tq_mono_set - tq_dag_set),
        'duplicate_task_ids': [u for u, c in Counter(tq_uids).items() if c > 1],
        'dag_task_sources': [str(TQB / 'TASKS.json'), str(SU / 'TQ_TASKS.json')],
        'split': 'dev (r3_own_pool/data/tatqa/tatqa_dataset_dev.json, git-clean at aeeabc8)',
        'protocol_group': tq_groups,
        'conclusion': ('mono missing for the old 40; old-40 DAG is gold-fed reasoning (40/40); '
                       '9/160 new tasks had gold fallback on extraction parse failure. '
                       'Legacy paper number -9.38pp mixes gold-fed and actual DAG arms with 160 mono.'),
    }

    # ---------- unified frozen protocol (three arms, v1.1 design decision) ----------
    audit['unified_frozen_protocol'] = {
        'definition': 'same task + same input + same scorer + same model capability; only whether decomposition is applied differs',
        'design_decision_v1_1': (
            'Three arms, not two. Mono-L vs DAG-L/L isolates the pure decomposition effect; '
            'DAG-L/L vs DAG-L/M isolates stage-level heterogeneous model allocation. '
            'Comparing Mono-L directly against DAG-L/M would confound decomposition with reasoning-model choice.'),
        'arms': {
            'Mono-L': dict(model='large', prompt='MONO v1', input='question + raw context (ctx[:14000])',
                           scoring='extract_value + tolerance 1e-4 rel'),
            'DAG-L/L': dict(extraction=dict(model='large', prompt='eprompt v1', input='question + raw context'),
                            reasoning=dict(model='large', prompt='sprompt v1',
                                           input='facts parsed from the large-extraction output; NEVER gold'),
                            execution='exec_calc over v0..v_{n-1} with the same facts; tolerance 1e-4 rel'),
            'DAG-L/M': dict(extraction=dict(model='large', prompt='eprompt v1', input='question + raw context (SHARED extraction with DAG-L/L)'),
                            reasoning=dict(model='medium', prompt='sprompt v1', input='same parsed facts as DAG-L/L'),
                            execution='exec_calc; tolerance 1e-4 rel'),
        },
        'research_questions': {'RQ-A': 'Mono-L vs DAG-L/L -> does decomposition itself help?',
                               'RQ-B': 'DAG-L/L vs DAG-L/M -> does heterogeneous stage allocation help after decomposition?'},
        'extraction_parse_failure_policy': 'deterministic DAG failure for BOTH DAG arms; NO gold fallback, NO retry; reasoning not called',
        'collection_policy': 'all three arms re-collected in one unified inference session (default); legacy cells are accuracy-reusable but latency is not comparable across sessions',
        'generation': GEN_CFG,
        'answer_normalization': 'regex Answer: <number> for mono; JSON expression for DAG reasoning',
        'no_gold_anywhere': True,
    }

    # ---------- rerun plan ----------
    mh_rerun_rsn = [u for u in mh_uids if u not in mh_ext_unparseable]
    tq_old_rerun_rsn = [t['uid'] for t in tq_old if t['uid'] not in tq_old_ext_unparseable]
    expect_fail = len(mh_ext_unparseable) + len(tq_old_ext_unparseable) + len(tq_new_fallback)
    expect_rsn = 300 - expect_fail
    audit['rerun_plan'] = {
        'policy': ('FULL FRESH unified session (default): every arm re-collected in one inference environment '
                   'after RealDetector completes; single-session Quality/Tokens/Latency accounting. '
                   'Legacy reuse remains possible for accuracy-only reporting (documented in legacy_reuse_option) '
                   'but is NOT the default for the formal paper results.'),
        'session': {
            'model_grouping': 'large: mono(300) -> extraction(300) -> DAG-L/L reasoning(<=300); then medium: DAG-L/M reasoning(<=300)',
            'gpu_guard': 'engine.start_model refuses to start when GPU busy or port 8128 occupied (protects RealDetector)',
            'resume': 'keyed ledger; completed keys skipped on resume',
            'timeout_per_call': 180, 'concurrency': 1,
        },
        'expected_calls': {
            'mono_large': 300,
            'extraction_large': 300,
            'dag_ll_reasoning_large': expect_rsn,
            'dag_lm_reasoning_medium': expect_rsn,
            'total_expected': 300 + 300 + 2 * expect_rsn,
            'worst_case_total': 1200,
            'expected_deterministic_dag_failures': expect_fail,
            'note': ('parse-failure estimate from legacy extraction (MH %d + TQ-old %d + TQ-new %d); '
                     'fresh extraction decides at runtime') % (len(mh_ext_unparseable), len(tq_old_ext_unparseable), len(tq_new_fallback)),
        },
        'legacy_reuse_option': {
            'mono': '100 MH + 160 TQ legacy mono rows are protocol-identical (same prompt/model/checkpoint, temp 0); accuracy-reusable',
            'dag_actual_cells': 'MH large-extraction 100 (FSC), TQ large-extraction 200 (40 tqb + 160 scale_up), TQ new-160 medium reasoning 151',
            'invalid_forever': 'gold-fed old-40 reasoning, 9+4 gold-fallback reasoning answers, FSC gold-conditioned reasoning, live static mixed-model arm',
        },
        'total_new_model_calls': None,
        'total_new_calls_breakdown': {
            'note': 'superseded by expected_calls under the full-fresh policy; minimal-cell plan was 165 (87 MH rsn-M + 40 TQ mono + 38 TQ rsn-M)',
            'minimal_cell_plan': dict(mh_reasoning_medium=len(mh_rerun_rsn),
                                      tq_mono_large=40, tq_reasoning_medium=len(tq_old_rerun_rsn)),
        },
        'paired_n': dict(MultiHiertt=100, TAT_QA=200, overall=300),
        'analysis': {
            'paired_delta': 'Delta_i = I(armA_i correct) - I(armB_i correct); mean + paired bootstrap 95% CI (10k resamples, seed 20260916)',
            'mcnemar': 'exact McNemar on b / c per arm pair',
            'table_A': 'Mono-L vs DAG-L/L (pure decomposition), per dataset + overall',
            'table_B': 'DAG-L/L vs DAG-L/M (heterogeneous allocation), per dataset + overall',
            'complexity_stratification': 'n_ops buckets 1-2 / 3 / 4+, computed on Table-A pair (Mono-L vs DAG-L/L) ONLY',
            'cost_metrics': 'tokens and per-call latency_s per arm from the single fresh session',
        },
    }

    # ---------- per-task complexity plan (no model calls) ----------
    complexity = {}
    for t in mh:
        n = mh_n_ops(t['program'])
        complexity[t['uid']] = dict(dataset='MultiHiertt', n_ops=n, bucket=bucket(n))
    for t in tq_old + tq_new:
        n = tq_n_ops(t['derivation'])
        complexity[t['uid']] = dict(dataset='TAT-QA', n_ops=n, bucket=bucket(n))
    audit['complexity_stratification_plan'] = {
        'rule': 'count arithmetic ops: TAT-QA derivation binary operators; MultiHiertt program function calls (add/sub/mul/div)',
        'MultiHiertt': {b: sum(1 for u in mh_uids if complexity[u]['bucket'] == b) for b in ['1-2', '3', '4+']},
        'TAT-QA': {b: sum(1 for u in tq_uids if complexity[u]['bucket'] == b) for b in ['1-2', '3', '4+']},
        'per_task': complexity,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'DECOMPOSITION_PAIRING_AUDIT.json').write_text(
        json.dumps(audit, indent=1, ensure_ascii=False) + '\n')

    mh_freeze = [dict(task_id=u, dataset='MultiHiertt', split='fresh_holdout_unused_train') for u in mh_uids]
    tq_freeze = [dict(task_id=u, dataset='TAT-QA', split='dev') for u in tq_uids]
    (OUT / 'decomposition_final_multihiertt_100.json').write_text(
        json.dumps(mh_freeze, indent=1, ensure_ascii=False) + '\n')
    (OUT / 'decomposition_final_tatqa_200.json').write_text(
        json.dumps(tq_freeze, indent=1, ensure_ascii=False) + '\n')

    print(json.dumps({
        'audit_written': str(OUT / 'DECOMPOSITION_PAIRING_AUDIT.json'),
        'mh_freeze': len(mh_freeze), 'tq_freeze': len(tq_freeze),
        'expected_calls': audit['rerun_plan']['expected_calls'],
        'mh_ext_unparseable': len(mh_ext_unparseable),
        'tq_old_ext_unparseable': len(tq_old_ext_unparseable),
        'tq_new_fallback': len(tq_new_fallback),
        'complexity_MH': audit['complexity_stratification_plan']['MultiHiertt'],
        'complexity_TQ': audit['complexity_stratification_plan']['TAT-QA'],
    }, indent=1))


if __name__ == '__main__':
    main()
