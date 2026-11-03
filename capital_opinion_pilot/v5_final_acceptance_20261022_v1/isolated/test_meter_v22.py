"""V2.2 zero-call audit tests: dedup, failed-entry recovery, conservative reservation,
crash recovery, ledger-only aggregation. All use FakeMeter transports (no HTTP)."""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, '/root/capital_opinion_pilot/v5_final_acceptance_20261022_v1/isolated')
from pilot_common import PILOT_DIR, Meter, BudgetExceeded  # noqa: E402

TMP = PILOT_DIR / 'v22_test_tmp'
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir()
ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    ok += bool(cond)
    fail += (not cond)
    print(f"{'PASS' if cond else 'FAIL'} {name} {detail}")


class FakeMeter(Meter):
    def __init__(self, texts=None, **kw):
        super().__init__(ledger_path=TMP / kw.pop('ledger_name', 'l1.jsonl'), **kw)
        self.texts = texts or ['{"ok": 1}']
        self.n_transport = 0

    def _transport(self, alias, system, user, max_tokens, timeout_s):
        self.n_transport += 1
        return {'usage': {'input_tokens': 100, 'output_tokens': 50},
                'text': self.texts[min(self.n_transport - 1, len(self.texts) - 1)],
                'latency_s': 0.01, 'stop_reason': 'end_turn'}


# T1 dedup: identical (purpose, prompt) never re-pays
m = FakeMeter(max_calls=10, max_guaranteed_actual=10000)
r1, t1 = m.call('glm53', 's', 'p1', max_tokens=100, purpose='T1')
r2, t2 = m.call('glm53', 's', 'p1', max_tokens=100, purpose='T1')
check('T1 dedup same purpose+prompt', m.n_transport == 1 and r1['call_id'] == r2['call_id'] and t1 == t2)
r3, _ = m.call('glm53', 's', 'p1-different', max_tokens=100, purpose='T1:rep2')
check('T1 deliberate repeat via distinct purpose allowed', m.n_transport == 2 and r3['call_id'] == 2)

# T2 failed-entry dedup: a parse-failed persisted attempt is returned, not re-paid
m2 = FakeMeter(texts=['not json at all'], max_calls=10, max_guaranteed_actual=10000, ledger_name='l2.jsonl')
ra, ta = m2.call('glm53', 's', 'p', max_tokens=100, purpose='T2')
m2b = FakeMeter(texts=['not json at all'], max_calls=10, max_guaranteed_actual=10000, ledger_name='l2.jsonl')
rb, tb = m2b.call('glm53', 's', 'p', max_tokens=100, purpose='T2')
check('T2 crash-rerun does not re-pay failed entry', m2b.n_transport == 0 and ra['call_id'] == rb['call_id'] and tb == ta)

# T3 conservative reservation rejects BEFORE transport (1.5x factor)
m3 = FakeMeter(max_calls=10, max_guaranteed_actual=1000)
m3.call('glm53', 's', 'a', max_tokens=400, purpose='T3a')          # reserve 600; actual 150
m3.call('glm53', 's', 'b', max_tokens=100, purpose='T3b')          # actual 300, reserve 150 -> ok
try:
    m3.call('glm53', 's', 'c', max_tokens=400, purpose='T3c')      # actual 300 + reserve 600 > 1000
    check('T3 conservative reserve rejects pre-transport', False, 'no exception')
except BudgetExceeded as e:
    check('T3 conservative reserve rejects pre-transport', m3.n_transport == 2, str(e)[:70])

# T4 crash recovery: fresh process instance reuses persisted call + response text
m4 = FakeMeter(max_calls=10, max_guaranteed_actual=10000, ledger_name='l4.jsonl')
r4, t4 = m4.call('glm53', 's', 'prompt-x', max_tokens=100, purpose='T4')
m4b = FakeMeter(max_calls=10, max_guaranteed_actual=10000, ledger_name='l4.jsonl')
r4b, t4b = m4b.call('glm53', 's', 'prompt-x', max_tokens=100, purpose='T4')
resp_file = TMP / 'l4_responses.jsonl'
check('T4 recovery: no new call + full text recovered',
      m4b.n_transport == 0 and t4b == '{"ok": 1}' and resp_file.exists())

# T5 ledger-only aggregation reproduces V2.1 official numbers without any transport
from budget_audit import audit
a = audit(PILOT_DIR / 'model_call_ledger_v21.jsonl')
check('T5 ledger aggregation matches V2.1 report', a['n_calls'] == 10 and a['settled_actual'] == 19084,
      f"n={a['n_calls']} actual={a['settled_actual']}")

# T6 response persistence completes before return (write-through check)
raw = (TMP / 'l4_responses.jsonl').read_text()
check('T6 responses file write-through', '"text"' in raw and '"stop_reason"' in raw)

print(f'\nV2.2 ZERO-CALL AUDIT (pre-T8): {ok} passed, {fail} failed')

# T8 (added after V3-repair overage): input-size-aware reserve rejects big-prompt calls
m8 = FakeMeter(max_calls=5, max_guaranteed_actual=2000, ledger_name='l8.jsonl')
big_prompt = 'x' * 3000  # ~2700 input reserve alone exceeds cap
try:
    m8.call('glm53', 's', big_prompt, max_tokens=100, purpose='T8')
    check8 = False
except BudgetExceeded:
    check8 = m8.n_transport == 0
print(('PASS' if check8 else 'FAIL'), 'T8 input-aware reserve rejects pre-transport')
sys.exit(0 if (fail == 0 and check8) else 1)
