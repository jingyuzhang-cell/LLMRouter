"""Measured-profile integration; no dispatch, no synthetic feedback, no result mutation."""
import json,hashlib,sys,importlib.util,itertools
from pathlib import Path
from dataclasses import asdict
R=Path(__file__).resolve().parent
RUN=Path('/root/research_outputs/DYNAMIC_PI_FIXED_CALIBRATION_RUN')
FIX=Path('/root/research_outputs/DYNAMIC_PI_FIXED_CALIBRATION_INPUTS')
ENGINE=Path('/root/.worktrees/codex-dd-v51-six-arm/dd_v51_six_arm/engine.py')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('frozen_integration_engine',ENGINE)
engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
analysis=json.loads((RUN/'ANALYSIS.json').read_text());config=json.loads((FIX/'CALIBRATION_CONFIG.json').read_text())
dagfile=Path('/root/research_outputs/DYNAMIC_PI_DEV_EXPLORATION/calibration/DAG.json')
dag=json.loads(dagfile.read_text());models=[x['request_model'] for x in config['models']]
profile={};failures=[]
for row in analysis['rows']:
 if row['status']!='CONTRACT_COMMITTED':
  failures.append({'node':row['node'],'model':row['model'],'observed_failed_wall_s':row['wall_s'],'successful_completion_prediction':None,'reason':'Failure observation preserved; cannot substitute for successful completion latency.'});continue
 m=next(x for x in config['models'] if x['request_model']==row['model'])
 from decimal import Decimal,ROUND_CEILING
 micro=int((Decimal(16384)*Decimal(str(m['input_per_million']))+Decimal(3072)*Decimal(str(m['output_per_million']))).to_integral_value(rounding=ROUND_CEILING))
 profile[row['node'],row['model']]=engine.Profile(row['wall_s'],19456,micro if m['currency']=='CNY' else 0,micro if m['currency']=='USD' else 0,quality=None,reliability=None,evidence='ONE_REAL_CONDITIONAL_NODE_OBSERVATION_NOT_SUCCESS_GUARANTEE')
ids={n for n,m in profile};nodes=[engine.Node(n['node_id'],tuple(p for p in n['dependencies'] if p in ids),tuple(models)) for n in dag['nodes'] if n['node_id'] in ids]
engine.validate(nodes)
limits=engine.Limits({m:1 for m in models},600,180,4,4*19456,200000,100000)
chosen,audit=engine.choose(nodes,profile,limits,{})
plans=[]
for values in itertools.product(*(n.models for n in nodes)):
 pi=dict(zip((n.id for n in nodes),values))
 if any((n.id,pi[n.id]) not in profile for n in nodes):continue
 plans.append({'pi':pi,'predicted_makespan_s':engine.predict(nodes,pi,profile,limits.slots,{}),
               'evidence':'PREDICTION_FROM_CONDITIONAL_MEASUREMENTS_NOT_END_TO_END_REPLAY'})
# A report response is only reusable for byte-equivalent structured inputs.
actual=json.loads((RUN/'RESULT.json').read_text())['rows']
parents=['timeline_1','relations_1','verify_1'];findings=[]
for node in parents:
 row=next(x for x in actual if x['node']==node and x['model']=='deepseek-flash')
 findings.extend(row['output']['findings'])
old_report_input=json.loads((FIX/'report_1.json').read_text())['input']
new_report_input={**old_report_input,'findings':findings}
input_equal=new_report_input==old_report_input
out={'evidence':'OFFLINE_PROFILE_INTEGRATION_NOT_REAL_PAIRED_EXECUTION','source_hashes':{str(p):sha(p) for p in [ENGINE,dagfile,RUN/'ANALYSIS.json',RUN/'RESULT.json',FIX/'report_1.json']},
 'limits':asdict(limits),'failed_observations':failures,'plans':plans,'initial_pi':chosen,'initial_audit':audit,
 'feedback_snapshot':None,'feedback_status':'NO_REAL_PAIRED_EVALUATION_PREFIX_OR_FEEDBACK_COLLECTED',
 'dynamic_pi':None,'static_dynamic_effect':None,
 'report_response_reusable_after_new_upstreams':input_equal,
 'replay_status':'BLOCKED_INPUT_LINEAGE_MISMATCH' if not input_equal else 'INPUT_MATCHED_ONLY',
 'new_model_calls':0,'semantic_Q':None,
 'conclusion':'Two measured-supported prediction plans exist, but no current observed feedback justifies a dynamic comparison. Do not fabricate scale or splice mismatched report responses.'}
(R/'INTEGRATION_RESULT.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({'initial_pi':chosen,'plans':plans,'report_reusable':input_equal,'audit':audit},ensure_ascii=False))
