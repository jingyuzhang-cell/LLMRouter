"""Frozen local GTE query-only embeddings, resumable and exclusive with collection."""
import argparse
from collections import Counter
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import time
import numpy as np
from .data import load_cohort, sha

ROOT=Path(__file__).resolve().parents[1]
MODEL='/root/autodl-tmp/models/gte-Qwen2-7B-instruct-fp16'


def write_json(path, obj):
    path=Path(path);tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,indent=2));tmp.replace(path)


def status(out, phase, **extra):
    write_json(Path(out)/'STATUS.json',dict(phase=phase,updated_at=time.time(),**extra))
    print(json.dumps(dict(phase=phase,**extra)),flush=True)


def plan(cohort_dir, model_dir, out):
    from transformers import AutoTokenizer
    cohort,split=load_cohort(cohort_dir)
    model=Path(model_dir);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    ids=sorted(cohort)
    config=json.loads((model/'config.json').read_text())
    index=json.loads((model/'model.safetensors.index.json').read_text())
    weights=sorted(set(index['weight_map'].values()))
    if any(not (model/name).is_file() or (model/name).stat().st_size==0 for name in weights):
        raise ValueError('Missing local encoder weights')
    tokenizer=AutoTokenizer.from_pretrained(str(model),local_files_only=True,trust_remote_code=False)
    lengths=[]
    for start in range(0,len(ids),128):
        batch=[cohort[q]['query'] for q in ids[start:start+128]]
        tokenized=tokenizer(batch,add_special_tokens=True,truncation=False,return_attention_mask=False)
        lengths.extend(map(len,tokenized['input_ids']))
    config_paths=[p for p in model.rglob('*.json') if '.cache' not in p.parts]
    config_paths += [p for p in (model/'merges.txt',) if p.exists()]
    description=dict(query_sha256=sha(Path(cohort_dir)/'queries.jsonl'),
        split_sha256=sha(Path(cohort_dir)/'split.json'),model_path=str(model.resolve()),
        config_sha256={str(p.relative_to(model)):sha(p) for p in sorted(config_paths)},
        weight_sizes={name:(model/name).stat().st_size for name in weights},
        dimensions=config['hidden_size'],max_sequence_length=32768,batch_size=1,
        dtype='float16',normalize_embeddings=True,query_prompt='none (default_prompt_name=None)',
        query_count=len(ids),length_quantiles=np.quantile(lengths,[0,.5,.9,.99,1]).tolist(),
        truncated_query_count=sum(n>32768 for n in lengths),
        truncated_query_ids=[q for q,n in zip(ids,lengths) if n>32768],
        input_fields=['query'],outcomes_loaded=False,remote_requests=False,
        note='Weights hashed at execution; plan checks local shards/configs and tokenizer only.')
    target=out/'PLAN.json'
    if target.exists() and json.loads(target.read_text())!=description:
        raise ValueError('Frozen embedding plan changed; use a new directory')
    if not target.exists():write_json(target,description)
    return description


def gpu_free():
    check=subprocess.run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],capture_output=True,text=True)
    if check.returncode:
        raise RuntimeError('Cannot verify GPU ownership')
    return not check.stdout.strip()


def local_complete(cohort_dir):
    import importlib.util
    spec=importlib.util.spec_from_file_location('_r3_embedding_storage',ROOT/'collect/storage.py')
    storage=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(storage)
    cohort,_=load_cohort(cohort_dir)
    expected=set(cohort)
    return all(expected <= set(storage.canonical_rows(ROOT/'data/raw'/f'{slot}.jsonl'))
               for slot in ('small','medium','large'))


