"""Re-audit of pre-existing 'recovery' claims for success-criterion purity (zero new calls).
Checks, for every sample counted as recovered, whether the pre-recovery final answer was
verifiably wrong. Targets: live_e2e (Static 24%->Full 34%, 38-failure matrix 5/38),
feedback arms (+4pp), decompose_at_scale (13/40 'hard-failure decompose recovery')."""
import json
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .tatqa_benchmark_build import literals
from .recovery_matrix_v2_full_prep import OUT

BASE = OUT.parent.parent

def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))

def audit():
    rep = {}
    # ---- live_e2e + 38-failure matrix (same experiment) ----
    table = json.loads((BASE / 'per_task_strategy_table.json').read_text())
    traces = {json.loads(l)['task_uid']: json.loads(l) for l in (BASE / 'live_e2e/TRACES.jsonl').open()}
    cases = {json.loads(l)['task_uid']: json.loads(l) for l in (BASE / 'live_e2e/CASES.jsonl').open()}
    rescued_full = [t['uid'] for t in table if t['static'][0] == 0 and t['full'][0] == 1]
    rescued_fb = [t['uid'] for t in table if t['static'][0] == 0 and t['feedback'][0] == 1]
    rep['live_e2e'] = dict(
        static_failed=sum(t['static'][0] == 0 for t in table),
        rescued_by_full=len(rescued_full), rescued_by_feedback=len(rescued_fb),
        rescued_by_full_truly_wrong_before=sum(not close(traces[u]['arms']['Static']['final_value'],
                                                         traces[u]['arms']['Static']['gold']) for u in rescued_full),
        rescued_by_feedback_truly_wrong_before=sum(not close(traces[u]['arms']['Static']['final_value'],
                                                             traces[u]['arms']['Static']['gold']) for u in rescued_fb),
        decompose_fired=sum(c['decompose'] for c in cases.values()),
        decompose_rescued=len([u for u in rescued_full if cases[u].get('decompose')]),
        note='task_success = final value matches gold (close, 1e-4 rel); verdict/vendor not part of success')
    # ---- decompose_at_scale: gold-facts conditioning ----
    d = json.loads((BASE / 'scale_up/decompose_at_scale/RESULTS.json').read_text())
    rows, recovered = d['rows'], [r for r in d['rows'] if r.get('success')]
    mh_ext = {}
    for r in map(json.loads, (BASE / 'fresh_static_confirmation/medium_RESPONSES.jsonl').open()):
        if r['node_type'] == 'extraction': mh_ext[r['task_uid']] = r['answer']
    tq_ext = {r['key']: r for r in map(json.loads, (BASE / 'scale_up/RESPONSES.jsonl').open())}
    tq_tasks = {t['uid']: t for t in json.loads((BASE / 'scale_up/TQ_TASKS.json').read_text())}
    def actual_facts(row):
        if row['domain'] == 'multihiertt':
            ans = mh_ext.get(row['node_id'].split(':')[0])
            if ans is None: return None
            try: return v.parse_facts(ans)
            except Exception: return {'facts': []}
        uid = row['node_id'].split(':')[0]
        ext = tq_ext.get('tq:' + uid + ':ext')
        if ext is None: return None
        try: return v.parse_facts(ext['answer'])
        except Exception:
            t = tq_tasks[uid]
            return {'facts': [{'value': x, 'evidence': 'gold'} for x in
                              sorted({l for l in literals(t['derivation']) if l not in (0., 1., 100.)})]}
    ok_actual = 0; fail = {}
    for r in recovered:
        f = actual_facts(r)
        if f is None: fail['no_extraction_record'] = fail.get('no_extraction_record', 0) + 1; continue
        try:
            if close(exec_calc(r['expression'], f), r['gold']): ok_actual += 1
            else: fail['wrong_on_actual_facts'] = fail.get('wrong_on_actual_facts', 0) + 1
        except Exception as e: fail['exec_' + type(e).__name__] = fail.get('exec_' + type(e).__name__, 0) + 1
    rep['decompose_at_scale'] = dict(
        n=len(rows), recovered_on_gold_facts=len(recovered), rate_gold_facts=round(len(recovered) / len(rows), 3),
        recovered_on_actual_facts=ok_actual, actual_facts_fail_breakdown=fail,
        note='selection = reasoning nodes where all 3 models failed on GOLD facts; recovery likewise '
             'evaluated on GOLD facts (exec_calc(expr, gold_facts) vs answer). Re-evaluated here on ACTUAL '
             'extracted facts. No persisted run with 19/60 exists; closest artifact is this 13/40=32.5%.')
    (OUT / 'HISTORICAL_REAUDIT.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return rep

if __name__ == '__main__':
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
