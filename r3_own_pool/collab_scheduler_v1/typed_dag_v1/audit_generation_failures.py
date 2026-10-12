"""Read-only, per-response failure attribution from preserved real artifacts."""
import json,re
from pathlib import Path
from .protocol import CONTRACTS

def audit(base):
    cases=[]
    for directory in sorted(base.glob('stage3_real_smoke_*')):
        path=directory/'TRAJECTORY.jsonl'
        if not path.exists():
            events=directory/'GENERATION_EVENTS.jsonl'
            if events.exists():cases.append(dict(run=directory.name,category='SERVICE_ABORT_NOT_DAG_SAMPLE',events=[json.loads(l) for l in events.read_text().splitlines()],http_root_cause='HTTP500 observed; error body not retained in old runner, exact server cause unproven'))
            continue
        for line_number,line in enumerate(path.read_text().splitlines(),1):
            row=json.loads(line)
            if not row['key'].startswith('typed:generate:') or ':semantic_review:' in row['key']:continue
            answer=row['response']['answer'];text=answer.strip();issues=[]
            if text.startswith('```') and text.endswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
            try:obj=json.loads(text)
            except ValueError:obj=None;issues.append(dict(code='JSON_FORMAT',field='root'))
            if isinstance(obj,dict) and 'graph_format' in obj:
                issues.append(dict(code='ROOT_WRAPPER',field='graph_format'));obj=obj['graph_format'] # diagnostic only, no executable repair
            if isinstance(obj,dict) and isinstance(obj.get('nodes'),list):
                by={n.get('node_id'):n for n in obj['nodes']}
                for n in obj['nodes']:
                    u=n.get('node_id');cid=n.get('output_contract');c=CONTRACTS.get(cid);deps=n.get('dependencies',[]);bindings=n.get('inputs',[])
                    if c is None:issues.append(dict(code='UNKNOWN_CONTRACT',node_id=u,actual=cid));continue
                    if n.get('node_type')!=c[0]:issues.append(dict(code='CONTRACT_TYPE',node_id=u,expected=c[0],actual=n.get('node_type')))
                    missing=set(c[1])-{b.get('port') for b in bindings}
                    if missing:issues.append(dict(code='MISSING_INPUT',node_id=u,expected=sorted(missing)))
                    for b in bindings:
                        if b.get('port') not in c[1]:issues.append(dict(code='UNKNOWN_INPUT_PORT',node_id=u,actual=b.get('port')))
                        if b.get('source')=='node':
                            source=b.get('node_id')
                            if source not in deps:issues.append(dict(code='BINDING_DEPENDENCY',node_id=u,source=source,deps=deps))
                            if source not in by:issues.append(dict(code='SOURCE_REFERENCE',node_id=u,source=source))
                            elif by[source].get('output_contract') in CONTRACTS and b.get('field') not in CONTRACTS[by[source]['output_contract']][2]:issues.append(dict(code='OUTPUT_PORT',node_id=u,source=source,actual=b.get('field')))
                    for dep in deps:
                        if dep not in by:issues.append(dict(code='DEPENDENCY_REFERENCE',node_id=u,actual=dep))
            cases.append(dict(run=directory.name,trajectory_line=line_number,key=row['key'],finish_reason=row['response'].get('finish_reason'),truncated=row['response'].get('finish_reason')=='length',issues=issues,response=answer,answer_sha=__import__('hashlib').sha256(answer.encode()).hexdigest(),semantic_coverage='NOT_REACHED'))
    return cases
if __name__=='__main__':
    base=Path(__file__).parent;data=audit(base);(base/'STAGE3_REPAIR_FAILURE_AUDIT.json').write_text(json.dumps(data,indent=2));print('audited',len(data),'responses/aborts')
