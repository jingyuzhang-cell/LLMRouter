"""Part-1 gate: zero-call tests for the generic facts_merge contract.
Old-protocol regression + type legality + real multi-input + dead branch + cycle
+ crash recovery + merge-program semantics. ALL must pass before any model call."""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, '/root/capital_opinion_pilot/v5_migration_20261022/v5_acceptance_final')
import semantic_plan as SP
import assemble_dag as AD
import pilot_dag_contracts as C
from collab_scheduler_v1.typed_dag_v1 import protocol as td
from merge_facts import merge_facts, merge_stats

TMP = Path('/root/capital_opinion_pilot/v5_migration_20261022/v5_acceptance_final/v3_repair_test_tmp')
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir()
ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    ok += bool(cond)
    fail += (not cond)
    print(f"{'PASS' if cond else 'FAIL'} {name} {detail}")


KDX = ['kdx_inquiry_2018', 'kdx_notice_2019', 'kdx_notice_2020', 'kdx_penalty_2020', 'kdx_inquiry_2019']
BASE = [
    {'id': 'i1', 'kind': 'index', 'goal': '索引', 'doc_ids': [], 'depends': []},
    {'id': 'e1', 'kind': 'extracts_f', 'goal': '监管线', 'doc_ids': ['kdx_penalty_2020'], 'depends': ['i1']},
    {'id': 'e2', 'kind': 'extracts_f', 'goal': '问询线', 'doc_ids': ['kdx_inquiry_2018'], 'depends': ['i1']},
    {'id': 'm1', 'kind': 'facts_merge', 'goal': '多源汇合', 'doc_ids': [], 'depends': ['e1', 'e2']},
    {'id': 'tl', 'kind': 'timeline', 'goal': '时间线', 'doc_ids': [], 'depends': ['m1']},
    {'id': 'ck', 'kind': 'factcheck_tl', 'goal': '核查', 'doc_ids': [], 'depends': ['m1', 'tl']},
    {'id': 'rp', 'kind': 'report', 'goal': '报告', 'doc_ids': [], 'depends': ['ck']}]

# T1 real multi-input: dual extracts_f -> facts_merge -> downstream; validator PASS
plan = {'plan': BASE}
iss = SP.validate_plan(plan, KDX)
gv, iss2 = AD.assemble(plan)
check('T1 dual-line merge assembles+validates', gv is not None,
      f'plan={iss[:2]} asm={iss2}' if gv is None else f'layers={[list(l) for l in gv[1].layers]}')

# T2 type legality: json-typed source (plain extracts) must NOT feed facts_merge
plan_bad = {'plan': [dict(t) for t in BASE] + [{'id': 'e3', 'kind': 'extracts', 'goal': '普通线',
          'doc_ids': ['kdx_notice_2020'], 'depends': ['i1']}]}
plan_bad['plan'][3]['depends'] = ['e1', 'e3']   # facts_merge now fed by kind 'extracts'
iss = SP.validate_plan(plan_bad, KDX)
gv2, iss2b = AD.assemble(plan_bad)
check('T2 json-typed source rejected for facts_merge', bool(iss) or gv2 is None, f'issues={iss[:2]}/{str(iss2b)[:60]}')

# T3 dead-branch detection still fires (unconsumed check node)
plan_dead = {'plan': BASE + [{'id': 'ck2', 'kind': 'factcheck_tl', 'goal': '孤儿核查',
                              'doc_ids': [], 'depends': ['m1', 'tl']}]}
gv3, iss3 = AD.assemble(plan_dead)
check('T3 dead branch rejected', gv3 is None, str(iss3)[:60])

# T4 cycle detection at plan level
plan_cyc = {'plan': [dict(t) for t in BASE]}
plan_cyc['plan'][1]['depends'] = ['m1']  # e1 <- m1 <- e1
check('T4 cycle detected', bool(SP.validate_plan(plan_cyc, KDX)))

# T5 old-protocol regression: legacy Shuntian V2 graph + KDX v3 graph still validate
DAGS = ['initial_dag_v2.json', 'initial_dag_v3_kdx.json']
for f in DAGS:
    d = json.loads((Path('/root/capital_opinion_pilot/v5_migration_20261022/v5_acceptance_final') / f).read_text())
    g = td.Graph.from_json(json.dumps(d['graph'], ensure_ascii=False))
    try:
        C.td.validate(g, required_outputs=('investigation_report',),
                      limits=C.td.Limits(max_nodes=9, max_depth=6, max_llm_calls=9))
        check(f'T5 legacy validates: {f}', True)
    except Exception as e:
        check(f'T5 legacy validates: {f}', False, str(e)[:60])

# T6 merge semantics: provenance preserved, duplicates merged, conflicts flagged
line1 = [{'fact_key': '立案日期', 'value': '2020-04-07', 'doc_id': 'kdx_penalty_2020'},
         {'fact_key': '罚款', 'value': '60万', 'doc_id': 'kdx_penalty_2020'}]
line2 = [{'fact_key': '立案日期', 'value': '2020-04-08', 'doc_id': 'kdx_inquiry_2018'},   # conflict
         {'fact_key': '罚款', 'value': '60万', 'doc_id': 'kdx_inquiry_2018'},              # duplicate value
         {'fact_key': '存款虚假', 'value': '是', 'doc_id': 'kdx_inquiry_2018'}]
m = merge_facts([line1, line2], ['e1', 'e2'])
st = merge_stats(m)
byk = {x['fact_key']: x for x in m}
check('T6 duplicate merged with multi-origin', len(m) == 4 and byk['罚款'].get('origins') and
      len([o for o in byk['罚款']['origins'] if o['doc_id']]) == 2, json.dumps(st, ensure_ascii=False))
check('T6 conflict flagged on both items, both kept', byk['立案日期'].get('conflict_marker') is True
      and sum(1 for x in m if x['fact_key'] == '立案日期') == 2)
check('T6 provenance present on every item', all(x.get('origins') and x['origins'][0].get('source_node') for x in m))

# T7 crash recovery suites still green (import side-effect free)
import subprocess
r1 = subprocess.run(['python3', 'test_meter_v22.py'], capture_output=True, text=True, cwd='/root/capital_opinion_pilot/v5_migration_20261022/v5_acceptance_final')
r2 = subprocess.run(['python3', 'dry_run_tests.py'], capture_output=True, text=True, cwd='/root/capital_opinion_pilot/v5_migration_20261022/v5_acceptance_final')
check('T7 meter/dry-run suites pass', '0 failed' in r1.stdout and '0 failed' in r2.stdout)

print(f'\nCONTRACT-REPAIR GATE: {ok} passed, {fail} failed')
sys.exit(1 if fail else 0)
