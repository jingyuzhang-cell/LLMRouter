"""Read-only historical cell replay. No network/credential/paid-dispatch implementation.
Normal missing or failed measurements do not block independent cells.
"""
import json,hashlib,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RUN=Path('/root/research_outputs/DYNAMIC_PI_DEV_EXPLORATION_RUN')
MODELS=('qwen-plus-2025-12-01','deepseek-flash')
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def execute_cells(cells,worker,*,max_cells,wall_seconds):
    started=time.monotonic();rows=[];stop=None
    for cell in cells:
        if len(rows)>=max_cells:stop='CELL_LIMIT';break
        if time.monotonic()-started>=wall_seconds:stop='WALL_LIMIT';break
        try:
            row=worker(cell)
            if row['status'] not in ('MISSING','OBSERVED_COMMITTED','OBSERVED_MODEL_FAILURE'):
                raise ValueError('INVALID_CELL_STATUS')
            rows.append(row)
        except Exception as exc:
            rows.append(dict(cell=cell,status='SYSTEM_ERROR',error=type(exc).__name__+': '+str(exc)))
            stop='SYSTEM_ERROR';break
    return dict(rows=rows,stop=stop,new_model_calls=0,evidence='HISTORICAL_MEASUREMENT_REPLAY',
                live_dispatch_supported=False)

def replay():
    manifest=json.loads((ROOT/'MANIFEST.json').read_text())
    for path,expected in manifest['source_hashes'].items():
        if h(Path(path))!=expected:raise ValueError('HISTORICAL_SOURCE_CHANGED')
    raw=json.loads((RUN/'cal_1.RAW.json').read_text())
    fixtures={}
    for item in manifest['fixtures']:
        path=ROOT/item['file']
        if h(path)!=item['sha256']:raise ValueError('FIXTURE_CHANGED')
        fixtures[item['node_id']]=json.loads(path.read_text())
    cells=[dict(node=node,model=model) for node in fixtures for model in MODELS]
    def worker(cell):
        node,model=cell['node'],cell['model'];fixture=fixtures[node]
        matches=[c for c in raw['trace'] if c['node']==node and c['model']==model]
        if not matches:
            return dict(cell=cell,status='MISSING',Q=None,latency_s=None,usage=None,
                        reason='NO_SAVED_MATCHING_MODEL_NODE_INPUT_MEASUREMENT')
        if len(matches)!=1:raise ValueError('AMBIGUOUS_MEASUREMENT')
        c=matches[0];request=Path(fixture['source_request'])
        if h(request)!=fixture['source_request_sha256']:raise ValueError('REQUEST_CHANGED')
        req=json.loads(request.read_text());prompt=req['messages'][0]['content']
        payload=json.loads(prompt[prompt.index('\n')+1:])
        if req['model']!=model or payload['input']!=fixture['input']:
            raise ValueError('MEASUREMENT_INPUT_MISMATCH')
        response=request.parent/'RESPONSE.bin';resp=json.loads(response.read_bytes())
        if resp.get('model')!=model:raise ValueError('RESPONSE_MODEL_MISMATCH')
        if resp['usage']['total_tokens']!=c['usage']['tokens']:raise ValueError('USAGE_MISMATCH')
        return dict(cell=cell,status='OBSERVED_COMMITTED' if c['commit'] else 'OBSERVED_MODEL_FAILURE',
                    Q=None,E_structural=c['verdict'].get('E'),K=c['verdict'].get('K'),
                    semantic_quality='UNKNOWN',reliability_lower_bound=None,
                    latency_s=c['wall_s'],usage=c['usage'],actual_settlement=None,
                    cost_basis='HISTORICAL_ESTIMATE_NOT_ACCOUNT_SETTLEMENT',sample_count=1,
                    source_response=str(response),response_sha256=h(response),
                    input_fixture_sha256=h(ROOT/(node+'.json')),
                    same_input_replay_not_new_repeat=True)
    result=execute_cells(cells,worker,max_cells=len(cells),wall_seconds=30)
    result['profile_scope']='CONDITIONAL_ON_FIXED_DEEPSEEK_GENERATED_INPUTS_NOT_END_TO_END'
    result['remaining_missing_cells']=[r['cell'] for r in result['rows'] if r['status']=='MISSING']
    result['dynamic_pi_benefit']='NOT_EVALUATED'
    return result
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result=replay()
    with args.output.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'cells':len(result['rows']),'statuses':[r['status'] for r in result['rows']],'stop':result['stop'],'new_calls':0}))
