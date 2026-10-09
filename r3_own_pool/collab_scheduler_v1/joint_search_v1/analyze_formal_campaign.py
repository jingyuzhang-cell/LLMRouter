"""Zero-call descriptive analysis of the formal search campaign (V2).

Reads all formal_campaign_v2* roots; tolerates partial/incomplete sessions.
DESCRIPTIVE ONLY per review boundary: presents per-session status, budget
usage, selection counts, and per-state Q/C/L of evaluated configs. No
method-superiority claim, no TEST16 release, no winner declaration until all
18 cells COMPLETE and comparisons are made on common budget support.

Excludes the V1 diagnostic session (old gold) by construction (it lives in
formal_campaign/, not formal_campaign_v2*).
"""
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
JS = ROOT / 'collab_scheduler_v1/joint_search_v1'

METHOD_LABELS = {
    'proposed_state_incremental': 'Proposed (state+incremental-cost)',
    'random': 'Random',
    'scalarized_bo': 'Scalarized BO',
    'official_qnehvi_same_state': 'qNEHVI (official BoTorch)',
    'proposed_without_state': 'Ablation: w/o state features',
    'proposed_without_incremental_cost': 'Ablation: w/o incremental-cost divisor',
}


def load_sessions():
    sessions = {}
    for root in sorted(JS.glob('formal_campaign_v2*')):
        if not root.is_dir():
            continue
        for sdir in sorted(root.glob('*_2026*')):
            if not sdir.is_dir():
                continue
            sid = sdir.name
            entry = sessions.setdefault(sid, dict(dirs=[], evals=[]))
            entry['dirs'].append(str(sdir))
            evf = sdir / 'EVALUATIONS.jsonl'
            if evf.exists():
                entry['evals'].extend(json.loads(l) for l in evf.read_text().splitlines())
            stf = sdir / 'STATUS.jsonl'
            if stf.exists():
                entry['status'] = json.loads(stf.read_text().splitlines()[-1])
    return sessions


def main():
    sessions = load_sessions()
    out = dict(generated=str(Path.cwd()), sessions={}, totals={}, caveats=[
        'DESCRIPTIVE ONLY — no superiority claim until all 18 cells COMPLETE',
        'comparisons must use common budget support (min per-session requests '
        'or configs across methods)',
        'V1 diagnostic session excluded (old gold); TEST16 not released'])
    total_req = total_tok = 0
    n_complete = n_cells = 0
    for sid, entry in sorted(sessions.items()):
        method, seed = sid.rsplit('_', 1)
        evs = entry['evals']
        per_state = {}
        for st in ('clean', 'fault30'):
            sel = [e for e in evs if e['state'] == st]
            if sel:
                per_state[st] = dict(
                    n_configs=len(sel),
                    Q_values=[round(e['objectives']['Q'], 3) for e in sel],
                    C_values=[int(e['objectives']['C']) for e in sel],
                    best_Q=max(e['objectives']['Q'] for e in sel))
        status = entry.get('status', {}).get('status', 'RUNNING/UNKNOWN')
        req = entry.get('status', {}).get('new_requests')
        if status == 'COMPLETE':
            n_complete += 1
        n_cells += 1
        total_req += req or 0
        total_tok += entry.get('status', {}).get('tokens_known') or 0
        out['sessions'][sid] = dict(
            method=method, label=METHOD_LABELS.get(method, method), seed=int(seed),
            status=status, dirs=entry['dirs'], n_evaluations=len(evs),
            requests=req, per_state=per_state)
    out['totals'] = dict(cells_seen=n_cells, complete=n_complete,
                         requests_settled=total_req, tokens_settled=total_tok,
                         campaign_ceiling_requests=6901,
                         note='plus v1 diagnostic 299 requests charged to the '
                              'frozen 7,200 envelope')
    (JS / 'FORMAL_CAMPAIGN_ANALYSIS.json').write_text(json.dumps(out, indent=1))
    # console digest
    print(json.dumps(out['totals']))
    for sid, s in out['sessions'].items():
        cq = s['per_state'].get('clean', {}).get('best_Q')
        fq = s['per_state'].get('fault30', {}).get('best_Q')
        print(f"{sid[:36]:38} {s['status'][:12]:13} evals={s['n_evaluations']:2} "
              f"req={s['requests']!s:4} bestQ clean={cq} fault30={fq}")
    return out


if __name__ == '__main__':
    main()
