#!/usr/bin/env python3
"""B4: GLM-4-flash atomic (one-candidate-per-call) calibration on the 5 unresolved groups.

Frozen GO rule (from E4_1_EVALUATION_AMENDMENT_002.json):
  parse_completeness >= 0.95 AND no missing labels AND
  agreement not worse than Amendment-003 (pairwise within-one >= 0.80, mae <= 0.75) vs qwen-max on common scores.
On PASS -> SECONDARY_READY. On FAIL -> ENGINEERING_UNAVAILABLE (do not retry).

Only granularity changes (one candidate per call); rubric, 0-4 scale, temperature 0,
and prompt semantics are identical to run_c9_multi_judge_feasibility.prompt_for.
"""
import asyncio, json, hashlib, string, random
from pathlib import Path
from phase_e4_1.judge_format_normalization import parse_scores

ROOT = Path('/root'); OUT = ROOT / 'phase_e4_1'
EVENTS = OUT / 'B4_GLM_ATOMIC_CALIBRATION_EVENTS.jsonl'
RESULT = OUT / 'B4_GLM_ATOMIC_CALIBRATION_RESULT.json'

# Reuse frozen definitions (LLMBackend, OpenClawConfig, extract_message_text, read_jsonl, groups, prompt_for, SEED, TIMEOUT, DATA, PROJECT).
source = (ROOT / 'run_c9_multi_judge_feasibility.py').read_text()
ns = {'__name__': 'b4_definitions'}
exec(compile(source.replace('asyncio.run(main())', ''), '<frozen definitions>', 'exec'), ns)
groups = ns['groups']; read_jsonl = ns['read_jsonl']; SEED = ns['SEED']
LLMBackend = ns['LLMBackend']; OpenClawConfig = ns['OpenClawConfig']
extract_message_text = ns['extract_message_text']; DATA = ns['DATA']; PROJECT = ns['PROJECT']
JUDGE = 'glm-4-flash'; TIMEOUT = 90

# The 5 unresolved groups (success=false in JUDGE_FORMAT_RECOVERY_EVENTS.jsonl).
recovery = read_jsonl(OUT / 'JUDGE_FORMAT_RECOVERY_EVENTS.jsonl')
failed_gids = [r['group_id'] for r in recovery if not r['success']]
assert len(failed_gids) == 5, f'expected 5 failed groups, got {len(failed_gids)}'

# qwen-max base scores for the agreement gate.
qwen_base = {(r['group_id'], r['judge_model']): r for r in read_jsonl(DATA / 'C9_2_MULTI_JUDGE_CALIBRATION_BASE_EVENTS.jsonl')}


def atomic_prompt_for(key, candidate_model):
    """Single-candidate prompt: same preamble/rubric/schema as prompt_for, only one 'Answer A:' shown."""
    tid, repeat = key
    answers = sorted([a for a in groups[key] if a['model'] == candidate_model], key=lambda r: r['model'])
    assert answers, f'no answer for {key} {candidate_model}'
    ans = answers[0]
    label = 'A'
    digest = hashlib.sha256(f'{SEED}|primary|{tid}|{repeat}'.encode()).hexdigest()
    # NOTE: order permutation is keyed identically to prompt_for; with one candidate it is the identity.
    mapping = {label: ans['model']}
    task = ns['tasks'][tid]
    reference = str(task.get('reference_answer') or '').strip()
    refpart = f'\nReference answer:\n{reference}' if reference else '\nNo reference answer is available. Judge only whether each answer is correct and supported by the supplied context/table.'
    displayed = f'Answer {label}:\n{ans.get("answer", "")}'
    prompt = f'''You are an independent evaluator. Score every blinded candidate answer independently; do not rank candidates or infer model identity. Use only the question, supplied context/table, and reference answer when present.
Rubric: 4=fully correct and supported; 3=mostly correct with only minor omission; 2=partly correct with a material omission or local error; 1=little correct content and main conclusion wrong; 0=incorrect, irrelevant, unsupported, or no valid answer.
Return only JSON exactly shaped as {{"scores":[{{"label":"A","score":4,"reason":"brief reason"}}]}}. Include every supplied label exactly once; score must be an integer 0..4.
Question:
{task.get("question", "")}
Context:
{task.get("context", "")}
Table:
{json.dumps(task.get("table") or [], ensure_ascii=False)}{refpart}

{displayed}'''
    return mapping, prompt, hashlib.sha256(prompt.encode()).hexdigest()


