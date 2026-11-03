"""Read-only, zero-network package checks. No API sender or scheduler execution."""
import json,hashlib,pathlib,sys
B=pathlib.Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def check():
 p=json.loads((B/'PROTOCOL.json').read_text());checks=[]
 def record(name,ok):checks.append({'name':name,'pass':bool(ok)})
 record('algorithm hashes unchanged',all(sha(k)==v for k,v in p['algorithm_sha256'].items()))
 record('historical reference and source hashes unchanged',all(sha(k)==v for k,v in p['source_sha256'].items()))
 record('exactly eight controlled states',len(p['scenarios'])==8 and all(r['data_class'].startswith('CONTROLLED') for r in p['scenarios']))
 for r in p['scenarios']:
  for n in (1,2):
   a=B/'paired_states'/f"{r['scenario_id']}_r{n}_V5.json";b=B/'paired_states'/f"{r['scenario_id']}_r{n}_RL.json"
   record(f"{r['scenario_id']} repeat{n}: identical independent pre-action copies",a!=b and a.read_bytes()==b.read_bytes() and sha(a)==r['state_sha256'])
 record('20 request upper includes all recoveries',sum(r['request_cap_per_arm_execution']*len(r['arms'])*r['paired_repeats'] for r in p['scenarios'])==p['matrix']['physical_request_upper']==20)
 record('output ceiling is 20*1024',p['matrix']['total_output_limit']==20480)
 record('no synthetic outcomes or chosen actions supplied',all(r['actual_future_outputs'] is None and r['V5_selected'] is None and r['RL_selected'] is None and r['actual_QCL_difference'] is None for r in p['scenarios']))
 record('zero budget preserved',p['scenarios'][4]['state']['remaining_resources']['token_ceiling']==0)
 record('zero deadline preserved',p['scenarios'][5]['state']['remaining_resources']['deadline_seconds']==0)
 record('both models unavailable preserved',not any(p['scenarios'][6]['state']['availability'].values()))
 record('unknown quality hard gate preserved',p['scenarios'][7]['state']['terminal_q_min']==1.0 and p['scenarios'][7]['state']['terminal_quality_predictor'] is None)
 result={'package_integrity':'PASS' if all(x['pass'] for x in checks) else 'FAIL','checks':checks,'paid_execution':'HOLD','model_requests_sent':0,'remaining_gates':p['execution_gates'],'note':'Package integrity only. No mechanism execution, prediction calibration, real outcome or paid readiness demonstrated.'}
 return result
if __name__=='__main__':
 if len(sys.argv)>1:raise SystemExit('Only read-only preflight is supported. No execute/network mode exists.')
 r=check();print(json.dumps(r,ensure_ascii=False,indent=2));sys.exit(0 if r['package_integrity']=='PASS' else 1)
