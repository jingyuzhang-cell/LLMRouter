"""Zero-call executable integration check; no scheduler chooser or network sender."""
import json,pathlib,hashlib
from numeric_binding import adapt_shared_state
B=pathlib.Path(__file__).resolve().parent
P=pathlib.Path('/root/capital_opinion_pilot/v5_rl_controlled_preregistration_v1')
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def main():
 protocol=json.loads((P/'PROTOCOL.json').read_text());manifest=json.loads((P/'MANIFEST.json').read_text())
 assert all(sha(p)==h for p,h in protocol['algorithm_sha256'].items())
 assert all(sha(p)==h for p,h in protocol['source_sha256'].items())
 assert all(sha(P/p)==h for p,h in manifest['files'].items())
 rows=[]
 for r in protocol['scenarios']:
  cid=r['scenario_id'];pairs=[]
  for repeat in [1,2]:
   a=json.loads((P/'paired_states'/f'{cid}_r{repeat}_V5.json').read_text());b=json.loads((P/'paired_states'/f'{cid}_r{repeat}_RL.json').read_text());ea,eb=adapt_shared_state(a),adapt_shared_state(b)
   assert ea==eb and ea['source_state_sha256']==r['state_sha256']
   roots=sorted(n for n,v in ea['contract_valid'].items() if not v)
   # Graph has only two independent model branches and deterministic terminal.
   # No optional model node lies outside roots with remaining soft evidence.
   pairs.append({'repeat':repeat,'same_effective_feedback':True,'hard_invalid_model_nodes':roots,'dependency_required_model_R':roots,'optional_evidenced_model_nodes_outside_R':[],'actual_V5_action':None,'actual_RL_action':None,'actual_outcomes':None})
  rows.append({'scenario_id':cid,'pairs':pairs,'structural_R_identifiability':'NO_ALTERNATIVE_MODEL_REEXEC_SCOPE_SUPPORTED','status':'STATIC_CONTRACT_DERIVATION_NOT_EXECUTION'})
 cells=json.loads((B/'HISTORICAL_CELLS.json').read_text())
 return {'status':'ADAPTER_CHECK_PASS_PAID_EXECUTION_HOLD_JOINT_SCOPE_STUDY_NO_GO','scenario_contract_audit':rows,'capability_cells':[{'node':c['node'],'model':c['model'],'n':c['n'],'status':c['status']} for c in cells['cells']],'research_boundary':'Current controlled matrix can at most investigate model assignment effects; it does not isolate independent Z/R joint scope benefits','remaining':['executor/transport counted sender not supplied','current account deployment/entitlement and enforceable cash cap not certified','tool-time reservation and future latency are not certified upper bounds','purchase/deepseek cell unidentified; do not fill from payable branch','no new experiment-specific paid authorization'],'model_api_calls':0,'V5_RL_decision_executions':0,'algorithm_and_preregistration_hashes_unchanged':True}
if __name__=='__main__':print(json.dumps(main(),ensure_ascii=False,indent=2))
