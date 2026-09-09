"""Supplement only NumPy-deferred train code; original candidate/tests unchanged."""
import json
from pathlib import Path
import shutil
import sys
import numpy as np
from .code_sandbox import RUNTIME,execute,probe,verify_runtime
from .score_code import program
from .score_available import digest
from .data import load_cohort,sha
from .embed_queries import write_json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'collect'))
import storage
DEST=Path('/tmp/r3-code-runtime-numpy-v1')
PRELUDE="import os as _r3_runtime_os\n_r3_runtime_os.environ['OPENBLAS_NUM_THREADS']='1'\n_r3_runtime_os.environ['OMP_NUM_THREADS']='1'\ndel _r3_runtime_os\n"


def main():
    verify_runtime(RUNTIME)
    if not DEST.exists():
        shutil.copytree(RUNTIME,DEST)
        package=Path(np.__file__).parent
        shutil.copytree(package,DEST/'lib/python3.12/numpy',ignore=shutil.ignore_patterns('__pycache__','tests'))
        libs=package.parent/'numpy.libs'
        if libs.exists():shutil.copytree(libs,DEST/'lib/python3.12/numpy.libs')
        files={str(p.relative_to(DEST)):sha(p) for p in sorted(DEST.rglob('*')) if p.is_file() and p.name!='MANIFEST.json'}
        write_json(DEST/'MANIFEST.json',dict(files=files,worker_source_sha256=sha(DEST/'worker.py'),
            base_manifest_sha256=sha(RUNTIME/'MANIFEST.json'),numpy_version=np.__version__,
            role='Pure-function NumPy supplement; inherited Landlock/seccomp and resource limits'))
    verify_runtime(DEST)
    result=probe(DEST)
    result['numpy_canary']=execute(PRELUDE+"import numpy as np\nassert int(np.bitwise_and(1,2))==0\nassert np.__version__=="+repr(np.__version__),DEST)
    if result['status']!='PASS' or result['numpy_canary'].get('sandbox_ready') is not True or not result['numpy_canary']['passed']:
        write_json(ROOT/'router_v2/NUMPY_SANDBOX_AUDIT.json',result)
        raise RuntimeError('NumPy sandbox canary failed; no real candidate executed')
    cohort,split=load_cohort(ROOT/'data/cohort_full_v2')
    allowed=set(split['train'])
    base=ROOT/'data/scored_code_train_v2/SCORES.jsonl'
    deferred=[json.loads(line) for line in base.read_text().split('\n') if line.strip()]
    deferred=[r for r in deferred if r.get('dependencies')==['numpy'] and r['query_id'] in allowed]
    out=ROOT/'data/scored_code_numpy_train_v2';out.mkdir(exist_ok=True)
    output=out/'SCORES.jsonl'
    if output.exists():raise FileExistsError('Supplement already executed; preserve result')
    raw={slot:storage.canonical_rows(ROOT/'data/raw'/f'{slot}.jsonl') for slot in {r['slot'] for r in deferred}}
    records=[]
    for old in deferred:
        source=cohort[old['query_id']];response=raw[old['slot']][old['query_id']]
        if digest(response)!=old['response_sha256'] or digest(source)!=old['source_sha256']:
            raise ValueError('Deferred response/source changed')
        execution=execute(PRELUDE+program(source,response),DEST)
        quality=float(execution['passed']) if execution.get('sandbox_ready') is True and execution.get('error_type') not in ('ImportError','ModuleNotFoundError','PermissionError') else None
        records.append(dict(query_id=old['query_id'],slot=old['slot'],dataset=old['dataset'],partition='train',
            source_sha256=old['source_sha256'],response_sha256=old['response_sha256'],parent_key=old['key'],
            quality=quality,evaluation_status='scored' if quality is not None else 'environment_review_required',
            execution=execution,runtime_manifest_sha256=sha(DEST/'MANIFEST.json'),prelude_sha256=digest(PRELUDE)))
    with output.open('x') as f:
        for row in records:f.write(json.dumps(row)+'\n')
    result.update(records=len(records),resolved=sum(r['quality'] is not None for r in records),
        original_scores_modified=False,candidate_and_tests_modified=False,
        prelude='Set OpenBLAS/OMP thread count to 1, delete setup alias; no change to candidate or tests',
        output_sha256=sha(output),source_sha256=sha(Path(__file__)))
    write_json(ROOT/'router_v2/NUMPY_SANDBOX_AUDIT.json',result)
    print(json.dumps({k:result[k] for k in ('status','records','resolved','original_scores_modified','candidate_and_tests_modified')},indent=2))

if __name__=='__main__':main()
