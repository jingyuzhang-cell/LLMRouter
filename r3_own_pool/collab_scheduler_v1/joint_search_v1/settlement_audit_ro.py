"""FORMAL settlement audit — READ-ONLY evidence verification. Zero model
calls, no GPU, no writes outside settlement_audit_ro/.

Verifies, from the frozen campaign artifacts alone:
  A. journal integrity: every root's CAMPAIGN.jsonl binds the SAME
     protocol sha + caps; every reserved session settles EXACTLY once;
     no unknown events;
  B. three-way reconciliation per session: DISPATCH reservations ==
     STATUS new_requests; DISPATCH settled usage tokens == STATUS
     charged_tokens; CAMPAIGN settle charge == STATUS record;
  C. cap compliance: per-session charges within per_session_caps;
     campaign totals (incl. the frozen prior v1 consumption) within
     campaign_caps;
  D. retry legitimacy: every retry-root session's ORIGINAL failure in an
     earlier root is an infra failure (termination / File exists /
     interrupted / deadline) per the driver policy, and the retry settled
     COMPLETE;
  E. announced-figure check: envelope totals, COMPLETE-only totals (the
     method-comparison accounting), 18/18 methods x seeds, and the
     per-arm request totals behind the 'proposed ties wo_state at 663'
     claim;
  F. no reserved-but-unsettled (crash) sessions are silently missing.

Run: python3 -m collab_scheduler_v1.joint_search_v1.settlement_audit_ro
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
JS = HERE
OUT = HERE / 'settlement_audit_ro'
INFRA = ('termination', 'File exists', 'interrupted', 'deadline')

protocol = json.loads((JS / 'SEARCH_BUDGET_V1.json').read_text())
launch = json.loads((JS / 'FORMAL_LAUNCH_V2.json').read_text())
PROTO_SHA_EXPECTED = launch['protocol_sha256']
CAPS = protocol['campaign_caps']
PSC = protocol['per_session_caps']
PRIOR = launch.get('prior_consumption', {})


def jload(p: Path):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def main():
    OUT.mkdir(exist_ok=True)
    checks = {}
    rows = []
    roots = sorted(JS.glob(launch.get('campaign_root', 'formal_campaign')
                           + '*'))
    roots = [r for r in roots if (r / 'CAMPAIGN.jsonl').exists()]

    # ---- A. journal integrity ------------------------------------------
    proto_ok, dup_settle, unknown_ev, unsettled = True, [], [], []
    sessions = {}          # (root, sid) -> record
    by_sid = {}            # sid -> [(root, status, reason, charges)]
    for root in roots:
        evs = jload(root / 'CAMPAIGN.jsonl')
        if evs[0] != dict(event='protocol', sha256=PROTO_SHA_EXPECTED,
                          caps=CAPS):
            proto_ok = False
        seen = set()
        for e in evs[1:]:
            if e['event'] == 'reserved':
                sid = e['session']
                if sid in seen:
                    dup_settle.append((root.name, sid, 'dup reserve'))
                seen.add(sid)
                unsettled.append((root.name, sid))
            elif e['event'] == 'settled':
                sid = e['session']
                if sid not in seen:
                    dup_settle.append((root.name, sid, 'settle w/o reserve'))
                seen.discard(sid)
                by_sid.setdefault(sid, []).append(
                    (root.name, e['status'], e.get('reason', ''),
                     dict(e['charge'])))
            else:
                unknown_ev.append((root.name, e.get('event')))
        unsettled = [u for u in unsettled
                     if u[0] == root.name and u[1] in seen] + \
                    [u for u in unsettled if u[0] != root.name]
    checks['A_protocol_binding_all_roots'] = proto_ok
    checks['A_no_duplicate_or_orphan_settles'] = not dup_settle
    checks['A_only_known_events'] = not unknown_ev
    checks['A_every_reserved_settled'] = not unsettled

    # ---- B. per-session three-way reconciliation -----------------------
    recon_fail = []
    crash_recon = []
    for root in roots:
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            sid = d.name
            if not (d / 'STATUS.jsonl').exists():
                # Hard crash between journal settle and the STATUS write.
                # Hardening A (crash reconciliation): reconcile what the
                # surviving PRIMARY evidence allows and REPORT explicit
                # evidence gaps. Never a silent pass.
                camp = next(((r[3]) for r in by_sid.get(sid, [])
                             if r[0] == root.name), None)
                if (d / 'DISPATCH.jsonl').exists():
                    disp_c = jload(d / 'DISPATCH.jsonl')
                    c_res = sum(1 for e in disp_c
                                if e['event'] == 'reserved')
                    c_resp = sum(1 for e in disp_c
                                 if e['event'] == 'response')
                    c_tok = sum(e['response']['usage']['total_tokens']
                                for e in disp_c
                                if e['event'] == 'response')
                    c_legal = all(
                        e.get('event') in ('reserved', 'response')
                        and (e['event'] != 'response' or isinstance(
                            e.get('response', {}).get('usage'), dict))
                        for e in disp_c)
                    resp_ids = set(e['id'] for e in disp_c
                                   if e['event'] == 'response')
                    unmatched = [e for e in disp_c
                                 if e['event'] == 'reserved'
                                 and e['id'] not in resp_ids]
                    c_gap_tok = sum(e.get('tokens', 0) for e in unmatched)
                    # honest evidence: reserves == campaign requests;
                    # events legal; response tokens == campaign tokens.
                    # Unmatched reservations are EXPECTED in a crash and
                    # are disclosed (Budget semantics say they stay
                    # charged, so the campaign token charge may
                    # under-count by that amount).
                    ok = (camp is not None
                          and c_res == camp['new_request_attempts']
                          and c_legal
                          and c_tok == camp['new_total_tokens'])
                    gap_txt = ('STATUS.jsonl absent: wall/settle status '
                               'unverifiable. ' + str(len(unmatched))
                               + ' unmatched reservation(s) ('
                               + str(c_gap_tok)
                               + ' reserved tokens) with no response '
                               '- charge may under-count the crashed '
                               'reservation per Budget semantics; '
                               'disclosed as an evidence gap')
                    crash_recon.append(dict(
                        sid=sid, root=root.name,
                        dispatch_present=True,
                        dispatch_reserved=c_res,
                        dispatch_responses=c_resp,
                        events_legal=c_legal,
                        dispatch_tokens=c_tok,
                        unmatched_reservations=len(unmatched),
                        unmatched_reserved_tokens=c_gap_tok,
                        campaign_requests=(camp
                                           and camp['new_request_attempts']),
                        campaign_tokens=(camp
                                         and camp['new_total_tokens']),
                        reconciled=ok, gap=gap_txt))
                    if not ok:
                        recon_fail.append((sid, 'crash reconcile',
                                           c_res, c_tok, camp))
                else:
                    zero_ok = (camp is not None
                               and camp['new_request_attempts'] == 0
                               and camp['new_total_tokens'] == 0)
                    crash_recon.append(dict(
                        sid=sid, root=root.name,
                        dispatch_present=False,
                        campaign_requests=(camp
                                           and camp['new_request_attempts']),
                        campaign_tokens=(camp
                                         and camp['new_total_tokens']),
                        reconciled=zero_ok,
                        gap='neither STATUS nor DISPATCH on disk: only '
                            'the zero-charge journal entry survives - '
                            'nothing to reconcile beyond charge==0'))
                    if not zero_ok:
                        recon_fail.append((sid, 'crash no-dispatch '
                                           'but charged', camp))
                rows.append(dict(root=root.name, sid=sid,
                                 status='NO_STATUS_ON_DISK',
                                 reason='hard-crash (journal settled, '
                                        'STATUS never written)',
                                 campaign_charge=camp))
                continue
            st = jload(d / 'STATUS.jsonl')
            # infra-crash sessions can fail BEFORE the Budget exists
            # (e.g. GPU busy / mkdir collision): no DISPATCH.jsonl, and
            # STATUS must then legitimately record zero spend
            disp = jload(d / 'DISPATCH.jsonl') \
                if (d / 'DISPATCH.jsonl').exists() else []
            res_n = sum(1 for e in disp if e['event'] == 'reserved')
            ok_n = sum(1 for e in disp if e['event'] == 'response')
            tok = sum(e['response']['usage']['total_tokens']
                      for e in disp if e['event'] == 'response')
            camp = next(((r[3]) for r in by_sid.get(sid, [])
                         if r[0] == root.name), None)
            status = st[-1]
            row = dict(root=root.name, sid=sid,
                       status=status['status'],
                       reason=status.get('reason', ''),
                       dispatch_reserved=res_n,
                       dispatch_responses=ok_n,
                       dispatch_tokens=tok,
                       status_requests=status['new_requests'],
                       status_tokens=status['charged_tokens'],
                       campaign_charge=camp)
            rows.append(row)
            if res_n != ok_n or res_n != status['new_requests']:
                recon_fail.append((sid, 'requests',
                                   res_n, ok_n, status['new_requests']))
            if tok != status['charged_tokens']:
                recon_fail.append((sid, 'tokens', tok,
                                   status['charged_tokens']))
            if camp is not None and (
                    camp['new_request_attempts'] != status['new_requests']
                    or abs(camp['new_total_tokens']
                           - status['charged_tokens']) > 1e-6):
                recon_fail.append((sid, 'campaign-vs-status', camp,
                                   status['new_requests'],
                                   status['charged_tokens']))
            if camp is not None and camp['wall_seconds'] < 0:
                recon_fail.append((sid, 'negative wall', camp))
    checks['B_three_way_reconciliation'] = not recon_fail

    # ---- C. cap compliance ----------------------------------------------
    cap_fail = []
    for r in rows:
        c = r['campaign_charge']
        if c is None:
            continue
        if c['new_request_attempts'] > PSC['new_request_attempts']:
            cap_fail.append((r['sid'], 'session requests', c))
        if c['new_total_tokens'] > PSC['new_total_tokens']:
            cap_fail.append((r['sid'], 'session tokens', c))
    tot_req = sum(r['campaign_charge']['new_request_attempts']
                  for r in rows if r['campaign_charge'])
    tot_tok = sum(r['campaign_charge']['new_total_tokens']
                  for r in rows if r['campaign_charge'])
    grand_req = tot_req + PRIOR.get('requests', 0)
    grand_tok = tot_tok + PRIOR.get('tokens', 0)
    checks['C_session_caps'] = not cap_fail
    checks['C_campaign_requests'] = grand_req <= CAPS['new_request_attempts']
    checks['C_campaign_tokens'] = grand_tok <= CAPS['new_total_tokens']
    checks['C_v2_headroom_rule'] = (
        tot_req <= CAPS['new_request_attempts']
        - PRIOR.get('requests', 0))

    # F1 attribution evidence (audit hardening): every retried sid must
    # match a 'retrying' line in a RESUME_DRIVER log; unmatched sids
    # downgrade the attribution to journal-reason-only.
    import re as _re
    retry_log = {}
    for lg in sorted((JS / 'formal_campaign_v2'
                      ).glob('RESUME_DRIVER*.log')):
        for line in lg.read_text().splitlines():
            m = _re.search(r'"retrying": "([^"]+)"', line)
            if m:
                retry_log[m.group(1)] = lg.name
    retried_sids = sorted(sid for sid, r in by_sid.items()
                          if len(r) > 1)
    unmatched = [sid for sid in retried_sids if sid not in retry_log]

    # ---- D. retry legitimacy --------------------------------------------
    # Two levels, reported separately (audit honesty):
    #  (a) SEMANTIC: every retried original is infrastructure-class
    #      (the frozen driver tuple + GPU busy + Model server exited +
    #      BlockingIOError + hard-crash-no-STATUS) and every retry
    #      settles COMPLETE; NO search-logic failure was ever retried.
    #  (b) LITERAL: the in-process driver's INFRA_FAILURE tuple does not
    #      cover several actually-retried reasons — the retries were
    #      orchestrated by the RESUME_DRIVER processes with a broader
    #      but still infra-only criterion. Reported as a FINDING with
    #      the exact reasons; never massaged into a pass.
    INFRA_SEMANTIC = INFRA + ('GPU busy', 'Model server exited',
                              'BlockingIOError')
    retry_semantic_fail, literal_mismatch = [], []
    first_root = {}       # sid -> (root, status, reason)
    for r in sorted(rows, key=lambda x: (x['root'], x['sid'])):
        prev = first_root.get(r['sid'])
        if prev is None:
            first_root[r['sid']] = (r['root'], r['status'], r['reason'])
            continue
        if not any(k in prev[2] for k in INFRA_SEMANTIC) \
                and prev[1] != 'NO_STATUS_ON_DISK':
            retry_semantic_fail.append((r['sid'], 'original not infra',
                                        prev))
        if not any(k in prev[2] for k in INFRA) \
                and prev[1] != 'NO_STATUS_ON_DISK':
            literal_mismatch.append((r['sid'], prev[2]))
        if r['status'] != 'COMPLETE':
            retry_semantic_fail.append((r['sid'], 'retry not COMPLETE',
                                        r['status']))
    # every INCOMPLETE anywhere must be infra-class (no search-logic
    # failure ever entered the journals as a session failure)
    non_infra_incomplete = [r['sid'] for r in rows
                            if r['status'] == 'INCOMPLETE'
                            and not any(k in r['reason']
                                        for k in INFRA_SEMANTIC)]
    checks['D_retry_semantic_infra_only'] = (
        not retry_semantic_fail and not non_infra_incomplete)
    checks['D_no_search_logic_failure_retried_or_present'] = (
        not non_infra_incomplete)
    checks['D_resume_log_attribution'] = (
        len(retried_sids) == 10 and not unmatched)
    findings = [dict(
        id='F1-retry-criterion-broader-than-driver-tuple',
        detail='retries for reasons outside the in-process '
               'INFRA_FAILURE tuple; all are infrastructure-class '
               '(GPU busy / Model server exited / BlockingIOError / '
               'FileExists / wall termination / hard crash), every '
               'retry settled COMPLETE, no search-logic failure was '
               'retried. Attribution: per-sid "retrying" log lines in '
               'RESUME_DRIVER*.log cover all retried sessions '
               '(evidence per session below); sessions without a log '
               'line would be downgraded to journal-reason-only.',
        retried_sessions=[dict(sid=sid, log=retry_log.get(sid))
                          for sid in retried_sids],
        outside_literal_tuple=sorted(sid for sid, _ in
                                     literal_mismatch))]

    # ---- E. announced figures -------------------------------------------
    complete = [r for r in rows if r['status'] == 'COMPLETE']
    comp_req = sum(r['campaign_charge']['new_request_attempts']
                   for r in complete)
    comp_tok = sum(r['campaign_charge']['new_total_tokens']
                   for r in complete)
    methods = protocol['methods']
    seeds = protocol['search_seeds']
    expected_sids = {f'{m}_{s}' for m in methods for s in seeds}
    got_complete = {r['sid'] for r in complete}
    arm_req = {}
    for r in complete:
        arm_req[r['sid']] = r['campaign_charge']['new_request_attempts']
    per_arm = {}
    for m in methods:
        per_arm[m] = sum(v for k, v in arm_req.items()
                         if k.rsplit('_', 1)[0] == m)
    checks['E_18_unique_complete'] = (
        len(complete) == 18 and got_complete == expected_sids)
    checks['E_expected_8_roots'] = (
        [r.name for r in roots] == ['formal_campaign_v2']
        + [f'formal_campaign_v2_retry{i}' for i in range(1, 8)])
    checks['E_28_total_settled'] = len(rows) == 28
    checks['E_envelope_requests_4871'] = tot_req == 4871
    checks['E_envelope_tokens_exact'] = tot_tok == 1_743_814
    checks['E_complete_only_4542'] = comp_req == 4542
    checks['E_complete_only_tokens_exact'] = comp_tok == 1_620_410
    checks['E_grand_with_prior_exact'] = (
        grand_req == 5170 and grand_tok == 1_792_521)
    checks['E_proposed_ties_wo_state_663'] = (
        per_arm.get('proposed_state_incremental') == 663
        and per_arm.get('proposed_without_state') == 663)
    checks['E_prior_299_carried'] = PRIOR.get('requests') == 299

    # ---- F. crash sessions ----------------------------------------------
    incomplete = [r for r in rows if r['status'] != 'COMPLETE']
    unresolved = [r['sid'] for r in incomplete
                  if r['sid'] not in got_complete]
    checks['F_no_unresolved_incomplete'] = not unresolved

    evidence = dict(
        audit='formal_settlement_read_only', zero_model_calls=True,
        checks=checks, all_pass=all(checks.values()),
        totals=dict(envelope_requests=tot_req, envelope_tokens=tot_tok,
                    grand_with_prior_requests=grand_req,
                    grand_with_prior_tokens=grand_tok,
                    complete_only_requests=comp_req,
                    complete_only_tokens=comp_tok,
                    complete_sessions=len(complete),
                    total_settled_sessions=len(rows)),
        per_arm_complete_requests=per_arm,
        roots=[r.name for r in roots],
        sessions=rows, recon_failures=recon_fail[:20],
        cap_failures=cap_fail[:20],
        retry_semantic_failures=retry_semantic_fail[:20],
        literal_mismatch=[list(x) for x in literal_mismatch],
        crash_reconciliation=crash_recon,
        findings=findings)
    (OUT / 'SETTLEMENT_AUDIT_RO.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'\n{sum(checks.values())}/{len(checks)} checks; '
          f'{"ALL PASS" if all(checks.values()) else "FAIL PRESENT"}')
    print(f'envelope {tot_req} req / {tot_tok:.0f} tok; '
          f'COMPLETE-only {comp_req} req / {comp_tok:.0f} tok; '
          f'prior {PRIOR.get("requests")} req carried')
    return 0 if all(checks.values()) else 2


if __name__ == '__main__':
    raise SystemExit(main())
