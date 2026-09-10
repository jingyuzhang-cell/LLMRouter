"""Full-cohort outcomes assembly for the v2 freeze gate.

Builds the exact-cohort outcomes.jsonl (schema consumed by data.load_outcomes)
from per-partition label caches and raw collection records. Conventions are
explicit and audited, never silent:
- quality: from bound label caches; any missing label aborts the assembly.
- cost/latency: ok/truncated cells recomputed as tokens x price_table_v2;
  failed generations recorded as usd 0.0 / total_ms 0.0 with the flag
  'generation_failure_zero_resource' (failed DashScope requests are unbilled;
  wall time of failed attempts was not instrumented at collection time).
- Cost/latency values recorded at collection time are preserved verbatim under
  cost.collected_usd / latency.collected_total_ms for audit comparison.
"""
import argparse
from collections import Counter
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

LABEL_SOURCES={
 'train':[ROOT/'data/scored_train_v2/SCORES.jsonl',ROOT/'data/scored_code_train_v2/SCORES.jsonl',
          ROOT/'data/scored_code_numpy_train_v2/SCORES.jsonl',ROOT/'data/judged_train_primary_v2/ATTEMPTS.jsonl'],
 'validation':[ROOT/'data/scored_validation_v2/SCORES.jsonl',ROOT/'data/scored_code_validation_v2/SCORES.jsonl',
               ROOT/'data/judged_validation_primary_v2/ATTEMPTS.jsonl'],
 'test':[ROOT/'data/scored_test_v2/SCORES.jsonl',ROOT/'data/scored_code_test_v2/SCORES.jsonl',
         ROOT/'data/judged_test_primary_v2/ATTEMPTS.jsonl'],
}


def merged_labels(path):
    rows=[json.loads(line) for line in path.read_text().split('\n') if line.strip()]
    labels={}
    for row in rows:
        if row.get('event') not in (None,'grade','generation_failure'):continue
        key=(row['query_id'],row['slot'],row['source_sha256'],row['response_sha256'])
        if key not in labels or labels[key][1].get('quality') is None:
            labels[key]=('journal',row)
    return labels


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',required=True)
    args=ap.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    prices=json.loads((ROOT/'collect/price_table_v2.json').read_text())['models']
    model_price={m:(v['input'],v['output']) for m,v in prices.items()}
    # Collection records name the large slot without the -GPTQ-Int8 quant suffix; same deployment.
    model_price.setdefault('Qwen/Qwen2.5-14B-Instruct',model_price['Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8'])
    cohort,split=load_cohort(ROOT/'data/cohort_full_v2')
    raw={slot:storage.canonical_rows(ROOT/'data/raw'/f'{slot}.jsonl') for slot in SLOTS}
    labels={}
    for part,paths in LABEL_SOURCES.items():
        for p in paths:
            if not p.exists():raise ValueError('Missing label cache: '+str(p))
            for k,v in merged_labels(p).items():
                if k not in labels or labels[k][1].get('quality') is None:labels[k]=v
    counts=Counter();records=[]
    for part in ('train','validation','test'):
        for qid in sorted(split[part]):
            source=cohort[qid];sh=digest(source)
            record={k:source[k] for k in ('query_id','query','dataset','task_type')}
            record['partition']=part;record['responses']=[]
            for slot in SLOTS:
                response=raw[slot].get(qid)
                counts['cells']+=1
                if response is None:raise ValueError(f'Uncollected cell {qid}/{slot}')
                rh=digest(response);status=response.get('status')
                kind,label=labels.get((qid,slot,sh,rh),('unscored',{}))
                quality=label.get('quality')
                if quality is None or not math.isfinite(quality) or not 0<=quality<=1:
                    raise ValueError(f'Unlabeled/invalid cell {qid}/{slot} ({kind})')
                flags=[]
                if label.get('rubric',{}).get('components_consistent') is False:
                    flags.append('judge_components_inconsistent');counts['judge_components_inconsistent']+=1
                cost_in=(response.get('cost') or {});lat_in=(response.get('latency') or {})
                if status=='failed':
                    if quality!=0.:raise ValueError(f'Failed cell with nonzero quality {qid}/{slot}')
                    usd=0.0;total_ms=0.0;flags.append('generation_failure_zero_resource')
                    counts['generation_failure_zero_resource']+=1
                else:
                    model=response.get('model');pin,pout=model_price[model]
                    ti,to=cost_in.get('tokens_input'),cost_in.get('tokens_output')
                    if ti is None or to is None or cost_in.get('tokens_estimated'):
                        raise ValueError(f'Missing/estimated tokens on delivered cell {qid}/{slot}')
                    usd=round((ti*pin+to*pout)/1e6,8)
                    total_ms=lat_in.get('total_ms')
                    if total_ms is None or not math.isfinite(total_ms) or total_ms<0:
                        raise ValueError(f'Missing latency on delivered cell {qid}/{slot}')
                counts[f'{status}']+=1
                record['responses'].append(dict(slot=slot,model=response.get('model'),status=status,
                    quality=dict(final=quality,quality_source=kind,flags=flags),
                    cost=dict(usd=usd,tokens_input=cost_in.get('tokens_input'),tokens_output=cost_in.get('tokens_output'),
                        price_input_per_mtok=model_price.get(response.get('model'),(None,None))[0],
                        price_output_per_mtok=model_price.get(response.get('model'),(None,None))[1],
                        collected_usd=cost_in.get('usd'),price_table='collect/price_table_v2.json'),
                    latency=dict(total_ms=total_ms,collected_total_ms=lat_in.get('total_ms')),
                    response_sha256=rh,source_sha256=sh,
                    evaluation_status=label.get('evaluation_status',label.get('event','unscored'))))
            records.append(record)
    target=out/'OUTCOMES.jsonl'
    with target.open('x') as f:
        for row in records:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    emb=ROOT/'data/embeddings_full_v2_recovery1/EMBEDDINGS.npz'
    embedding={}
    if emb.exists():
        manifest=json.loads((emb.parent/'MANIFEST.json').read_text())
        if sha(emb)!=manifest['embedding_sha256']:raise ValueError('Embedding hash mismatch')
        with np.load(emb,allow_pickle=False) as saved:
            if saved['query_sha256'].item()!=sha(ROOT/'data/cohort_full_v2/queries.jsonl'):raise ValueError('Embedding query hash mismatch')
        embedding=dict(status='VERIFIED',sha256=sha(emb))
    else:embedding=dict(status='MISSING')
    report=dict(queries=len(records),counts=dict(counts),embedding=embedding,
        outcomes_sha256=sha(target),price_table_sha256=sha(ROOT/'collect/price_table_v2.json'),
        conventions='failed generation => quality 0 (bound label), usd 0.0, total_ms 0.0, flagged; delivered cells recomputed from price_table_v2',
        label_caches={str(p):sha(p) for part in LABEL_SOURCES for p in LABEL_SOURCES[part]},
        note='Exact-cohort outcomes for freeze; no utility aggregation, no test result reporting.')
    write_json(out/'MANIFEST.json',report)
    print(json.dumps({k:report[k] for k in ('queries','counts','embedding')},indent=2))


if __name__=='__main__':main()
