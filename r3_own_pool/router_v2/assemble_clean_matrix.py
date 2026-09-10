"""Clean train matrix snapshot: infrastructure failures are missing labels, never zero quality.

Contamination audit 2026-09-10: 633/14000 train cells carried quality=0 from
DashScope arrearage ('Access denied' HTTP 400) during reasoning collection, not
model behavior. After re-collection this builder rebinds labels from the v3
caches and marks any cell whose generation still failed as missing:
quality.final=None, quality_source='infrastructure_failure_missing'. Cached
zero-for-failure policies in scorer/judge journals are unchanged; the policy
conversion happens here, at the auditable matrix layer.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
from .data import load_cohort,sha
from .core import SLOTS
from .score_available import digest
from .embed_queries import write_json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'collect'))
import storage


def snapshot(path):
    path=Path(path)
    if not path.exists():return [],dict(exists=False)
    data=path.read_bytes()
    # Readers may see the writer's last unfinished append; never parse it as a record.
    complete=data[:data.rfind(b'\n')+1] if data and not data.endswith(b'\n') else data
    rows=[json.loads(line) for line in complete.split(b'\n') if line.strip()]
    return rows,dict(exists=True,complete_prefix_sha256=hashlib.sha256(complete).hexdigest(),
                     complete_bytes=len(complete),ignored_unfinished_tail_bytes=len(data)-len(complete),records=len(rows))


def label_key(row):
    return row['query_id'],row['slot'],row['source_sha256'],row['response_sha256']


def merge_labels(auto,code,supplement,judge):
    merged={}
    for kind,rows in [('auto',auto),('code_stdlib',code),('code_numpy',supplement)]:
        for row in rows:
            key=label_key(row)
            # A supplemental failure must never erase a previously scored label.
            if key not in merged or merged[key][1].get('quality') is None:
                merged[key]=(kind,row)
    for row in judge:
        if row.get('event') not in ('grade','generation_failure'):continue
        key=label_key(row)
        # Reported-score amendment uses first usable scalar, never a later/high score.
        if key not in merged:merged[key]=('judge_primary',row)
    return merged


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',required=True)
    args=ap.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    cohort,split=load_cohort(ROOT/'data/cohort_full_v2')
    paths=[ROOT/'data/scored_train_v3/SCORES.jsonl',ROOT/'data/scored_code_train_v3/SCORES.jsonl',
           ROOT/'data/scored_code_numpy_train_v3/SCORES.jsonl',ROOT/'data/judged_train_primary_v3/ATTEMPTS.jsonl']
    snapshots=[snapshot(path) for path in paths]
    labels=merge_labels(*(item[0] for item in snapshots))
    raw={slot:storage.canonical_rows(ROOT/'data/raw'/f'{slot}.jsonl') for slot in SLOTS}
    counts=Counter();by_dataset={};records=[]
    for qid in split['train']:
        source=cohort[qid];sh=digest(source)
        record={k:source[k] for k in ('query_id','query','dataset','task_type')}
        record['responses']=[]
        per=by_dataset.setdefault(source['dataset'],Counter())
        complete=True
        for slot in SLOTS:
            response=raw[slot].get(qid)
            per['expected_cells']+=1
            if response is None:
                counts['missing_response']+=1;per['missing_response']+=1;complete=False
                record['responses'].append(dict(slot=slot,status='not_collected',quality={'final':None},cost={'usd':None},latency={'total_ms':None}))
                continue
            rh=digest(response)
            infrastructure_failure=(response.get('status')=='failed')
            selected=labels.get((qid,slot,sh,rh))
            kind,label=selected if selected else ('unscored',{})
            if label.get('evaluation_status')=='generation_failure' or label.get('event')=='generation_failure':
                infrastructure_failure=True
            quality=label.get('quality')
            if infrastructure_failure:
                # Clean policy: an infrastructure-induced generation failure is a
                # missing label, not evidence of model quality.
                quality=None;kind='infrastructure_failure_missing'
            if quality is not None and (not math.isfinite(quality) or not 0<=quality<=1):
                raise ValueError('Invalid cached quality')
            if quality is None:
                complete=False
                if kind=='infrastructure_failure_missing':
                    counts['infrastructure_failure_missing']+=1;per['infrastructure_failure_missing']+=1
                else:
                    counts['missing_label']+=1;per['missing_label']+=1
            else:
                counts['labeled_cells']+=1;per['labeled_cells']+=1
            flags=[]
            if infrastructure_failure:flags.append('infrastructure_failure')
            if label.get('rubric',{}).get('components_consistent') is False:
                flags.append('judge_components_inconsistent');counts['judge_components_inconsistent']+=1
            record['responses'].append(dict(slot=slot,model=response.get('model'),status=response.get('status'),
                quality=dict(final=quality,quality_source=kind,flags=flags),
                cost=response.get('cost') or {},latency=response.get('latency') or {},
                response_sha256=rh,source_sha256=sh,evaluation_status='generation_failure_missing' if infrastructure_failure else label.get('evaluation_status',label.get('event','unscored'))))
        counts['complete_label_queries']+=int(complete)
        records.append(record)
    target=out/'TRAIN_MATRIX.jsonl'
    with target.open('x') as f:
        for row in records:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    emb=ROOT/'data/embeddings_full_v2_recovery1/EMBEDDINGS.npz'
    embedding={}
    if emb.exists():
        manifest=json.loads((emb.parent/'MANIFEST.json').read_text())
        if sha(emb)!=manifest['embedding_sha256']:raise ValueError('Embedding hash mismatch')
        with np.load(emb,allow_pickle=False) as saved:
            ids=saved['ids'].tolist();vectors=saved['vectors']
            if len(ids)!=len(set(ids)) or set(ids)!=set(cohort) or vectors.shape!=(len(cohort),3584):
                raise ValueError('Embedding id/shape mismatch')
            if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors,axis=1),1,atol=.005):
                raise ValueError('Invalid embedding vectors')
            if saved['query_sha256'].item()!=sha(ROOT/'data/cohort_full_v2/queries.jsonl'):raise ValueError('Embedding query hash mismatch')
            embedding=dict(status='VERIFIED',queries=len(ids),dimensions=3584,sha256=sha(emb))
    else:embedding=dict(status='PENDING')
    report=dict(partition='train',queries=len(records),expected_cells=4*len(records),counts=dict(counts),
        by_dataset={k:dict(v) for k,v in by_dataset.items()},embedding=embedding,
        matrix_sha256=sha(target),cache_snapshots={str(p):info for p,(_,info) in zip(paths,snapshots)},
        failure_policy='Infrastructure-induced generation failures (provider arrearage/access denials) are missing labels; never quality zero.',
        decontamination=dict(audited_against='train_matrix_snapshot_20260909c',
            contaminated_cells_there=633,cause='DashScope arrearage during reasoning collection',
            remediation='reasoning re-collected 2026-09-10; labels rebound from v3 caches'),
        formal_training_ready=False,test_labels_loaded=False,original_split_modified=False,
        remaining=['Missing raw/labels shown above','Judge reliability incl. component inconsistency',
                   'Common verified monetary cost basis','Independent-confirmation protocol after pilot exposure'],
        note='Read-only clean label snapshot after infrastructure-failure decontamination; no utility/quality aggregate and no test evaluation.')
    write_json(out/'MANIFEST.json',report)
    print(json.dumps({k:report[k] for k in ('queries','expected_cells','counts','by_dataset','embedding','failure_policy')},indent=2))


if __name__=='__main__':main()
