"""Train-only code scoring with audited local OS controls; no network calls."""
import argparse
import ast
from collections import Counter
import fcntl
import json
from pathlib import Path
import sys
import time
from .data import load_cohort,sha
from .core import SLOTS
from .score_available import digest,metrics
from .embed_queries import write_json
from .code_sandbox import RUNTIME,execute,verify_runtime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'collect'))
import storage


def program(source,response):
    code=metrics.extract_code(response.get('answer') or '')
    if source['dataset']=='mbpp':
        tests=json.loads(source['ground_truth'])
        if not isinstance(tests,list) or any(not isinstance(t,str) for t in tests):raise ValueError('Invalid MBPP tests')
        return code+'\n\n'+'\n'.join(tests)
    if source['dataset']=='humaneval':
        gt=json.loads(source['ground_truth'])
        if not isinstance(gt['test'],str) or not gt['entry_point'].isidentifier():raise ValueError('Invalid HumanEval test')
        return code+'\n\n'+gt['test']+'\ncheck('+gt['entry_point']+')\n'
    raise ValueError('Not a code dataset')


def third_party_imports(code):
    try:tree=ast.parse(code)
    except SyntaxError:return []
    names=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node,ast.ImportFrom) and node.module:names.add(node.module.split('.')[0])
    return sorted(names-set(sys.stdlib_module_names))


def score(source,response,executor=execute):
    if response.get('status')=='failed' or not response.get('answer'):
        return dict(quality=0.,evaluation_status='generation_failure')
    compiled=program(source,response)
    dependencies=third_party_imports(compiled)
    if dependencies:return dict(quality=None,evaluation_status='dependency_review_required',dependencies=dependencies)
    result=executor(compiled)
    if result.get('sandbox_ready') is not True:
        return dict(quality=None,evaluation_status='sandbox_failure',execution=result)
    if result.get('error_type') in ('ModuleNotFoundError','ImportError','PermissionError'):
        return dict(quality=None,evaluation_status='environment_review_required',execution=result)
    return dict(quality=float(result['passed']),evaluation_status='scored',execution=result)


def run(cohort_dir,raw_dir,out,probe_path,max_new=10000):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    with (out/'CODE.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        runtime_hash=verify_runtime()
        probe=json.loads(Path(probe_path).read_text())
        if probe.get('status')!='PASS' or probe.get('runtime_manifest_sha256')!=runtime_hash:
            raise ValueError('Sandbox probe must pass on this exact runtime')
        cohort,split=load_cohort(cohort_dir)
        protocol=dict(partition='train',datasets=['mbpp','humaneval'],
            query_sha256=sha(Path(cohort_dir)/'queries.jsonl'),split_sha256=sha(Path(cohort_dir)/'split.json'),
            source_sha256={p.name:sha(p) for p in [Path(__file__),Path(__file__).with_name('code_sandbox.py'),ROOT/'collect/metrics.py']},
            runtime_manifest_sha256=runtime_hash,probe_sha256=sha(probe_path),
            limits=dict(memory_mb=512,cpu_seconds=10,wall_seconds=12,output_bytes=65536),
            retries_per_unchanged_response=0,third_party_policy='Missing/unprofiled third-party imports deferred, not scored wrong',
            failure_policy='Generation failure/no answer => zero; delivered truncated answer tested as-is; raw statuses retained',
            role='Controlled pure-function stdlib-only development evaluation; denied filesystem/syscall operations deferred, not complete benchmark certification')
        p=out/'PROTOCOL.json'
        if p.exists() and json.loads(p.read_text())!=protocol:raise ValueError('Code scoring protocol changed')
        if not p.exists():write_json(p,protocol)
        journal=out/'SCORES.jsonl';seen=set()
        if journal.exists():
            for line in journal.read_text().split('\n'):
                if line.strip():seen.add(json.loads(line)['key'])
        stats=Counter();new=0;missing=0
        with journal.open('a') as stream:
            for slot in SLOTS:
                raw=storage.canonical_rows(Path(raw_dir)/f'{slot}.jsonl')
                for qid in sorted(split['train']):
                    source=cohort[qid]
                    if source['dataset'] not in ('mbpp','humaneval'):continue
                    if qid not in raw:missing+=1;continue
                    response=raw[qid]
                    key=digest(dict(source=source,response=response,slot=slot,protocol=digest(protocol)))
                    if key in seen:continue
                    if new>=max_new:continue
                    outcome=score(source,response)
                    record=dict(key=key,query_id=qid,slot=slot,dataset=source['dataset'],partition='train',
                        source_sha256=digest(source),response_sha256=digest(response),
                        generation_status=response.get('status'),**outcome)
                    stream.write(json.dumps(record,ensure_ascii=False)+'\n');stream.flush()
                    new+=1;stats[outcome['evaluation_status']]+=1
                    write_json(out/'STATUS.json',dict(phase='SCORING',updated_at=time.time(),new_records=new,
                        records_in_cache=len(seen)+new,counts=dict(stats),formal_training_ready=False))
                    if outcome['evaluation_status']=='sandbox_failure':
                        raise RuntimeError('Sandbox failure: stop scoring, inspect journal; never impute quality zero')
        summary=dict(phase='SNAPSHOT_FINISHED',updated_at=time.time(),new_records=new,
            records_in_cache=len(seen)+new,counts=dict(stats),missing_raw=missing,formal_training_ready=False)
        write_json(out/'STATUS.json',summary)
        return summary


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',required=True)
    ap.add_argument('--probe',default=str(ROOT/'router_v2/CODE_SANDBOX_PROBE_V3.json'))
    ap.add_argument('--max-new',type=int,default=10000)
    a=ap.parse_args()
    if a.max_new<0:raise ValueError('Negative record limit')
    print(json.dumps(run(ROOT/'data/cohort_full_v2',ROOT/'data/raw',a.output,a.probe,a.max_new),indent=2))

if __name__=='__main__':main()
