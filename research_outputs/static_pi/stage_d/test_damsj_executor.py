"""Zero-call stress tests for the DAMJS executor wrapper (mock child process).

Verifies the five operator-required P0/P1 properties:
  P0-a L3 global deadline stops dispatch
  P0-b L4 degraded output keeps completed, marks rest UNKNOWN
  P0-c L2 node timeout truly aborts a hung child
  P1-a late results isolated (never merged)
  P1-b budget guard prevents overrun
"""
import json, os, sys, tempfile, time
from damsj_executor import (run_isolated, ProgressLog, BudgetGuard, Quarantine,
                            merge_guarded)

PASS, FAIL = [], []
def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))

TMP = tempfile.mkdtemp(prefix='damsj_')
CHILD = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), '_damsj_child.py')]

def run(deadline, hang='', slow='', fail='', reserve=1.0, tag='x'):
    prog = os.path.join(TMP, f'prog_{tag}.jsonl')
    canc = os.path.join(TMP, f'cancel_{tag}')
    cmd = CHILD + ['--progress', prog, '--cancel', canc]
    if hang: cmd += ['--hang', hang]
    if slow: cmd += ['--slow', slow]
    if fail: cmd += ['--fail', fail]
    r = run_isolated(arm='DAMJS', scenario='S4', rep=1, deadline_s=deadline,
                     exec_cmd=cmd, progress_path=prog, cancel_path=canc,
                     reserve_s=reserve, kill_grace_s=0.3, poll_s=0.05)
    return r, ProgressLog(prog)

print("\nP0-c L2/L3: hung child is truly aborted at deadline")
r, plog = run(deadline=2.0, hang='E2:60', reserve=1.0, tag='hang')
check("child aborted (not COMPLETE)", r['status'] != 'COMPLETE', r['status'])
check("elapsed bounded by deadline", r['elapsed'] <= 2.0 + 3.0, f"elapsed={r['elapsed']}")
check("hung node never reported completed", 'E2' not in r['completed_nodes'])
check("E1 completed before hang is retained", 'E1' in r['completed_nodes'], str(r['completed_nodes']))

print("\nP0-a L3: no dispatch after deadline")
starts = [x for x in plog.read() if x.get('ev') == 'node_start']
last_start = max((x.get('ts', 0) for x in starts), default=0)
first_ts = min((x.get('ts', 0) for x in plog.read()), default=0)
check("no node started after abort budget elapsed",
      (last_start - first_ts) < 2.0, f"span={last_start-first_ts:.2f}s")

print("\nP0-b L4: degraded output structure")
check("status is DEGRADED", r['answer_status'] == 'DEGRADED')
check("completed nodes listed", len(r['completed_nodes']) >= 1)
check("partial outputs are dict of node->text",
      all(isinstance(v, str) for v in r['partial_outputs'].values()))

print("\nP1-a late-result isolation")
q = Quarantine(os.path.join(TMP, 'quarantine.jsonl'))
q.put('E2', {'text': 'ghost-late-result'}, reason='aborted')
merged = merge_guarded(r['partial_outputs'], q.entries())
check("late node excluded from merged map", 'E2' not in merged)
check("quarantine recorded the ghost", q.entries()[0]['node'] == 'E2')

print("\nP1-b budget guard")
b = BudgetGuard(calls_max=3, tokens_max=1000, yuan_max=0.01)
ok_count = 0
try:
    for i in range(5):
        b.precheck(est_tokens=300, est_yuan=0.004); b.commit(300, 0.004); ok_count += 1
except RuntimeError as e:
    pass
check("budget stops before overrun", ok_count <= 3 and b.calls <= 3, f"calls={b.calls} ok={ok_count}")
check("tokens never exceed cap", b.tokens <= 1000, f"tokens={b.tokens}")
check("yuan never exceeds cap", b.yuan <= 0.01 + 1e-9, f"yuan={b.yuan}")

print("\nP0 fast path: normal completion is COMPLETE")
r2, _ = run(deadline=30.0, slow='J1:0.3', tag='fast')
check("normal run is COMPLETE", r2['status'] == 'COMPLETE', r2['status'])
check("all nodes completed", len(r2['completed_nodes']) == 8, str(len(r2['completed_nodes'])))

print("\nFailed node is not treated as completed")
r3, _ = run(deadline=30.0, fail='J2', tag='fail')
check("failed node absent from completed", 'J2' not in r3['completed_nodes'])
check("other nodes retained", 'E1' in r3['completed_nodes'])

print(f"\n{'='*60}\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL: print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