async def call_atomic(backend, key, candidate_model):
    mapping, prompt, prompt_sha = atomic_prompt_for(key, candidate_model)
    gid = f'{key[0]}:{key[1]}'
    row = {'group_id': gid, 'candidate_model': candidate_model, 'judge_model': JUDGE,
           'formal_label': False, 'success': False, 'prompt_sha256': prompt_sha}
    try:
        response = await asyncio.wait_for(
            backend.call(JUDGE, [{'role': 'user', 'content': prompt}], max_tokens=1500, temperature=0, stream=False),
            timeout=TIMEOUT)
        row['raw_response'] = response
        scores = parse_scores(extract_message_text(response), sorted(mapping))
        row.update(success=True, scores_by_model={mapping[k]: v for k, v in scores.items()})
    except Exception as exc:
        row['error_type'] = type(exc).__name__
    return row


async def main():
    backend = LLMBackend(OpenClawConfig.from_yaml(str(PROJECT / 'configs/openclaw_multi_provider.yaml')))
    done = {(r['group_id'], r['candidate_model']): r for r in read_jsonl(EVENTS)} if EVENTS.exists() else {}
    for gid in failed_gids:
        tid, rep = gid.rsplit(':', 1)
        key = (tid, int(rep))
        if key not in groups:
            print(json.dumps({'skipped': gid, 'reason': 'no candidate answers in groups dict'}), flush=True)
            continue
        candidate_models = sorted({a['model'] for a in groups[key]})
        for cm in candidate_models:
            if (gid, cm) in done:
                continue
            row = await call_atomic(backend, key, cm)
            with EVENTS.open('a', encoding='utf-8') as h:
                h.write(json.dumps(row, ensure_ascii=False) + '\n'); h.flush()
            done[(gid, cm)] = row
            print(json.dumps({k: v for k, v in row.items() if k not in ('raw_response', 'scores_by_model')}, ensure_ascii=False), flush=True)

    # Aggregate + apply frozen gate.
    total = len(done)
    success = sum(1 for r in done.values() if r.get('success'))
    parse_completeness = success / total if total else 0.0
    missing = total - success
    common = []  # (qwen_score, glm_score)
    for (gid, cm), r in done.items():
        if not r.get('success'):
            continue
        qrow = qwen_base.get((gid, 'qwen-max'))
        if not qrow or not qrow.get('success'):
            continue
        qs = qrow.get('scores_by_model', {})
        gs = r.get('scores_by_model', {})
        if cm in qs and cm in gs:
            common.append((int(qs[cm]), int(gs[cm])))
    within_one = sum(1 for q, g in common if abs(q - g) <= 1) / len(common) if common else 0.0
    mae = sum(abs(q - g) for q, g in common) / len(common) if common else 0.0
    exact = sum(1 for q, g in common if q == g) / len(common) if common else 0.0

    gate_pass = (parse_completeness >= 0.95 and missing == 0 and within_one >= 0.80 and mae <= 0.75)
    status = 'SECONDARY_READY' if gate_pass else 'ENGINEERING_UNAVAILABLE'
    result = {
        'status': status,
        'gate': 'parse_completeness>=0.95 AND no_missing AND within_one>=0.80 AND mae<=0.75',
        'atomic_calls_total': total,
        'atomic_calls_success': success,
        'parse_completeness': round(parse_completeness, 4),
        'missing_labels': missing,
        'common_scores_vs_qwen': len(common),
        'within_one_agreement': round(within_one, 4),
        'mean_absolute_disagreement': round(mae, 4),
        'exact_agreement': round(exact, 4),
        'groups_tested': failed_gids,
        'decision': 'GLM is an independent secondary sensitivity judge on a complete label set.' if gate_pass else 'GLM is ENGINEERING_UNAVAILABLE; stop repair, do not retry.',
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


asyncio.run(main())
