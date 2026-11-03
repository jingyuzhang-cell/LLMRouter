"""Offline ledger/structure audit; never calls model or reads silver answers."""
import json,hashlib,shutil
from pathlib import Path
import semantic_plan as SP,assemble_dag as AD
from v3_kdx_resource_aware import KDX_DOCS,feasibility
root=Path('/root/capital_opinion_pilot/v5_final_acceptance_20261022_v1/isolated');out=Path('/tmp/kdx_audit_dir').read_text().strip();out=Path(out)
def save(name,obj):(out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def analyse(p):
 rows=p['plan'];by={r['id']:r for r in rows};reports=[r['id'] for r in rows if r['kind']=='report'];active=set()
 def walk(u):
  if u in active or u not in by:return
  active.add(u)
  for v in by[u].get('depends',[]):walk(v)
 for u in reports:walk(u)
 docs={r['id']:set(r.get('doc_ids',[])) for r in rows if r['kind'] in ('extracts','extracts_f')};issues=SP.validate_plan(p,KDX_DOCS);gv,errors=AD.assemble(p,task_id="kdx_002450_resource_planning_v3")
 overlaps=[{'nodes':[a,b],'overlap_docs':sorted(docs[a]&docs[b]),'meaning':'Shared document scope, not proof of redundant investigation'} for i,a in enumerate(docs) for b in list(docs)[i+1:] if docs[a]&docs[b]]
 result={'plan':p,'semantic_validation':issues,'typed_validation':errors,'status':'STRUCTURE_VALID' if gv is not None and not issues and not errors else 'INVALID','dead_nodes':sorted(set(by)-active),'planned_docs':sorted(set().union(*docs.values())) if docs else [],'final_chain_docs':sorted(set().union(*(ds for n,ds in docs.items() if n in active))) if any(n in active for n in docs) else [],'overlap_risk':overlaps,'edges':[{'producer':d,'consumer':r['id']} for r in rows for d in r.get('depends',[])],'feasibility':feasibility({'plan':p}),'missing_necessary_information':'NOT_ESTABLISHED_BY_STRUCTURE','execution':'NOT_RUN','node_feasibility':[{ 'node':r['id'],'kind':r['kind'],'known_tools':'Original execute_v2 main is wired to a different task/evidence set; new merge program adapter tested independently; whole KDX adapter not executed','retrieval_strategy':'DECLARED_SEGMENTED' if any(s in r['goal'] for s in ['分段','定位','检索','窗口']) else 'NOT_EXPLICIT','context_semantics':'3300 characters is direct-injection limit; full document coverage and downstream input sizes unverified'} for r in rows]}
 if gv:
  g,v=gv;result.update(graph=g.to_dict(),layers=[list(l) for l in v.layers],critical_path_node_count=len(v.layers),max_layer_parallel_width=max(map(len,v.layers)),parallelism_kind='Topological layer width, not measured concurrency or maximum antichain',contracts=[{'node':n.node_id,'contract':n.output_contract,'inputs':[b.__dict__ for b in n.inputs],'dependencies':n.dependencies} for n in g.nodes])
 return result
orig={}
for arm in ['A','B']:
 f=json.loads((root/'v3_kdxra_frozen'/f'arm_{arm}_original.json').read_text());orig[arm]=analyse(SP.parse_plan(f['raw_response']));save(arm+'_ORIGINAL_AUDIT.json',orig[arm])
entries=json.loads((root/'v3_kdx_repair.json').read_text())['arms'];repaired={}
for e in entries:
 arm=e['arm']
 try:
  if arm=='B':raise ValueError('Provider finish_reason=max_tokens; response truncated, not a complete repaired plan')
  p=SP.parse_plan(e['raw_response']);r=analyse(p)
 except Exception as x:r={'status':'INVALID','graph':None,'error':str(x),'raw_response':e['raw_response'],'execution':'NOT_RUN'}
 repaired[arm]=r;save(arm+'_REPAIRED_DAG.json',r);save(arm+'_STRUCTURE_AUDIT.json',{'before':orig[arm],'after':r})
ledger=[json.loads(l) for l in (root/'model_call_ledger_v3kdxrepair.jsonl').read_text().splitlines() if l.strip()];actual=sum(x['usage']['input_tokens']+x['usage']['output_tokens'] for x in ledger)
save('BUDGET_AUDIT.json',{'requests_existing':len(ledger),'requests_this_audit':0,'actual_tokens':actual,'authorized_cap':4000,'overrun':actual-4000,'inflight_unknown_reserve':'No surviving reservation journal; no new dispatch allowed','root_cause':'Snapshot Meter checked 1.5*max_output only and omitted prompt input; no persistent pre-dispatch reserve event. Existing second call 1970+1486+640=4096 should have been blocked with trustworthy input bound. New pure gate rejects unknown bounds; current parallel Meter character estimate is not a proven bound.','claims':'Historical A repaired before new v2 contract changes; not success of new contract. B INVALID. No further calls.'})
for log,name in [('/tmp/kdx_v2_tests.log','NEW_TESTS.log'),('/tmp/kdx_old_tests.log','OLD_CONTRACT_TESTS.log'),('/tmp/kdx_meter_tests.log','METER_TESTS.log'),('/tmp/kdx_dry_tests.log','DRY_TESTS.log')]:shutil.copy(log,out/name)
save('CURRENT_CODE_HASHES.json',{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [root/n for n in ['pilot_dag_contracts.py','semantic_plan.py','assemble_dag.py','merge_contract_v2.py','repair_budget_gate.py','test_merge_contract_v2.py','pilot_common.py']]})
print(json.dumps({'dir':str(out),'A':repaired['A']['status'],'B':repaired['B']['status'],'actual_tokens':actual,'A_depth':repaired['A'].get('critical_path_node_count'),'A_width':repaired['A'].get('max_layer_parallel_width')},ensure_ascii=False))
