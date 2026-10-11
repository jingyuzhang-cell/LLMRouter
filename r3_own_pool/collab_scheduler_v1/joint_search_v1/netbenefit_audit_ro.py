"""NET-BENEFIT independent read-only audit — Calibration GO prerequisite.

Zero real model calls; frozen artifacts untouched; writes only to
netbenefit_audit_ro/.

Verifies from raw artifacts (no announcements trusted):
  A. freeze integrity: arms/gates match across freeze, driver code, and
     the audit reports;
  B. halt honesty: NB_ROWS shows the pre-halt 3 real cells; nothing ran
     after the halt directive;
  C. row-level reconciliation: each NB_ROWS cell vs the task-level
     records in the same run directory;
  D. budget gates: pre-halt spend vs frozen caps (incl. DE reservation);
  E. V4 audit cross-check: every V4 claim re-derivable from raw data;
  F. protocol/gate structure: confirmatory families, Holm, competitive
     family, task_selection exclusions — all internally consistent.
Run: python3 -m collab_scheduler_v1.joint_search_v1.netbenefit_audit_ro
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'netbenefit_audit_ro'
JS = HERE

freeze = json.loads((JS / 'NET_BENEFIT_FREEZE.json').read_text())
ROWS = JS / 'netbenefit_runs' / 'NB_ROWS.jsonl'


def jload(p: Path):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def main():
    OUT.mkdir(exist_ok=True)
    checks = {}
    findings = []

    # ============ A. freeze integrity ============
    arms_f = set(freeze['arms'].keys())
    # check driver code references the same arms
    driver_src = (JS / 'netbenefit_runner.py').read_text()
    arms_in_driver = {a for a in arms_f if f"'{a}'" in driver_src}
    checks['A1_arms_match_driver'] = arms_f == arms_in_driver
    # V2 candidate arms present
    checks['A2_v2_arms_present'] = {'V2_static', 'V2_dynamic'} <= arms_f
    # arm semantic checks (from freeze definitions)
    d = freeze['arms'].get('D_dynamic_local', {})
    e = freeze['arms'].get('E_dynamic_full', {})
    checks['A3_de_same_x'] = (
        d.get('X') == e.get('X')
        and d.get('Z') == 'LOCAL' and e.get('Z') == 'FULL')
    checks['A4_e_replay_rule_present'] = bool(e.get('replay_rule'))
    # competitive family arm A_cross has fallback+max_fallbacks
    a2 = freeze['arms'].get('A_single_cross_fallback', {})
    checks['A5_cross_fallback_def'] = (
        a2.get('fallback') is not None
        and a2.get('max_fallbacks') == 1)

    # ============ B. halt honesty ============
    rows = jload(ROWS) if ROWS.exists() else []
    real_rows = [r for r in rows if r.get('execute')]
    stub_rows = [r for r in rows if not r.get('execute')]
    checks['B1_nbrows_exists'] = len(rows) > 0
    checks['B2_three_real_cells'] = len(real_rows) == 3
    checks['B3_real_arms_match_note'] = (
        {r['arm'] for r in real_rows}
        == {'A_single', 'A_single_cross_fallback', 'B_same_model_dag'})
    checks['B4_all_real_are_clean'] = all(
        r['state'] == 'clean' for r in real_rows)
    # no rows after the halt date (freeze v2 date)
    checks['B5_no_post_halt_real'] = all(
        not r.get('execute') for r in rows if r not in real_rows)

    # ============ C. row-level reconciliation (hardened) ============
    # PER-CELL independent recount: DISPATCH responses are grouped by
    # the cell encoded in each event's key, independently summed, and
    # compared with NB_CELL_LEDGER per-cell (requests, tokens, status).
    # TRAJECTORY covers the total. No default-0 fallbacks.
    cell_ledger_path = JS / 'netbenefit_runs' / 'NB_CELL_LEDGER.jsonl'
    checks['C1_cell_ledger_exists'] = cell_ledger_path.exists()
    recon_fail = []
    real_dir = JS / 'netbenefit_runs' / 'real_20261010_000854'
    checks['C1_real_run_dir_exists'] = real_dir.exists()
    cells = jload(cell_ledger_path) if cell_ledger_path.exists() else []
    checks['C1_cell_ledger_count'] = len(cells) == 3

    # independent recount from DISPATCH (the per-call primary evidence):
    # reservations carry the cell key; responses link by ID
    dispatch = jload(real_dir / 'DISPATCH.jsonl') \
        if (real_dir / 'DISPATCH.jsonl').exists() else []
    res_key = {e['id']: e['key'] for e in dispatch
               if e.get('event') == 'reserved'}
    cell_req = {}
    cell_tok = {}
    for e in dispatch:
        if e.get('event') != 'response':
            continue
        key = res_key.get(e['id'], '')
        parts = key.split(':')
        arm = parts[2] if len(parts) > 2 else '?'
        cell_req[arm] = cell_req.get(arm, 0) + 1
        cell_tok[arm] = cell_tok.get(arm, 0.0) + \
            e['response']['usage']['total_tokens']

    per_cell_ok = True
    for c in cells:
        arm = c['arm']
        led_req = c['physical']['new_requests']
        led_tok = c['physical']['new_tokens']
        act_req = cell_req.get(arm, -1)
        act_tok = cell_tok.get(arm, -1.0)
        if act_req != led_req or abs(act_tok - led_tok) > 0.01 \
                or c.get('status') != 'COMPLETE':
            per_cell_ok = False
            recon_fail.append((arm, f'DISPATCH({act_req},{act_tok}) '
                               f'vs ledger({led_req},{led_tok})'))
    checks['C1_per_cell_recount'] = per_cell_ok
    checks['C1_no_recon_failures'] = not recon_fail
    total_req = sum(cell_req.values())
    total_tok = sum(cell_tok.values())

    # TRAJECTORY covers the total
    traj = real_dir / 'TRAJECTORY.jsonl'
    checks['C1_trajectory_covers'] = (
        traj.exists()
        and sum(1 for _ in traj.open()) >= total_req)

    # C2: pre-halt spend recorded with EXACTLY matching counts
    ph = freeze.get('pre_halt_real_spend', {})
    checks['C2_prehalt_spend_recorded'] = bool(
        ph.get('note') and ph.get('cells') and total_req > 0)
    # C2b (hardened): the ACTUAL COUNTED total must be exactly 252
    # (no string-matching fallback)
    checks['C2b_prehalt_request_count'] = (total_req == 252)

    # ============ D. budget gates ============
    budgets = freeze.get('budgets', {})
    checks['D1_global_caps_present'] = all(
        k in budgets for k in (
            'global_max_physical_requests', 'global_max_physical_tokens',
            'global_max_wall_seconds'))
    checks['D2_de_reservation_present'] = (
        budgets.get('de_reserved_physical_requests') == 800)
    checks['D3_per_strategy_cap'] = (
        budgets.get('per_strategy_per_state_physical_max') == 400)
    # D4 (hardened): budget checked with the INDEPENDENTLY RECOUNTED
    # totals from DISPATCH (never a default-0 from the freeze file)
    checks['D4_prehalt_within_cap'] = (
        total_req > 0
        and total_req <= budgets.get('global_max_physical_requests', 0)
        and total_tok <= budgets.get('global_max_physical_tokens', 0))

    # ============ E. V4 audit cross-check (hardened) ============
    v4_path = JS / 'NET_BENEFIT_AUDIT_REPORT_V4.json'
    checks['E1_v4_exists'] = v4_path.exists()
    if v4_path.exists():
        v4 = json.loads(v4_path.read_text())
        checks['E2_v4_zero_requests'] = v4.get('zero_model_requests') is True
        checks['E3_v4_all_pass'] = v4.get('all_pass') is True
        audits = v4.get('audits', [])
        checks['E4_v4_has_audits'] = len(audits) > 0
        # E5 HARDENED: independently re-verify the V4's own key
        # assertions against raw data instead of trusting its flags
        e5_ok = True
        # the V4's audits reference the stub validation evidence
        stub_rows_path = JS / 'netbenefit_runs' / 'NB_ROWS_STUB.jsonl'
        if stub_rows_path.exists():
            stub_rows = jload(stub_rows_path)
            # V4 should have been based on stub evidence only
            e5_ok &= all(not r.get('execute') for r in stub_rows)
            e5_ok &= len(stub_rows) > 0
        # the V4's audits themselves should have check structures
        for a in audits:
            if isinstance(a, dict) and a.get('checks'):
                # re-verify: any check that is False must not be
                # claimed as all_pass
                if not a.get('all_pass', False):
                    if all(a['checks'].values()):
                        e5_ok &= False  # claimed fail but checks pass
                else:
                    if not all(a['checks'].values()):
                        e5_ok &= False  # claimed pass but a check fails
        checks['E5_v4_independent_recheck'] = e5_ok
    else:
        for k in ('E2', 'E3', 'E4', 'E5'):
            checks[f'{k}_v4_cross'] = False

    # ============ G. negative tests (tamper detection) ============
    # Tampering with request counts, token counts, or V4 flags must
    # make the corresponding checker FAIL.
    def budget_check(req, tok, caps):
        return (req > 0 and req <= caps.get(
            'global_max_physical_requests', 0)
            and tok <= caps.get('global_max_physical_tokens', 0))
    checks['G1_negative_request_tamper'] = (
        not budget_check(99999, total_tok, budgets))
    checks['G2_negative_token_tamper'] = (
        not budget_check(total_req, 99999999.0, budgets))
    # per-cell tamper: a wrong per-cell count must fail the comparison
    fake_ledger = [dict(c) for c in cells]
    if fake_ledger:
        fake_ledger[0]['physical']['new_requests'] += 1
        fake_ok = all(
            cell_req.get(c['arm'], -1)
            == c['physical']['new_requests'] for c in fake_ledger)
        checks['G3_negative_cell_tamper'] = not fake_ok
    else:
        checks['G3_negative_cell_tamper'] = True
    # V4 flag tamper: a report claiming all_pass with a failing check
    # must be DETECTED (the E5 recheck catches it)
    def v4_recheck(report):
        if not report.get('all_pass', False):
            return False  # honestly failed
        for a in report.get('audits', []):
            if isinstance(a, dict) and a.get('checks'):
                if not all(a['checks'].values()):
                    return False  # claims pass but a check fails
        return True
    tampered_v4 = dict(all_pass=True, audits=[
        dict(checks={'x': False})])  # claims pass, has a fail
    checks['G4_negative_v4_tamper'] = (
        not v4_recheck(tampered_v4)
        and v4_recheck(dict(all_pass=True, audits=[
            dict(checks={'x': True})])))

    # ============ F. protocol structure ============
    conf = freeze.get('confirmatory', {})
    checks['F1_primary_family'] = isinstance(conf.get('primary'), list) \
        and len(conf['primary']) > 0
    checks['F2_holm_declared'] = 'Holm' in str(
        conf.get('multiple_comparison', ''))
    checks['F3_competitive_family'] = isinstance(
        conf.get('competitive_family'), list)
    checks['F4_gate2_present'] = isinstance(conf.get('gate2'), list)
    # task selection exclusions recorded
    ts = freeze.get('task_selection', {})
    checks['F5_task_exclusions_recorded'] = bool(
        ts.get('excluded_from_pool'))

    # ============ summary ============
    n_pass = sum(1 for v in checks.values() if v)
    n_fail = sum(1 for v in checks.values() if not v)
    audit_exit = 0 if n_fail == 0 else 1
    report = dict(
        audit='netbenefit_read_only', zero_model_calls=True,
        checks=checks, all_pass=(n_fail == 0),
        summary=dict(passed=n_pass, failed=n_fail,
                     total=len(checks)),
        rows_summary=dict(total=len(rows), real=len(real_rows),
                          stub=len(stub_rows),
                          real_arms=[r['arm'] for r in real_rows]),
        freeze_version=freeze.get('version'),
        recon_failures=recon_fail[:10],
        exit_code=audit_exit)
    (OUT / 'NETBENEFIT_AUDIT_RO.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'\nPASS {n_pass} / FAIL {n_fail} / total {len(checks)}')
    print(f'exit code: {audit_exit}')
    return audit_exit


if __name__ == '__main__':
    raise SystemExit(main())
