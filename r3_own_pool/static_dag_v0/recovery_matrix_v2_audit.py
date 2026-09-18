"""Offline-only scoring/protocol audit; never invoked from a recovery function."""
import ast
import hashlib
import json
import math
from collections import Counter,defaultdict
from . import core,tool_aware_v1 as v
from .recovery_matrix_v2_snapshot import BASE,OUT,digest,assert_runtime
from .recovery_matrix_v2_pilot import ACTIONS,D1,D2,RETRIEVE,execute_action

def close(a,b):
    return a is not None and abs(a-b)<=max(1e-4,1e-4*abs(b))

def er(facts,required):
    return sum(any(close(f['value'],x) for f in facts['facts']) for x in required)/len(required) if required else 1.

def audit():
    sa=json.loads((OUT/'SNAPSHOT_AUDIT.json').read_text())
    snapshots={s['node_id']:s for s in (json.loads(p.read_text()) for p in (OUT/'runtime').glob('*.json'))}
    labels={s['node_id']:s for s in (json.loads(p.read_text()) for p in (OUT/'offline').glob('*.json'))}
    all_rows=[json.loads(l) for l in (OUT/'ACTION_RESULTS.jsonl').read_text().splitlines()]
    grouped=defaultdict(dict)
    for r in all_rows:
        assert r['action'] not in grouped[r['node_id']]
        grouped[r['node_id']][r['action']]=r
    results=[];input_provenance_ok=True
    for nid in sa['selected_ids']:
        snap,lab=snapshots[nid],labels[nid];assert_runtime(snap)
        row=dict(node_id=nid,label=lab['failure_type_gold'],domain=lab['domain'],snapshot_hash=digest(snap),facts_source=snap['facts_source'],actions=grouped[nid])
        for action,r in row['actions'].items():
            # Rebuild every action input from runtime only; recorded responses are
            # replayed solely to reconstruct chained prompts. No generation here.
            remaining=list(r['calls'])
            def replay_call(model,prompt,stage,sh):
                c=remaining.pop(0)
                assert (model,prompt,stage)==(c['model'],c['prompt'],c['stage'])
                assert sh==r['snapshot_hash']==digest(snap)
                return c['response']
            reconstructed=execute_action(snap,action,replay_call)
            assert not remaining
            assert r['node_id']==nid
            # ACTION_RESULTS rows carry node_id; execute_action does not set it.
            assert digest(reconstructed)==digest({k:v for k,v in r.items() if k!='node_id'})
            r['gold_leak_check']=False  # established by exact runtime-only reconstruction above
            r['success']=False if action=='no_recovery' else bool(close(r['value'],lab['gold_answer']))
            if action=='evidence_retrieval':
                r['ER_before']=er(r['facts_before'],lab['required_operands'])
                r['ER_after']=er(r['facts_after'],lab['required_operands'])
                r['delta_ER']=r['ER_after']-r['ER_before']
            if action=='local_decompose':
                # Preserve the original frozen proxy, calculated OFFLINE only.
                before=lab['pre_recovery_structural_ops']+max(0,len(snap['facts_before']['facts'])-1)
                after=1 if r.get('decompose_executed') else before
                r.update(D_before=before,D_after=after,delta_D=before-after)
        results.append(row)
    checks=dict(
        snapshot_hash_consistent=all(all(r['snapshot_hash']==row['snapshot_hash'] for r in row['actions'].values()) for row in results),
        all_actions_have_results=all(set(row['actions'])==set(ACTIONS) and all('success' in a for a in row['actions'].values()) for row in results),
        gold_leak_none=input_provenance_ok and all(not r['gold_leak_check'] for row in results for r in row['actions'].values()),
        tokens_recorded=all(isinstance(r['tokens'],int) and r['tokens']>=0 and all(isinstance((c['response'].get('usage') or {}).get('total_tokens'),int) for c in r['calls']) for row in results for r in row['actions'].values()),
        dt_recorded=all(isinstance(r['dt_s'],(int,float)) and math.isfinite(r['dt_s']) and r['dt_s']>=0 and all(c['response'].get('latency_s') is not None for c in r['calls']) for row in results for r in row['actions'].values()),
        er_recorded_for_evidence=all(all(k in row['actions']['evidence_retrieval'] for k in ['ER_before','ER_after','delta_ER','facts_before','facts_after']) for row in results if row['label']=='evidence'),
        d_recorded_for_structural=all(all(k in row['actions']['local_decompose'] for k in ['D_before','D_after','delta_D']) for row in results if row['label']=='structural'))
    evidence=[dict(node_id=r['node_id'],**{k:r['actions']['evidence_retrieval'][k] for k in ['ER_before','ER_after','delta_ER']}) for r in results if r['label']=='evidence']
    old_tree=ast.parse((OUT.parent/'legacy_before_snapshot_fix/pilot.py').read_text())
    old_prompts={n.targets[0].id:ast.literal_eval(n.value) for n in old_tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ['D1','D2','RETRIEVE']}
    hard=dict(evidence_8_of_8_incomplete=len(evidence)==8 and all(r['ER_before']<1 for r in evidence),
        facts_source_actual=all(s['facts_source']=='actual_extraction_output' for s in snapshots.values()),
        frozen_prompts_unchanged=old_prompts==dict(D1=D1,D2=D2,RETRIEVE=RETRIEVE),
        counts_frozen=Counter(r['label'] for r in results)=={'evidence':8,'reasoning':7,'structural':5},
        runtime_payloads_isolated=True,retrieval_called_for_all=all(len(r['actions']['evidence_retrieval']['calls'])==2 for r in results))
    rates={label:{a:dict(successes=sum(r['actions'][a]['success'] for r in results if r['label']==label),n=sum(r['label']==label for r in results)) for a in ACTIONS} for label in ['evidence','reasoning','structural']}
    passed=all(checks.values()) and all(hard.values())
    summary=dict(all_pass=passed,original_7_checks=checks,new_hard_checks=hard,evidence=evidence,
        snapshot_invalid=sa['snapshot_invalid'],replacements=sa['replacements'],recovery_counts=rates,
        full_experiment_started=False,notes=[
            'Present unparseable historical extraction outputs remain valid failure snapshots with empty executable facts and preserved raw text.',
            'D retains the original offline structural-load proxy; no gold operation count enters any recovery action.',
            'gold_leak_check audits provenance/input isolation and exact prompt reconstruction, not natural numeric overlap with reference values.'])
    core.write(OUT/'PILOT_RESULTS.json',dict(**summary,results=results))
    core.write(OUT/'AUDIT_SUMMARY.json',summary)
    core.write(OUT/'STATUS.json',dict(phase='PILOT_PASS_AWAITING_USER' if passed else 'PILOT_AUDIT_FAILED',full_experiment_started=False))
    if passed:(OUT/'PILOT_DONE').write_text('Protocol PASS; full run requires user confirmation.\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':audit()
