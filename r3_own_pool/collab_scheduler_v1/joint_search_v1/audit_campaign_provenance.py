"""Read-only campaign evidence audit; never dispatches model requests."""
import hashlib,json,datetime
from pathlib import Path
JS=Path(__file__).resolve().parent
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p):
    if not p.exists(): return []
    out=[]
    for line in p.read_text().splitlines():
        try: out.append(json.loads(line))
        except json.JSONDecodeError: pass # concurrent append: incomplete line is not evidence
    return out
def main():
    admission=json.loads((JS/'FORMAL_ADMISSION_V2.json').read_text())
    launch=json.loads((JS/'FORMAL_LAUNCH_V2.json').read_text())
    bindings=[]
    for name,want in admission['bindings'].items():
        p=Path(name); got=digest(p) if p.exists() else None
        bindings.append(dict(path=name,expected=want,current=got,matches=got==want))
    sessions=[]
    for root in sorted(JS.glob('formal_campaign_v2*')):
        if not root.is_dir(): continue
        for d in sorted(root.glob('*_2026*')):
            if not d.is_dir(): continue
            panel=rows(d/'TASK_PANEL.jsonl'); evs=rows(d/'EVALUATIONS.jsonl'); st=rows(d/'STATUS.jsonl')
            panel_ok=bool(panel) and panel[-1]==launch['tasks']
            means_ok=all(abs(e['objectives']['Q']-sum(t['Q'] for t in e['tasks'])/len(e['tasks']))<1e-12 for e in evs if e.get('tasks'))
            sessions.append(dict(directory=str(d),evaluations=len(evs),status=st[-1] if st else None,
                panel_matches_launch=panel_ok,recorded_Q_matches_task_mean=means_ok,
                runtime_source_snapshot_status='NOT_FOUND: protocol/task snapshots are not loaded-source snapshots',
                selector_observation_status='SOURCE_PATH_PRESENT; actual ingestion trace not persisted',
                missing_dispatch=(not (d/'DISPATCH.jsonl').exists()),
                spending_rule='Missing ledger leaves spend UNKNOWN; do not release reservation based on absence alone'))
    score_source=(JS/'scoring_contract_final.py').read_text()
    result=dict(snapshot_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        diagnostic_only=True,zero_model_calls=True,current_bindings=bindings,
        unbound_scoring_dependencies=[str(JS/'scoring_contract_final.py'),str(JS/'task_contract_v2.py')],
        rounding_source_current='round(fa, 2) == round(fb, 2)' in score_source,
        current_source_is_not_runtime_proof=True,sessions=sessions,
        admission='NOT_CLOSED: execution version and selector ingestion need contemporaneous evidence')
    (JS/'CAMPAIGN_PROVENANCE_AUDIT.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(dict(sessions=len(sessions),binding_mismatches=sum(not b['matches'] for b in bindings),rounding_source_current=result['rounding_source_current'])))
    return result
if __name__=='__main__': main()
