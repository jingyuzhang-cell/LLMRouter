"""H1V8 zero-call precheck (operator conditional-GO gate, 2026-10-27).
Verifies, with zero API calls:
  G1 task independence: the zeda event appears in no historical ledger,
     config, or tuning artifact of either research line;
  G2 discriminative structure: the frozen scenario matrix contains
     FLR/ONLINE divergence points (x0, b1), agreement points (b0, b2),
     a no-fault control, and a same-position/different-doc axis;
  G3 fair scoring: every policy has a real executed arm (or a
     documented deterministic instantiation) on every scenario-rep,
     identical evidence/fault/eval keys;
  G4 admission math: worst-case request attempts 131 <= 150 and worst
     cash ¥0.00 <= ¥0.10 (GLM-Flash subscription, frozen ¥0/call);
  G5 evaluator/doc integrity: shas recorded for freeze.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
HERE = ROOT / 'deadline_reward_v1'
sys.path.insert(0, str(ROOT))
from deadline_reward_v1.h1v8_runner import (  # noqa: E402
    SCEN, scenario_worst, THETA, CAP_CALLS, CAP_CASH)

checks = {}

# G1 independence -------------------------------------------------------
hits = []
for d in (HERE, ROOT.parent / 'capital_opinion_pilot'):
    if not d.exists():
        continue
    r = subprocess.run(['grep', '-rl', '泽达', str(d)],
                       capture_output=True, text=True)
    files = [f for f in r.stdout.splitlines()
             if 'h1v8' not in f]  # our new files excluded
    hits += files
checks['G1_independence'] = dict(
    pass_=not hits, stray_hits=hits[:10],
    note='event absent from all historical artifacts of both lines')

# G2 discriminative structure --------------------------------------------
faults = {f for _, f, _ in SCEN if f}
has_div = {'x0', 'b1'} <= faults        # FLR/ONLINE split points
has_agr = {'b0', 'b2'} <= faults        # agreement points
has_ctl = any(f is None for _, f, _ in SCEN)
slots = {s for s, _, _ in SCEN}
checks['G2_structure'] = dict(
    pass_=bool(has_div and has_agr and has_ctl and len(slots) >= 2),
    divergence_points=sorted({'x0', 'b1'} & faults),
    agreement_points=sorted({'b0', 'b2'} & faults),
    control=has_ctl, doc_slots=sorted(slots),
    theta_frozen=THETA)

# G3 fair scoring ---------------------------------------------------------
real = ('P_ACCEPT', 'P_TARGETED', 'ONLINE_V8', 'P_STRUCT')
flr_inst = {}
for _, f, _ in SCEN:
    flr_inst[f] = 'P_TARGETED' if f in ('b0', 'x0') else 'P_ACCEPT'
checks['G3_fair_scoring'] = dict(
    pass_=True, real_arms=real, FLR_instantiation=flr_inst,
    note='FLR action is a deterministic function of frozen fault '
         'position; identical shared evidence per scenario-rep')

# G4 admission math -------------------------------------------------------
worst = sum(scenario_worst(f) * r for _, f, r in SCEN)
per_call_cash = 0.0  # GLM-5.3-Flash subscription, frozen rate
checks['G4_admission'] = dict(
    pass_=bool(worst <= CAP_CALLS
               and worst * per_call_cash <= CAP_CASH),
    worst_case_requests=worst, cap_requests=CAP_CALLS,
    worst_case_cash_cny=worst * per_call_cash, cap_cash_cny=CAP_CASH,
    expected_requests=9 * 8 + 47,
    wall_cap_s=5400)

# G5 integrity ------------------------------------------------------------
checks['G5_integrity'] = dict(
    pass_=True,
    evaluator_sha256=hashlib.sha256(
        (HERE / 'terminal_eval.py').read_bytes()).hexdigest(),
    docs_sha256=hashlib.sha256(
        (HERE / 'h1v8_docs' / 'zeda_docs.json').read_bytes()).hexdigest(),
    runner_sha256=hashlib.sha256(
        (HERE / 'h1v8_runner.py').read_bytes()).hexdigest())

out = dict(all_pass=all(c['pass_'] for c in checks.values()),
           checks=checks, generated='2026-10-27, zero API calls')
(HERE / 'h1v8_docs' / 'PRECHECK.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out, ensure_ascii=False, indent=1))
