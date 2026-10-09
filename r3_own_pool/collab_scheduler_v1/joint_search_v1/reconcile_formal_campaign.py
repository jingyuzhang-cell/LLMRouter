"""Zero-call diagnostic live reconciliation. Current-source hashes are not
execution-time evidence. Missing ledgers leave spend UNKNOWN. Request attempts
include reserved requests without responses; recorded tokens are lower bounds.
Re-score persisted final_value (including recovery/FULL), never infer it from
base-node responses. Zero flips do not permit cross-contract merging.
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
        return events, 'UNKNOWN: ledger absent; zero spend not proven'
    for line in p.read_text().splitlines():
        d = json.loads(line)
        if d.get('event') == 'reserved':
            events['reserved'] += 1
        elif d.get('event') == 'response':
            events['response'] += 1
            events['tokens'] += int(d['response'].get('usage', {})
                                    .get('total_tokens') or 0)
    events['pending'] = max(0, events['reserved'] - events['response'])
    return events, f"ledger: {events['reserved']} attempts / {events['response']} responses / {events['pending']} unresolved; tokens are recorded lower bound"


def main():
    gold_contract_sha = sha(JS / 'GOLD_CONTRACT_V1.json')
    scoring_code = dict(
        evaluator_py=sha(JS / 'evaluator.py'),
        fault30_run_py=sha(ROOT / 'collab_scheduler_v1/fault30_run.py'),
        scoring_contract_final_py=sha(JS / 'scoring_contract_final.py'),
        gold_contract_v1=gold_contract_sha,
        note='CURRENT FILE hashes only; NOT proof of loaded execution version. Rescore uses current score_v21; recorded scoring version remains UNVERIFIED')

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
            e['ledger'].setdefault('unknown_spend', False)
            e['ledger']['unknown_spend'] |= not (sdir / 'DISPATCH.jsonl').exists()
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
        # Missing stored field is unknown; persisted null is a parsed failure.
        rescore = []
        for ev in e['evals']:
            stored_tasks = {t['uid']: t for t in ev.get('tasks', [])}
            missing = [u for u in executed_uids
                       if u not in stored_tasks or 'final_value' not in stored_tasks[u]
                       or v21g[u]['gold'] is None]
            old = new = None
            if not missing:
                old = sum(int(close_v1(stored_tasks[u]['final_value'], gold_v1[u]))
                          for u in executed_uids) / len(executed_uids)
                new = sum(int(score_v21(stored_tasks[u]['final_value'], v21g[u]['gold']))
                          for u in executed_uids) / len(executed_uids)
            rescore.append(dict(cid=ev['config_id'], state=ev['state'],
                Q_recorded=ev['objectives']['Q'], Q_close_v1=old, Q_v21=new,
                status='UNSCORABLE' if missing else 'RESCORED', missing_uids=missing))
        flips = [r for r in rescore if r['Q_v21'] is not None
                 and abs(r['Q_v21'] - r['Q_recorded']) > 1e-9]
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
                         executed_contract='UNVERIFIED: protocol close vs production score_v21 mismatch',
                         execution_hash_status='NOT_PROVEN_BY_CURRENT_SOURCE',
                         selector_observation_trace_status='NOT_VERIFIED'),
            search_physical=dict(
                requests_ledger=e['ledger']['reserved'],
                responses_settled=e['ledger']['response'],
                unresolved_attempts=max(0,e['ledger']['reserved']-e['ledger']['response']),
                spend_status='UNKNOWN' if e['ledger']['unknown_spend'] else 'RECORDED_LOWER_BOUND',
                tokens_ledger=e['ledger']['tokens'],
                wall_reported=round(st.get('observed_wall_s', 0)),
                model_switch_wall=round(e.get('switch_wall', 0)),
                ledger_proofs=e['ledger']['proofs']),
            rescore_v21=dict(n_evaluations=len(rescore), flips=len(flips),
                             unscorable_evaluations=sum(r['status']=='UNSCORABLE' for r in rescore),
                             mergeable_across_contracts=False,
                             note='Zero flips cannot establish execution-version or selector-observation equivalence',
                             detail=rescore),
            deployment=per_state)

    n_cells = len(recon_sessions)
    n_complete = sum(1 for s in recon_sessions.values() if s['status'] == 'COMPLETE')
    total_req = sum(s['search_physical']['requests_ledger'] for s in recon_sessions.values())
    total_tok = sum(s['search_physical']['tokens_ledger'] for s in recon_sessions.values())

    out = dict(
        campaign_status='DIAGNOSTIC — automation complete != formal admission; '
                        'scoring contract not yet frozen into execution path',
        current_source_hashes=scoring_code,
        panel_identity=panel_identity,
        gold_v21_for_executed_panel={u: dict(gold=v21g[u]['gold'],
                                             source=v21g[u]['gold_source'])
                                     for u in executed_uids},
        closure_checks=dict(
            A_scoring='per-session hashes + Q_recorded vs Q_v2.1 re-score; '
                      'no cross-contract merge without runtime version and selector observation proof',
            B_quota='ledger-proven only (DISPATCH reserve/response events); '
                    'missing ledgers imply UNKNOWN spend, not zero; '
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
                 'Live snapshot: counters may advance during reading',
                 'Missing dispatch ledgers imply unknown spend; totals are lower bounds',
                 'Current-source hashes are not execution-time hashes',
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
