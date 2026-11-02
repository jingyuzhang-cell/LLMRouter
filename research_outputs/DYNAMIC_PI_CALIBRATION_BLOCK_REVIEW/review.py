import json,hashlib,sys,socket,ssl
from pathlib import Path
from admission import assess
socket.socket=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('NETWORK_FORBIDDEN'))
ROOT=Path('/root/research_outputs/DYNAMIC_PI_DEV_EXPLORATION')
RUN=Path('/root/research_outputs/DYNAMIC_PI_DEV_EXPLORATION_RUN')
OUT=Path(__file__).resolve().parent
paths=[RUN/'requests/cal_0__extract_1/RESPONSE.bin',RUN/'requests/cal_0__extract_1/REQUEST.json',RUN/'cal_0.RAW.json',RUN/'CALIBRATION.json',RUN/'RESULT.json',ROOT/'runner/batch.py',ROOT/'evaluation/DAG.json',ROOT/'RUNNER_LOCK.json']
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
sys.path.insert(0,'/root/.worktrees/codex-dd-v51-six-arm/dynamic_pi_binding_20261030')
import binding as B
response=json.loads(paths[0].read_text());payload=json.loads(response['choices'][0]['message']['content'])
expected=set(B.bridge.CONTRACTS['capital.extract.v1'][2]);actual=set(payload)
schema_check={'expected_top_level':sorted(expected),'observed_top_level':sorted(actual),'matches_frozen_schema':actual==expected,'extra_wrapper_previously_allowed':False,'original_K':json.loads(paths[2].read_text())['trace'][-1]['verdict']['K'],'unwrapped_for_execution':False,'historical_result_changed':False}
graph=json.loads((ROOT/'evaluation/DAG.json').read_text());config=json.loads((ROOT/'EXPERIMENT_CONFIG.json').read_text())
report=assess(graph['nodes'],[m['request_model'] for m in config['models']],json.loads((RUN/'CALIBRATION.json').read_text()),['timeline','relations','verify','report'])
result={'schema_review':schema_check,'revised_admission_on_real_saved_measurements':report,'new_model_calls':0,'new_quality_scores':None,'old_batch':'CLOSED_UNCHANGED','interpretation':'Missing Qwen downstream profiles are real missing measurements; allowing partial matrices does not create a second remaining allocation. Do not spend further evaluation calls on this state as a Dynamic-Pi benefit test.'}
assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
result['read_files_sha256_unchanged']=before
with (OUT/'REVIEW_RESULT.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps({'schema_pass':schema_check['matches_frozen_schema'],'admission':report['decision'],'remaining_assignments':report['remaining_assignment_count'],'new_calls':0},ensure_ascii=False))
