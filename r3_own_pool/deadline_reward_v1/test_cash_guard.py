"""test_cash_guard.py — Automated tests for CashGuard pre-call admission."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cash_guard import CashGuard

fails = []
def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg)
    if not cond: fails.append(msg)

print("== T1: Single call within budget ==")
g = CashGuard(cap=0.030)
ok, action = g.admit('verify', 'DS', remaining_after=['sink'], pi={'verify':'DS','sink':'DS'})
check(ok and action[0]=='proceed', f"DS verify admitted: {action}")

print("\n== T2: Single call exceeds budget ==")
g2 = CashGuard(cap=0.005)
ok2, action2 = g2.admit('sink', 'DS', remaining_after=[], pi={'sink':'DS'})
check(not ok2, f"DS sink refused at ¥0.005: {action2}")
check(action2[0] == 'fallback' and action2[2] == 'Flash', f"Falls back to Flash: {action2}")

print("\n== T3: Plan-level check prevents verify consuming all budget ==")
g3 = CashGuard(cap=0.015)
# verify DS costs ~0.0098 worst, sink DS costs ~0.0165 worst
# verify + sink = ~0.0263 > 0.015 → can't afford both as DS
ok3, action3 = g3.admit('verify', 'DS', remaining_after=['sink'], pi={'verify':'DS','sink':'DS'})
check(not ok3, f"DS verify+sink plan rejected: {action3}")
# Should fall back to Flash for verify (free) so sink can use DS
if action3[0] == 'fallback':
    check(action3[2] == 'Flash', f"Verify falls back to Flash: {action3}")

print("\n== T4: Plan check allows mixed π within budget ==")
g4 = CashGuard(cap=0.030)
# n_sup2 Flash(free) + verify DS(0.0098) + sink DS(0.0165) = 0.0263 ≤ 0.030
ok4, action4 = g4.admit('n_sup2', 'Flash', remaining_after=['verify','sink'],
                          pi={'n_sup2':'Flash','verify':'DS','sink':'DS'})
check(ok4 and action4[0]=='proceed', f"Flash sup2 + DS verify/sink admitted: {action4}")

print("\n== T5: Actual cost recording and compliance tracking ==")
g5 = CashGuard(cap=0.030)
g5.record('n_sup2', 'Flash', 0.0)
g5.record('verify', 'DS', 0.0085)  # actual (less than worst)
g5.record('sink', 'DS', 0.0120)
check(g5.summary()['compliant'], f"Within budget: spent=¥{g5.spent:.4f} ≤ ¥0.030")
check(g5.summary()['spent'] == 0.0205, f"Correct total: {g5.spent}")

print("\n== T6: Budget exhausted mid-plan ==")
g6 = CashGuard(cap=0.020)
g6.record('verify', 'DS', 0.0180)  # spent most on verify
ok6, action6 = g6.admit('sink', 'DS', remaining_after=[], pi={'sink':'DS'})
check(not ok6, f"DS sink refused after verify consumed budget: {action6}")
ok6b, action6b = g6.admit('sink', 'Flash', remaining_after=[], pi={'sink':'Flash'})
check(ok6b, f"Flash sink still allowed (free): {action6b}")

print("\n== T7: Worst-case exceeds but actual fits (conservative admission) ==")
g7 = CashGuard(cap=0.012)
# verify worst=0.0098, actual might be 0.006
# Conservative check uses worst → should admit if worst ≤ remaining
ok7, action7 = g7.admit('verify', 'DS', remaining_after=[], pi={'verify':'DS'})
check(ok7, f"DS verify admitted (worst 0.0098 ≤ 0.012): {action7}")
g7.record('verify', 'DS', 0.0060)  # actual less than worst
check(g7.summary()['compliant'], "Actual cost compliant")

print("\n== T8: Multiple DS calls cumulative check ==")
g8 = CashGuard(cap=0.025)
g8.record('n_sup1', 'DS', 0.0050)
g8.record('verify', 'DS', 0.0070)
# Spent 0.012, remaining 0.013. Sink worst=0.0165 > 0.013
ok8, action8 = g8.admit('sink', 'DS', remaining_after=[], pi={'sink':'DS'})
check(not ok8, f"DS sink refused (0.012+0.0165>0.025): {action8}")
check(action8[0] == 'fallback' and action8[2] == 'Flash', f"Falls back to Flash: {action8}")

print()
if fails:
    print(f"RESULT: {len(fails)} FAILURES")
    sys.exit(1)
print("RESULT: ALL PASS")
