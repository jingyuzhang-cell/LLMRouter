"""Supplement only NumPy-deferred train code labels for the v3 clean rebuild; candidates/tests unchanged.

v3 variant of resolve_numpy_code.py: reads scored_code_train_v3 (post
decontamination re-collection), writes scored_code_numpy_train_v3. Reuses the
already-audited /tmp/r3-code-runtime-numpy-v1 runtime; refuses to run if the
numpy runtime or its audit is missing.
"""
import json
from pathlib import Path
import sys
from .code_sandbox import RUNTIME,execute,verify_runtime
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
        raise RuntimeError('Audited numpy runtime missing; copy from resolve_numpy_code.py flow, never rebuild ad hoc')
    audit=json.loads((ROOT/'router_v2/NUMPY_SANDBOX_AUDIT.json').read_text())
    if audit.get('status')!='PASS':raise RuntimeError('NumPy sandbox audit not PASS')
    verify_runtime(DEST)
    cohort,split=load_cohort(ROOT/'data/cohort_full_v2')
    allowed=set(split['train'])
    base=ROOT/'data/scored_code_train_v3/SCORES.jsonl'
    deferred=[json.loads(line) for line in base.read_text().split('\n') if line.strip()]
    deferred=[r for r in deferred if r.get('dependencies')==['numpy'] and r['query_id'] in allowed]
    out=ROOT/'data/scored_code_numpy_train_v3';out.mkdir(parents=True,exist_ok=True)
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
    write_json(out/'STATUS.json',dict(records=len(records),resolved=sum(r['quality'] is not None for r in records),
        original_scores_modified=False,candidate_and_tests_modified=False,
        runtime=DEST.name,source_cache=str(base)))
    print(json.dumps(dict(records=len(records),resolved=sum(r['quality'] is not None for r in records))))


if __name__=='__main__':main()