def hash_large(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def encode(cohort_dir, model_dir, out, wait=False, deadline_hours=24):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    with (out/'JOB.lock').open('a+') as job_lock:
        fcntl.flock(job_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (out/'EMBEDDINGS.npz').exists():
            raise FileExistsError('Completed embedding artifact already exists')
        description=plan(cohort_dir,model_dir,out)
        deadline=time.monotonic()+deadline_hours*3600
        # Same lock as collection runner; wait for all local slots before acquiring.
        with (ROOT/'collect/logs/local_gpu.lock').open('a+') as gpu_lock:
            while True:
                complete=local_complete(cohort_dir)
                acquired=False
                if complete:
                    try:
                        fcntl.flock(gpu_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        acquired=True
                    except BlockingIOError:pass
                if acquired:
                    if gpu_free():break
                    fcntl.flock(gpu_lock,fcntl.LOCK_UN)
                if not wait or time.monotonic()>=deadline:
                    raise RuntimeError('Local collection incomplete or GPU occupied; no encoder loaded')
                status(out,'WAITING_FOR_LOCAL_COLLECTION_AND_GPU',local_records_complete=complete)
                time.sleep(30)
            status(out,'HASHING_LOCAL_ENCODER')
            model=Path(model_dir)
            weights={name:hash_large(model/name) for name in description['weight_sizes']}
            import importlib.metadata as metadata
            provenance=dict(plan_sha256=sha(out/'PLAN.json'),weight_sha256=weights,
                source_sha256=sha(Path(__file__)),
                packages={n:metadata.version(n) for n in ('torch','transformers','sentence-transformers','numpy')})
            p=out/'PROVENANCE.json'
            if p.exists() and json.loads(p.read_text())!=provenance:
                raise ValueError('Encoder/implementation changed across resume')
            write_json(p,provenance)
            import torch
            from sentence_transformers import SentenceTransformer
            status(out,'LOADING_ENCODER')
            encoder=SentenceTransformer(str(model),local_files_only=True,trust_remote_code=False,
                device='cuda',model_kwargs={'torch_dtype':torch.float16})
            encoder.max_seq_length=description['max_sequence_length']
            cohort,_=load_cohort(cohort_dir);ids=sorted(cohort)
            # Canary verifies dimensions, finite vectors, and repeat consistency.
            probe=encoder.encode([cohort[ids[0]]['query']],batch_size=1,convert_to_numpy=True,normalize_embeddings=True)
            again=encoder.encode([cohort[ids[0]]['query']],batch_size=1,convert_to_numpy=True,normalize_embeddings=True)
            if probe.shape!=(1,description['dimensions']) or not np.isfinite(probe).all() or not np.allclose(probe,again,atol=1e-5,rtol=1e-4):
                raise ValueError('Encoder canary failed')
            chunks=out/'chunks';chunks.mkdir(exist_ok=True)
            all_vectors=[]
            for start in range(0,len(ids),16):
                chunk_ids=ids[start:start+16]
                file=chunks/f'{start:06d}.npz'
                if file.exists():
                    with np.load(file,allow_pickle=False) as archive:
                        if archive['ids'].tolist()!=chunk_ids:raise ValueError('Chunk ids changed')
                        vectors=archive['vectors']
                else:
                    vectors=encoder.encode([cohort[q]['query'] for q in chunk_ids],batch_size=1,
                        convert_to_numpy=True,normalize_embeddings=True,show_progress_bar=False).astype('float32')
                if vectors.shape!=(len(chunk_ids),description['dimensions']) or not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors,axis=1),1.,atol=.005):
                    raise ValueError('Invalid embedding chunk')
                if not file.exists():
                    with file.with_suffix('.tmp').open('wb') as f:
                        np.savez_compressed(f,ids=np.array(chunk_ids),vectors=vectors)
                    file.with_suffix('.tmp').replace(file)
                all_vectors.append(vectors)
                status(out,'ENCODING',completed_queries=start+len(chunk_ids),total_queries=len(ids))
            with (out/'EMBEDDINGS.tmp').open('wb') as f:
                np.savez_compressed(f,ids=np.array(ids),vectors=np.concatenate(all_vectors),
                    query_sha256=description['query_sha256'])
            (out/'EMBEDDINGS.tmp').replace(out/'EMBEDDINGS.npz')
            write_json(out/'MANIFEST.json',dict(embedding_sha256=sha(out/'EMBEDDINGS.npz'),
                provenance_sha256=sha(out/'PROVENANCE.json'),plan_sha256=sha(out/'PLAN.json')))
            del encoder;torch.cuda.empty_cache()
            status(out,'COMPLETE',queries=len(ids),output=str(out/'EMBEDDINGS.npz'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage',choices=('plan','encode'))
    ap.add_argument('--cohort',default=str(ROOT/'data/cohort_full_v2'))
    ap.add_argument('--model',default=MODEL)
    ap.add_argument('--output',required=True)
    ap.add_argument('--wait',action='store_true')
    a=ap.parse_args()
    try:
        if a.stage=='plan':print(json.dumps(plan(a.cohort,a.model,a.output),indent=2))
        else:encode(a.cohort,a.model,a.output,a.wait)
    except BlockingIOError:
        raise SystemExit("Another embedding job holds the lock; its status is unchanged")
    except Exception as exc:
        Path(a.output).mkdir(parents=True,exist_ok=True)
        status(a.output,'BLOCKED',reason=str(exc))
        raise

if __name__=='__main__':main()
