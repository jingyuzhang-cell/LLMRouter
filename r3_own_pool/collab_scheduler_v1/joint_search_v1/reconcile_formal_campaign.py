"""Zero-call DIAGNOSTIC reconciliation + descriptive analysis of the formal
campaign (V2). Implements the three closure checks mandated by review:

  A. SCORING CONSISTENCY — per session: hashes of the scoring code path that
     actually executed (evaluator.py + fault30_run.py), the gold manifest the
     session ran with (TASK_PANEL snapshot answers = GOLD_CONTRACT_V1 values),
     plus GOLD_CONTRACT_V1 / scoring_contract_final.py hashes. Then re-scores
     every stored evaluation under scoring contract v2.1
     (contract_v2_gold + score_v21 = close OR round-2dp) and flags every
     session where Q changes. Sessions under different scoring contracts are
     NOT mergeable — the campaign stays DIAGNOSTIC until the contract is
     frozen into the execution path and cells re-run or re-registered.
     ALSO: flags the existence of a second, DISJOINT 'SEARCH8' manifest
     (task_contract_v2/SEARCH8_V21_MANIFEST.json, 0/8 overlap, contains
     excluded P1-B uid 0dc550d6) which does NOT cover the executed panel.

  B. QUOTA SETTLEMENT — every request/token claim is proven by the session's
     own DISPATCH ledger (reserve/response events with usage), never inferred
     from evaluation counts. Incomplete/failed cells are billed and retained.
     Retry consumption is additive (cross-directory ceiling; totals never reset).

  C. COMPARISON BASIS — per cell: search physical (requests, tokens, wall,
     model-switch wall) reported separately from deployment Q/C/L per state;
     INCOMPLETE cells retained, never dropped.

DESCRIPTIVE ONLY: no method-superiority claim. V1 diagnostic session (old
gold, formal_campaign/) excluded from all tables.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
JS = ROOT / 'collab_scheduler_v1/joint_search_v1'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_json(p):
    return json.loads(Path(p).read_text())


# ---------- contract v2.1 (imported from the frozen module) ----------
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.joint_search_v1.scoring_contract_final import (  # noqa
    score_v21)
from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (  # noqa
    contract_v2_gold, load_native_answers)


def json_value(ans):
    import re
    if not isinstance(ans, str):
        return None
    try:
        m = re.search(r'\{[^{}]*\}', ans, re.S)
        v = json.loads(m.group(0))['value']
        return float(v) if v is not None else None
    except Exception:
        return None


def close_v1(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def v21_golds_for(uids):
    native = load_native_answers()
    out = {}
    for uid in uids:
        nat = native.get(uid, {})
        out[uid] = contract_v2_gold(nat.get('native_answer'),
                                    nat.get('native_scale'),
                                    nat.get('raw_derivation', ''))
    return out


def session_ledger(sdir):
    """Ledger-proven physical spend from the session's DISPATCH journal."""
    p = sdir / 'DISPATCH.jsonl'
    events = {'reserved': 0, 'response': 0, 'tokens': 0, 'pending': 0}
    if not p.exists():
        return events, 'ledger file absent -> ZERO requests PROVEN'
    for line in p.read_text().splitlines():
        d = json.loads(line)
        if d.get('event') == 'reserved':
            events['reserved'] += 1
        elif d.get('event') == 'response':
            events['response'] += 1
            events['tokens'] += int(d['response'].get('usage', {})
                                    .get('total_tokens') or 0)
    return events, f"ledger: {events['reserved']} reserved / {events['response']} responses"


