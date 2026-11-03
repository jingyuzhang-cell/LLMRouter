"""Task-1 gate: three INDEPENDENT regression tests, one per historical overage
mechanism, plus calibration sanity. Zero model calls (FakeMeter transports).

Incident 1 (V1): output overshoot-style settle above cap      -> post-settle sentinel
Incident 2 (V2.1): crash-rerun re-paying failed entries       -> dedup (re-verified)
Incident 3 (V3-repair): input growth under output-only reserve-> calibrated input bound
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, '/root/capital_opinion_pilot/v5_migration_20261022/v5_regression')
from pilot_common import PILOT_DIR, Meter, BudgetExceeded  # noqa: E402
import budget_guard  # noqa: E402

TMP = PILOT_DIR / 'guard_test_tmp'
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir()
ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    ok += bool(cond)
    fail += (not cond)
    print(f"{'PASS' if cond else 'FAIL'} {name} {detail}")


# C0 calibration sanity on real ledgers
cal = budget_guard.calibrate()
check('C0 calibration uses real data', cal['n_calls'] >= 30 and cal['guard_ratio'] > cal['ratio_max'],
      json.dumps({k: cal[k] for k in ('n_calls', 'ratio_max', 'guard_ratio')}))


class FakeMeter(Meter):
    def __init__(self, usage=None, **kw):
        super().__init__(ledger_path=TMP / kw.pop('ledger_name', 'g.jsonl'), **kw)
        self.usage = usage or {'input_tokens': 100, 'output_tokens': 50}
        self.n_transport = 0

    def _transport(self, alias, system, user, max_tokens, timeout_s):
        self.n_transport += 1
        return {'usage': dict(self.usage), 'text': '{"ok":1}', 'latency_s': 0.01,
                'stop_reason': 'end_turn'}


# I1: settle far ABOVE the calibrated estimate (overshoot-style, incident-V1 mechanism)
# must be flagged in the ledger entry itself by the post-settle sentinel
m1 = FakeMeter(max_calls=5, max_guaranteed_actual=250, ledger_name="g1.jsonl")
m1.call('glm53', 's', 'a', max_tokens=60, purpose='I1')                       # settles 150 <= 250
m1.usage = {'input_tokens': 500, 'output_tokens': 50}                         # settle >> estimate
rec2, _ = m1.call('glm53', 's', 'b', max_tokens=60, purpose='I1b')            # pre-check passes; settles 700 > 250
check('I1 post-settle overrun flagged', rec2.get('overrun_flag') is True
      and m1.actual_tokens == 700, f'actual={m1.actual_tokens}')

# I2: crash-rerun never re-pays (failed or succeeded)
m2 = FakeMeter(max_calls=5, max_guaranteed_actual=10000, ledger_name='g2.jsonl')
m2.call('glm53', 's', 'p', max_tokens=100, purpose='I2')
m2b = FakeMeter(max_calls=5, max_guaranteed_actual=10000, ledger_name='g2.jsonl')
m2b.call('glm53', 's', 'p', max_tokens=100, purpose='I2')
check('I2 crash-rerun zero re-pay', m2b.n_transport == 0)

# I3: calibrated input bound rejects a big-prompt call pre-transport
m3 = FakeMeter(max_calls=5, max_guaranteed_actual=1200, ledger_name='g3.jsonl')
big = '字' * 2000   # calibrated ratio ~0.6-0.8 => est >= 1200 alone
try:
    m3.call('glm53', 's', big, max_tokens=100, purpose='I3')
    check('I3 calibrated input bound rejects pre-transport', False, 'no exception')
except BudgetExceeded:
    check('I3 calibrated input bound rejects pre-transport', m3.n_transport == 0)

# I4: guard ratio actually used by Meter (not the old 0.9 constant): craft a prompt
# whose 0.9-estimate would pass but calibrated estimate must reject when ratio>0.9? —
# instead verify estimate function matches calibration
est = budget_guard.estimate_input_tokens('s', 'u' * 1000)
check('I4 estimate consistent with calibrated ratio',
      est == int(1001 * budget_guard.GUARD_RATIO), f'est={est} ratio={budget_guard.GUARD_RATIO}')

print(f'\nBUDGET-GUARD AUDIT TESTS: {ok} passed, {fail} failed')
sys.exit(1 if fail else 0)
