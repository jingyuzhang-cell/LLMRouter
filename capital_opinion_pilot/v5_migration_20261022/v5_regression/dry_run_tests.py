"""Zero-call dry-run tests proving the V2 infrastructure before any authorization.

T1: deterministic assembly accepts two DIFFERENT plan topologies (no template binding)
    and the reused validator passes both; a malformed plan is rejected with issues.
T2: scoring module produces expected coverage/citation/order numbers on synthetic outputs.
T3: FakeMeter (transport-injected) writes ledger+responses immediately; budget guard
    trips at the configured cap; node-result reuse avoids duplicate calls (resume).
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, '/root/capital_opinion_pilot/v5_migration_20261022/v5_regression')
from pilot_common import PILOT_DIR, Meter, BudgetExceeded  # noqa: E402
import semantic_plan as SP  # noqa: E402
import assemble_dag as AD  # noqa: E402
import scoring  # noqa: E402
from execute_v2 import call_node  # noqa: E402
from execute_v2 import NODE_RESULTS  # noqa: E402

TMP = PILOT_DIR / 'dryrun_tmp'
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir()
ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    ok += bool(cond)
    fail += (not cond)
    print(f"{'PASS' if cond else 'FAIL'} {name} {detail}")


# ---------------- T1: assembly ----------------
PLAN_FULL = {'plan': [
    {'id': 't1', 'kind': 'index', 'goal': '整理证据索引与角色分类', 'doc_ids': [], 'depends': []},
    {'id': 't2', 'kind': 'extracts', 'goal': '检索监管与公告关键段落', 'doc_ids': SP.VALID_DOC_IDS, 'depends': ['t1']},
    {'id': 't3', 'kind': 'timeline', 'goal': '重建调查过程时间线', 'doc_ids': [], 'depends': ['t2']},
    {'id': 't4', 'kind': 'entity_facts', 'goal': '抽取主体与处罚事实', 'doc_ids': [], 'depends': ['t2']},
    {'id': 't5', 'kind': 'factcheck_full', 'goal': '交叉核查时间线与事实', 'doc_ids': [], 'depends': ['t2', 't3', 't4']},
    {'id': 't6', 'kind': 'report', 'goal': '撰写带引用的调查报告', 'doc_ids': [], 'depends': ['t5']}]}
PLAN_TL_ONLY = {'plan': [
    {'id': 'a1', 'kind': 'index', 'goal': '整理证据索引', 'doc_ids': [], 'depends': []},
    {'id': 'a2', 'kind': 'extracts', 'goal': '检索关键段落', 'doc_ids': ['csrc_penalty_2024_41'], 'depends': ['a1']},
    {'id': 'a3', 'kind': 'timeline', 'goal': '重建时间线', 'doc_ids': [], 'depends': ['a2']},
    {'id': 'a4', 'kind': 'factcheck_tl', 'goal': '核查时间线', 'doc_ids': [], 'depends': ['a2', 'a3']},
    {'id': 'a5', 'kind': 'report', 'goal': '撰写报告', 'doc_ids': [], 'depends': ['a4']}]}
PLAN_BAD = {'plan': [
    {'id': 'b1', 'kind': 'index', 'goal': '索引', 'doc_ids': [], 'depends': []},
    {'id': 'b2', 'kind': 'extracts', 'goal': '检索', 'doc_ids': ['no_such_doc'], 'depends': ['b1', 'b1x']},
    {'id': 'b3', 'kind': 'report', 'goal': '报告', 'doc_ids': [], 'depends': []}]}

for name, plan, expect_ok in [('full-6node', PLAN_FULL, True), ('tl-only-5node', PLAN_TL_ONLY, True),
                              ('bad-plan', PLAN_BAD, False)]:
    issues = SP.validate_plan(plan)
    (sp_ok := not issues)
    gv = None
    if sp_ok:
        gv, iss = AD.assemble(plan)
        sp_ok = gv is not None and not iss
    check(f'T1 {name} plan+assembly', sp_ok == expect_ok,
          f'issues={issues[:3]}' if issues else f'layers={[list(l) for l in gv[1].layers]}' if gv else '')
gv_full, _ = AD.assemble(PLAN_FULL)
gv_tl, _ = AD.assemble(PLAN_TL_ONLY)
check('T1 topologies differ (not template-bound)',
      [list(l) for l in gv_full[1].layers] != [list(l) for l in gv_tl[1].layers])

# ---------------- T2: scoring ----------------
silver = scoring.load_silver()
edates = scoring.load_evidence_dates()
sample = ('调查报告：公司于2022-11-04收到立案告知书（st_announce_2024_020），2023-06-30收到事先告知书'
          '（st_advance_notice_2023）。2009至2021年共计虚增营业收入10,333,448,392.98元，业务为隋某力主导的'
          '专网通信虚假自循环业务，无商业实质（csrc_penalty_2024_41）。股票于2024-07-08停牌、2024-07-09实施ST，'
          '简称变更为ST舜天，涨跌幅5%（st_announce_2024_021）。无法确认事项：无。')
s = scoring.score_output(sample, silver, edates)
check('T2 coverage=8/8', s['fact_coverage'] == 1.0, f"got {s['fact_coverage']} {s['covered_fact_ids']}")
check('T2 citation accuracy computed', s['citation_accuracy'] is not None and s['citation_accuracy'] >= 0.8,
      f"acc={s['citation_accuracy']}")
tl_bad = [{'date': '2024-07-09', 'e': 'ST实施'}, {'date': '2024-07-08', 'e': '停牌'}]
tl = scoring.score_timeline(tl_bad, silver, edates)
check('T2 timeline order violation detected', tl['order_violations'] == 1 and not tl['order_ok'])
wrong_cite = ('2022-11-04收到立案告知书（st_announce_2024_021）。')
s2 = scoring.score_output(wrong_cite, silver, edates)
check('T2 wrong citation penalized', s2['citation_accuracy'] == 0.0,
      f"acc={s2['citation_accuracy']} per_fact={s2['per_fact_citations']}")

# ---------------- T3: FakeMeter persistence + budget + resume ----------------
class FakeMeter(Meter):
    def __init__(self, **kw):
        super().__init__(ledger_path=TMP / 'ledger.jsonl', **kw)
        self.n_transport = 0

    def _transport(self, alias, system, user, max_tokens, timeout_s):
        self.n_transport += 1
        return {'usage': {'input_tokens': 100, 'output_tokens': 50}, 'text': '{"doc_extracts": []}',
                'latency_s': 0.01, 'stop_reason': 'end_turn'}


import pathlib as _pl
import execute_v2 as _ex
NODE_RESULTS = _pl.Path('/tmp/dryrun_node_results_test.jsonl')  # never touch production files
_ex.NODE_RESULTS = NODE_RESULTS  # call_node writes through this module global
NODE_RESULTS.unlink(missing_ok=True)
NODE_RESULTS.touch()
fm = FakeMeter(max_calls=3, max_guaranteed_actual=2000)
parsed, ent = call_node(fm, 'DRY', 't2', 'extracts', 'glm53', 'prompt-A')
check('T3 node result persisted', NODE_RESULTS.read_text().count('\n') >= 1 and ent['parse_status'] == 'OK')
check('T3 raw response persisted in ledger responses',
      (TMP / 'ledger_responses.jsonl').exists() and 'doc_extracts' in (TMP / 'ledger_responses.jsonl').read_text())
fm2 = FakeMeter(max_calls=3, max_guaranteed_actual=2000)
parsed2, ent2 = call_node(fm2, 'DRY', 't2', 'extracts', 'glm53', 'prompt-A')
check('T3 resume reuses without new call', fm2.n_transport == 0 and ent2.get('reused') is True)
fm3 = FakeMeter(max_calls=3, max_guaranteed_actual=210)
try:
    for i in range(5):
        fm3.call('glm53', 's', f'prompt-{i}', max_tokens=60, purpose='cap-test')
    check('T3 budget guard trips', False, 'never raised')
except BudgetExceeded as e:
    # V2.2 semantics: conservative reserve = 1.5 x max_tokens (90). This FakeMeter shares
    # the ledger with the earlier persistence test (actual=150 already settled), so the
    # very first T3 call is rejected pre-transport: no new spend, actual unchanged.
    check('T3 budget guard trips (conservative 1.5x reserve)', fm3.actual_tokens == 150
          and fm3.n_transport == 0, str(e)[:80])
check('T3 dual accounting recorded',
      'cumulative_settled_actual' in fm3.calls[0] and 'cumulative_conservative' in fm3.calls[0])

NODE_RESULTS.unlink(missing_ok=True)
print(f'\nDRY-RUN RESULT: {ok} passed, {fail} failed (zero real model calls)')
sys.exit(1 if fail else 0)