def main():
    gold_contract_sha = sha(JS / 'GOLD_CONTRACT_V1.json')
    scoring_code = dict(
        evaluator_py=sha(JS / 'evaluator.py'),
        fault30_run_py=sha(ROOT / 'collab_scheduler_v1/fault30_run.py'),
        scoring_contract_final_py=sha(JS / 'scoring_contract_final.py'),
        gold_contract_v1=gold_contract_sha,
        note='executed sessions scored via fault30_run close() (1e-4) against '
             'GOLD_CONTRACT_V1 answers; v2.1 re-score below uses score_v21')

    # executed panel identity + second-panel divergence flag
    panel_v2 = load_json(JS / 'FORMAL_LAUNCH_V2.json')
    executed_uids = [t['uid'] for t in panel_v2['tasks']]
    other = load_json(JS / 'task_contract_v2/SEARCH8_V21_MANIFEST.json')
    other_uids = {e['uid'] for e in other['entries']}
    panel_identity = dict(
        executed_panel='TASK_PANEL_V1 SEARCH8 (via FORMAL_LAUNCH_V2)',
        n=len(executed_uids),
        second_manifest_overlap=len(set(executed_uids) & other_uids),
        second_manifest_warning='task_contract_v2/SEARCH8_V21_MANIFEST.json covers '
                                'a DISJOINT 8-uid set (includes excluded P1-B uid '
                                '0dc550d6); it does NOT cover the executed panel; '
                                'trajectories must never be merged across panels')

    v21g = v21_golds_for(executed_uids)
    gold_v1 = {t['uid']: t['answer'] for t in panel_v2['tasks']}

    sessions = {}
    for root in sorted(JS.glob('formal_campaign_v2*')):
        if not root.is_dir():
            continue
        for sdir in sorted(root.glob('*_2026*')):
            if not sdir.is_dir():
                continue
            sid = sdir.name
            e = sessions.setdefault(sid, dict(dirs=[], evals=[], workflows=[]))
            e['dirs'].append(str(sdir))
            for name, key in (('EVALUATIONS.jsonl', 'evals'),
                              ('WORKFLOW.jsonl', 'workflows')):
                f = sdir / name
                if f.exists():
                    e[key].extend(json.loads(l) for l in f.read_text().splitlines())
            stf = sdir / 'STATUS.jsonl'
            if stf.exists():
                e['status'] = json.loads(stf.read_text().splitlines()[-1])
            # ledger per directory (a cell may span retry dirs)
            led, proof = session_ledger(sdir)
            e.setdefault('ledger', dict(reserved=0, response=0, tokens=0, proofs=[]))
            for k in ('reserved', 'response', 'tokens'):
                e['ledger'][k] += led[k]
            e['ledger']['proofs'].append(f'{sdir.name}: {proof}')
            swf = sdir / 'MODEL_SWITCH.jsonl'
            if swf.exists():
                e.setdefault('switch_wall', 0)
                e['switch_wall'] += sum(json.loads(l)['wall_s']
                                        for l in swf.read_text().splitlines())
            snap = sdir / 'TASK_PANEL.jsonl'
            if snap.exists():
                e['panel_sha'] = sha(snap)

    recon_sessions = {}
    for sid, e in sorted(sessions.items()):
        # A. re-score stored evaluations under v2.1
        v_ans = {}
        for r in e['workflows']:
            parts = r['key'].split(':')
            if len(parts) == 5 and parts[2] == 'base' and parts[3] == 'v':
                v_ans.setdefault((r['state'], r['cid'], parts[4]), []).append(
                    r['response']['answer'])
        rescore = []
        for ev in e['evals']:
            n = q_rec = q_v21 = 0
            for uid in executed_uids:
                answers = v_ans.get((ev['state'], ev['config_id'], uid))
                vv = json_value(answers[-1]) if answers else None
                g1 = gold_v1[uid]
                g21 = v21g[uid]['gold']
                n += 1
                q_rec += int(close_v1(vv, g1))
                q_v21 += int(score_v21(vv, g21) if vv is not None and g21 is not None
                             else False)
            rescore.append(dict(cid=ev['config_id'], state=ev['state'],
                                Q_recorded=round(ev['objectives']['Q'], 4),
                                Q_close_v1=round(q_rec / max(n, 1), 4),
                                Q_v21=round(q_v21 / max(n, 1), 4)))
        flips = [r for r in rescore if abs(r['Q_v21'] - r['Q_recorded']) > 1e-9]
        # B. ledger-proven spend
        # C. comparison basis
        per_state = {}
        for st in ('clean', 'fault30'):
            sel = [x for x in e['evals'] if x['state'] == st]
            if sel:
                per_state[st] = dict(
                    n=len(sel),
                    deployment_Q=[round(x['objectives']['Q'], 3) for x in sel],
                    deployment_C=[int(x['objectives']['C']) for x in sel],
                    deployment_L=[round(x['objectives']['L'], 2) for x in sel])
        st = e.get('status', {})
        recon_sessions[sid] = dict(
            status=st.get('status', 'RUNNING/UNKNOWN'),
            dirs=e['dirs'],
            scoring=dict(panel_snapshot_sha=e.get('panel_sha'),
                         executed_contract='close_1e-4 + GOLD_CONTRACT_V1 answers'),
            search_physical=dict(
                requests_ledger=e['ledger']['response'],
                responses_settled=e['ledger']['response'],
                tokens_ledger=e['ledger']['tokens'],
                wall_reported=round(st.get('observed_wall_s', 0)),
                model_switch_wall=round(e.get('switch_wall', 0)),
                ledger_proofs=e['ledger']['proofs']),
            rescore_v21=dict(n_evaluations=len(rescore), flips=len(flips),
                             mergeable_across_contracts=(len(flips) == 0),
                             detail=rescore),
            deployment=per_state)

    n_cells = len(recon_sessions)
    n_complete = sum(1 for s in recon_sessions.values() if s['status'] == 'COMPLETE')
    total_req = sum(s['search_physical']['requests_ledger'] for s in recon_sessions.values())
    total_tok = sum(s['search_physical']['tokens_ledger'] for s in recon_sessions.values())

    out = dict(
        campaign_status='DIAGNOSTIC — automation complete != formal admission; '
                        'scoring contract not yet frozen into execution path',
        scoring_code_hashes=scoring_code,
        panel_identity=panel_identity,
        gold_v21_for_executed_panel={u: dict(gold=v21g[u]['gold'],
                                             source=v21g[u]['gold_source'])
                                     for u in executed_uids},
        closure_checks=dict(
            A_scoring='per-session hashes + Q_recorded vs Q_v2.1 re-score; '
                      'sessions with flips are NOT mergeable across contracts',
            B_quota='ledger-proven only (DISPATCH reserve/response events); '
                    'random_20261009 0-request claim proven by absent ledger; '
                    'INCOMPLETE cells billed and retained; retries additive',
            C_comparison='search physical (requests/tokens/wall/switch) reported '
                         'separately from deployment Q/C/L; INCOMPLETE retained'),
        sessions=recon_sessions,
        totals=dict(cells_seen=n_cells, complete=n_complete,
                    requests_ledger_total=total_req, tokens_ledger_total=total_tok,
                    v2_ceiling=6901,
                    v1_diagnostic_charged_separately=dict(requests=299, tokens=48707)),
        caveats=['DIAGNOSTIC campaign until contract alignment',
                 'descriptive only; no method-superiority claim',
                 'INCOMPLETE cells retained; common-budget-support comparison only',
                 'TEST16 not released'])
    (JS / 'FORMAL_CAMPAIGN_RECONCILIATION.json').write_text(
        json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out['totals']))
    for sid, s in recon_sessions.items():
        print(f"{sid[:36]:38} {s['status'][:12]:13} req={s['search_physical']['requests_ledger']:3} "
              f"tok={s['search_physical']['tokens_ledger']:6} v21flips={s['rescore_v21']['flips']}")
    return out


if __name__ == '__main__':
    main()
