"""Audit prompt exposure and train labels; do not aggregate holdout outcomes."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from .data import load_cohort, read_rows, sha
from .integrity import prompt_groups, require_valid_quality, known_exposure


def run(root, output, matrices):
    root=Path(root);out=Path(output);out.mkdir(parents=True,exist_ok=False)
    cohort,split=load_cohort(root/'data/cohort_full_v2')
    partition={q:k for k,ids in split.items() for q in ids}
    groups,edges=prompt_groups(cohort)
    grouped=defaultdict(list)
    for q,g in groups.items(): grouped[g].append(q)
    cross=[v for v in grouped.values() if len({partition[q] for q in v})>1]
    pilot=read_rows(root/'data/frozen/pilot_v1.jsonl')
    from .integrity import normalize_prompt
    pilot_ids={r['query_id'] for r in pilot};pilot_text={normalize_prompt(r['query']) for r in pilot}
    exposed={q for q in cohort if q in pilot_ids or normalize_prompt(cohort[q]['query']) in pilot_text}
    historic_ids,historic_text,historic_evidence=known_exposure(root)
    all_exposed={q for q in cohort if q in historic_ids or normalize_prompt(cohort[q]['query']) in historic_text}
    exposed_groups={groups[q] for q in all_exposed}
    dev_groups={groups[q] for q in split['train']+split['validation']}
    quarantined=sorted(q for q in split['test'] if groups[q] in exposed_groups|dev_groups)
    candidates=sorted(set(split['test'])-set(quarantined))
    audits={}
    for path in matrices:
        rows=read_rows(path)
        if set(r['query_id'] for r in rows)!=set(split['train']): raise ValueError('Audit matrices must be train-only')
        bad=[];statuses=Counter();missing=0
        for row in rows:
            for response in row['responses']:
                statuses[response.get('evaluation_status','unknown')]+=1
                if response['quality']['final'] is None: missing+=1;continue
                try: require_valid_quality(response)
                except ValueError:
                    bad.append({'query_id':row['query_id'],'dataset':row['dataset'],'slot':response['slot'],'quality':response['quality']['final']})
        audits[str(path)]=dict(sha256=sha(path),invalid_labeled_cells=len(bad),by_dataset=dict(Counter(r['dataset'] for r in bad)),missing_cells=missing,status_counts=dict(statuses),invalid_cells=bad)
    opened=[]
    for marker in (root/'router_v2').glob('*/TEST_OPENED.json'):
        protocol=marker.parent/'PROTOCOL.json'
        p=json.loads(protocol.read_text()) if protocol.exists() else {}
        opened.append(dict(marker=str(marker),role=p.get('role'),sha256=sha(marker)))
    result=dict(role='contamination_audit_train_labels_and_prompt_metadata',
        prior_real_test_openings=historic_evidence,
        known_exposure_overlap={k:len(set(ids)&all_exposed) for k,ids in split.items()},
        known_pilot_overlap={k:len(set(ids)&exposed) for k,ids in split.items()},
        normalized_exact_edges=sum(e['kind']=='normalized_exact' for e in edges),
        near_duplicate_edges=sum(e['kind']=='lexical_near_duplicate' for e in edges),
        cross_partition_groups=cross,holdout_quarantine_ids=quarantined,
        holdout_candidates_not_certified=candidates,holdout_candidate_count=len(candidates),
        train_matrix_audits=audits,test_opening_markers=opened,test_quality_aggregated=False,
        formal_holdout_certified=False,
        limits=['Lexical screening is not exhaustive semantic duplicate detection.',
                'Public benchmark inclusion in base-model pretraining cannot be established from local router files.',
                'Remaining test IDs are candidates only; historical exposure cannot be undone by reshuffling.',
                'Original validation and repeated OOF runs are development data, not independent confirmation.'])
    (out/'AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (out/'PROMPT_GROUPS.json').write_text(json.dumps(dict(queries_sha256=sha(root/'data/cohort_full_v2/queries.jsonl'),groups=groups,edges=edges),ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['known_pilot_overlap','normalized_exact_edges','near_duplicate_edges','holdout_candidate_count','test_opening_markers']},indent=2))
    for p,a in audits.items():print(p,json.dumps({k:v for k,v in a.items() if k not in ('invalid_cells','status_counts')},indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));ap.add_argument('--output',required=True);ap.add_argument('--matrices',nargs='+',required=True)
    a=ap.parse_args();run(a.root,a.output,a.matrices)
