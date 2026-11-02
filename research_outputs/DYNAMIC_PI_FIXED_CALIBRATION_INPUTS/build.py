"""Offline export of real committed calibration inputs; no dispatch capability."""
import json, hashlib
from pathlib import Path
OUT=Path(__file__).resolve().parent
RUN=Path('/root/research_outputs/DYNAMIC_PI_DEV_EXPLORATION_RUN')
DAG=Path('/root/research_outputs/DYNAMIC_PI_DEV_EXPLORATION/calibration/DAG.json')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def match_input(node,payload,cache):
    if payload['node_id']!=node['node_id'] or payload['contract']!=node['output_contract']:
        raise ValueError('CONTRACT_MISMATCH')
    expected={}
    for port in node['inputs']:
        if port['source']!='node':continue
        source=cache[port['node_id']]
        if source['commit'] is not True:raise ValueError('UNCOMMITTED_UPSTREAM')
        val=source['output'][port['port']]
        field=port['field']
        if field in expected:
            if not isinstance(val,list) or not isinstance(expected[field],list):raise ValueError('AMBIGUOUS_INPUT_MERGE')
            expected[field]=expected[field]+val
        else:expected[field]=val
    for field,value in expected.items():
        if payload['input'].get(field)!=value:raise ValueError('UPSTREAM_INPUT_MISMATCH:'+field)
    return expected

def main():
    rawpath=RUN/'cal_1.RAW.json';raw=json.loads(rawpath.read_text());dag=json.loads(DAG.read_text())
    sources={str(rawpath):sha(rawpath),str(DAG):sha(DAG)};items=[]
    for node in dag['nodes']:
        if node['node_id'] not in ('timeline_1','relations_1','verify_1','report_1'):continue
        reqpath=RUN/'requests'/('cal_1__'+node['node_id'])/'REQUEST.json'
        sources[str(reqpath)]=sha(reqpath)
        request=json.loads(reqpath.read_text());content=request['messages'][0]['content']
        payload=json.loads(content[content.index('\n')+1:])
        match_input(node,payload,raw['cache'])
        fixture={'node_id':node['node_id'],'contract':node['output_contract'],
                 'input':payload['input'],'output_schema':payload['schema'],
                 'upstream_provenance':[{'node_id':d,'commit_id':raw['cache'][d]['commit_id'],
                    'model':raw['cache'][d]['model'],'historical_commit':raw['cache'][d]['commit'],
                    'semantic_quality':'UNKNOWN'} for d in node['dependencies']],
                 'source_request':str(reqpath),'source_request_sha256':sha(reqpath),
                 'purpose':'FIXED_INPUT_CONDITIONAL_NODE_CALIBRATION_NOT_END_TO_END',
                 'new_model_observations':None,'reference_quality':'PENDING',
                 'dispatch_authorized':False}
        path=OUT/(node['node_id']+'.json');path.write_text(json.dumps(fixture,ensure_ascii=False,indent=2))
        items.append({'node_id':node['node_id'],'file':path.name,'sha256':sha(path)})
    assert all(sha(Path(p))==s for p,s in sources.items())
    (OUT/'MANIFEST.json').write_text(json.dumps({'fixtures':items,'source_hashes':sources,'source_files_unchanged':True,'new_calls':0,'upstream_generator':'deepseek-flash','limitations':['Shared machine-generated inputs; not Gold','Measures conditional node performance, not upstream robustness','No target output or scores exported','Requires separately authorized new batch; old authorization closed']},ensure_ascii=False,indent=2))
    print(json.dumps(items))
if __name__=='__main__':main()
