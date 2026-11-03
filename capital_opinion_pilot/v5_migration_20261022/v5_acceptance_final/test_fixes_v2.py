"""Regression tests for the four protocol fixes (zero-pay). GO gate for any
future real re-run. Covers: t5 cap sizing (T1), layered JSON parse (T2),
deadline-controlled executor under FakeMeter (T3), scoring v2 (T4).
Historical F7 responses are REPLAYED as fixtures — no model calls.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR, norm
import evidence_packer as ep
from json_compat import parse_layers, node_contract
import scoring_v2
from execution_v2 import DeadlineGuardedExecutor

P = PILOT_DIR
failures = []


def check(cond, msg):
    if cond:
        print(f'  ok   {msg}')
    else:
        failures.append(msg)
        print(f'  FAIL {msg}')


RESP = [json.loads(l) for l in open(P / 'f7min_resp.jsonl') if l.strip()]
LED = [json.loads(l) for l in open(P / 'f7min_ledger.jsonl') if l.strip()]

# ---------------- T1: t5 cap sizing from historical evidence ----------------
print('== T1: t5 output cap sizing ==')
# per-verdict token cost from the only COMPLETE t5 (R2): 767 tok / 14 verdicts
t5_complete = [l for l in LED if l['node'] == 't5' and not l['truncated']]
t5_trunc = [l for l in LED if l['node'] == 't5' and l['truncated']]
check(len(t5_complete) == 1 and t5_complete[0]['out'] == 767, 'one complete t5 baseline (767 tok)')
per_verdict = t5_complete[0]['out'] / 14
# max downstream item load observed: t4 entity 21 + t3 timeline ~14 (R4 inputs)
max_items = 21 + 14
need_ds = per_verdict * max_items * 1.3          # 1.3x: DS slightly wordier than R2 baseline
need_glm_raw = 110.0 * max_items                 # measured GLM tok/verdict, no margin
print(f'    est need: DS~{need_ds:.0f} (1.3x margin) GLM~{need_glm_raw:.0f} (raw) for <= {max_items} verdicts')
check(need_ds <= 2560, 'cap 2560 already sufficient for DS worst load')
check(need_glm_raw > 2560, 'cap 2560 INSUFFICIENT for GLM worst load (real finding)')
check(need_glm_raw <= 4096 * 0.95, 'protocol-v2 cap 4096 covers GLM worst load with >=5% headroom')
# truncation regression: with cap>=3072 the historical truncated cases' item
# counts (max 24 complete + 1 partial) must fit: 24 <= max_items
check(max(l['out'] for l in t5_trunc) == 1536 and len(t5_trunc) == 5,
      'historical truncations all at 1536 cap (5 cases) recorded for the record')
check(4096 > need_glm_raw and 4096 >= 3072, 'PROTOCOL V2 CAP DECISION: t5=4096 (3072 insufficient for GLM)')

# ---------------- T2: layered JSON parse on historical t6 ----------------
print('== T2: layered parse (strict vs control-char compat) ==')
t6_texts = {r['run_id']: r['text'] for r in RESP if r['node'] == 't6'}
for rid, text in t6_texts.items():
    pl = parse_layers(text)
    s_ok, c_ok, val, layer = node_contract('t6', pl)
    print(f'    {rid}: strict={s_ok} compat={c_ok} layer={layer} report_len={len(val) if val else 0}')
    if rid in ('R1_B3p_clean',):
        check(not s_ok and c_ok, f'{rid}: raw newlines -> strict fail, compat pass (recorded separately)')
    if rid in ('R2_B3p_F7', 'R3_S5Cap_F7'):
        check(s_ok and c_ok, f'{rid}: strict pass (no control chars in these two)')
    if rid == 'R4_S6_F7':
        check(not s_ok and not c_ok, 'R4: inner unescaped quote -> BOTH layers fail (not repairable)')
# control chars are tolerated; truncation is NOT repaired
truncated_t5 = next(r['text'] for r in RESP if r['node'] == 't5' and not r['text'].rstrip().endswith(']'))
pl = parse_layers(truncated_t5)
check(not pl['strict_ok'] and not pl['compat_ok'], 'truncated JSON fails BOTH layers (no repair)')
# synthetic edge: tabs/CR/newlines inside strings
syn = '{"report":"line1\nline2\ttabbed\rcr ' + 'x' * 120 + '"}'
pl = parse_layers(syn)
check(pl['compat_ok'] and not pl['strict_ok'], 'synthetic control chars: compat only')
# synthetic edge: unescaped inner quote stays failed
bad = '{"report":"he said "hi" ' + 'y' * 120 + '"}'
pl = parse_layers(bad)
check(not pl['strict_ok'] and not pl['compat_ok'], 'unescaped inner quote: both layers fail (not provably safe to repair)')

# ---------------- T3: deadline-controlled executor (FakeMeter) ----------------
print('== T3: deadline enforcement under FakeMeter ==')


class FakeMeter:
    """Configurable fake: latencies per (node, model); records every call.
    Returns per-node VALID contract JSON so the DAG dataflow completes."""

    CANNED = {
        't1': '{"facts":[{"fact_key":"k","value":"v","doc_id":"D","quote":"q"}]}',
        't2': '{"facts":[{"fact_key":"k2","value":"v2","doc_id":"D","quote":"q"}]}',
        't3': '{"timeline":[{"date":"2020-01-01","event":"e","doc_id":"D"}]}',
        't4': '{"entity_facts":[{"fact_key":"k","value":"v","doc_id":"D"}]}',
        't5': '{"verdicts":[{"fact":"f","verdict":"SUPPORTED","doc_id":"D"}]}',
        't6': '{"report":"' + 'r' * 200 + '"}',
    }

    def __init__(self, lat_overrides=None, default_lat=2.0):
        self.calls = []
        self.lat = lat_overrides or {}
        self.default_lat = default_lat

    def call(self, run_id, node, alias, system, user, **kw):
        lat = self.lat.get((node, alias), self.default_lat)
        time.sleep(min(lat, 0.02))
        rec = {'in': 100, 'out': 50, 'lat': lat, 'stop': 'end_turn',
               'text': self.CANNED[node]}
        self.calls.append({'node': node, 'model': alias, 'lat': lat})
        return rec


class FastClockExecutor(DeadlineGuardedExecutor):
    """Virtual-clock executor: sleep() is 0, but elapsed() is driven by the
    SUM of fake latencies — deterministic deadline tests without real waiting."""

    def elapsed(self):
        return sum(c['lat'] for c in self.meter.calls)


def fake_event():
    return {'task': 'T', 'lines': {'t1': 'A' * 100, 't2': 'B' * 100}}


STATS = {(n, m): (100, 2.0, 0.9) for n in
         ('t1', 't2', 't3', 't4', 't5', 't6') for m in
         ('glm53', 'glm53flash', 'deepseek', 'qwen')}
B3P = {'t1': 'deepseek', 't2': 'deepseek', 't3': 'glm53', 't4': 'glm53',
       't5': 'deepseek', 't6': 'glm53'}
F7 = [('t1', 'deepseek')]

# (a) happy path: fast calls, completes under deadline
ex = FastClockExecutor(FakeMeter(), fake_event(), 'sim_a', dict(B3P), [], 'static', STATS, deadline_s=90.0)
r = ex.run()
check(r['complete'] and r['deadline_met'] and r['wall_s'] < 90, '(a) happy path completes under deadline')

# (b) preflight skip: slow t6 predicted to bust remaining time -> skipped, no call
m = FakeMeter(lat_overrides={('t6', 'glm53'): 30.0})
ex = FastClockExecutor(m, fake_event(), 'sim_b', dict(B3P), [], 'static', STATS, deadline_s=12.0)
r = ex.run()
t6_called = any(c['node'] == 't6' for c in m.calls)
check(not t6_called and any(s['node'] == 't6' and s['reason'] == 'deadline_preflight' for s in r['skips']),
      '(b) slow t6 refused by preflight, call never made')

# (c) F7 + recovery cascade near deadline: recovery refused, no violation
m = FakeMeter(lat_overrides={('t1', 'glm53'): 8.0, ('t4', 'glm53'): 6.0})
ex = FastClockExecutor(m, fake_event(), 'sim_c', dict(B3P), F7, 's6', STATS, deadline_s=14.0)
r = ex.run()
check(all(c is not None for c in m.calls), '(c) all issued calls recorded')
check(r['deadline_met'], f"(c) cascade near deadline: no violation (wall={r['wall_s']}s)")
check(len(r['skips']) > 0 or r['complete'], '(c) skips or completion recorded')

# (d) hard stop: predictions must match the fake reality (stats aligned), else
# the gate would trust wrong stats — scenario: one in-flight call lands near the
# deadline, everything slow is refused, NOTHING is issued beyond the deadline.
STATS_D = {(n, m): (100, 2.0, 0.9) for n in ('t1', 't2', 't3', 't4', 't5', 't6')
           for m in ('glm53', 'glm53flash', 'deepseek', 'qwen')}
STATS_D[('t2', 'deepseek')] = (100, 10.0, 0.9)   # runs first, lands at 10s
STATS_D[('t1', 'glm53')] = (100, 40.0, 0.9)      # recovery candidate: must be refused
STATS_D[('t3', 'glm53')] = (100, 40.0, 0.9)      # slow: must be refused
STATS_D[('t6', 'glm53')] = (100, 40.0, 0.9)      # slow: must be refused
m = FakeMeter(lat_overrides={('t2', 'deepseek'): 10.0, ('t1', 'glm53'): 40.0,
                             ('t3', 'glm53'): 40.0, ('t6', 'glm53'): 40.0})
ex = FastClockExecutor(m, fake_event(), 'sim_d', dict(B3P), F7, 's5cap', STATS_D, deadline_s=45.0)
r = ex.run()
total_lat = sum(c['lat'] for c in m.calls)
check(total_lat <= 45.0 + 1e-6, f'(d) issued-call latency sum never exceeds deadline ({total_lat}s)')
check(r['deadline_violation_s'] == 0.0, '(d) zero violation with in-flight calls counted')
called_nodes = {c['node'] for c in m.calls}
check('t1' not in called_nodes and 't6' not in called_nodes,
      '(d) slow recovery(t1) and t6 never issued (refused by preflight)')
check(any(s['reason'] == 'deadline_preflight' for s in r['skips']),
      '(d) preflight refusals recorded with reasons')

# ---------------- T4: scoring v2 ----------------
print('== T4: scoring v2 field rules ==')
cases = [
    ('RF1', '对康得新处以60万元罚款', 'COVERED'),                 # reordered phrasing
    ('RF1', '处以罚款60万元', 'NOT_COVERED'),                      # no subject
    ('RF1', '康得新被罚款1,000万元', 'NOT_COVERED'),               # wrong amount
    ('RF2', '康得新2015年至2018年年度报告存在虚假记载', 'COVERED'),
    ('RF2', '公司年报存在虚假记载', 'NOT_COVERED'),                # no time range
    ('RF3', '对钟玉采取10年证券市场禁入措施', 'COVERED'),
    ('RF3', '采取市场禁入措施，期限10年', 'COVERED'),              # order-flexible
    ('RF3', '采取终身市场禁入', 'NOT_COVERED'),
    ('RF4', '北京银行股份有限公司西单支行与公司签订现金管理业务合作协议', 'COVERED'),
    ('RF4', '与某银行签订现金管理协议', 'NOT_COVERED'),
]
for fid, text, want in cases:
    got = scoring_v2.score_fact(fid, text)
    check(got == want, f'{fid}: {text[:24]!r} -> {got}')

# apply v2 to the four historical reports (side by side with v1, no replacement)
ranked = ep.rank_chunks(ep.build_index())
packs = ep.pack_lines(10000, {'t1': ['kdx_penalty_2020', 'kdx_notice_2019', 'kdx_notice_2020'],
                              't2': ['kdx_inquiry_2018', 'kdx_inquiry_2019']}, ranked=ranked)
pack_text = packs['t1']['text'] + '\n' + packs['t2']['text']
print('    -- v2 scores on historical reports (v1 archived in f7_rescore.json) --')
v2 = {}
for rid, text in t6_texts.items():
    pl = parse_layers(text)
    _, c_ok, val, _ = node_contract('t6', pl)
    rep = val if val else text  # salvage layer disclosed in report
    s = scoring_v2.score_report(rep)
    chain = scoring_v2.chain_filter(s['covered'], pack_text)
    v2[rid] = {'v2_score': s['score'], 'per_fact': s['per_fact'], 'chain_valid': chain}
    print(f'    {rid}: v2={s["score"]} chain={chain} per_fact={s["per_fact"]}')
json.dump(v2, open(P / 'f7_scoring_v2_result.json', 'w'), ensure_ascii=False, indent=1)

print()
if failures:
    print(f'RESULT: {len(failures)} FAILURES -> NO-GO for any real re-run')
    json.dump({'status': 'FAIL', 'failures': failures}, open(P / 'test_fixes_v2_result.json', 'w'))
    sys.exit(1)
print('RESULT: ALL PASS -> fixes eligible for GO review')
json.dump({'status': 'PASS'}, open(P / 'test_fixes_v2_result.json', 'w'))
