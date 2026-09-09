"""Audit known pilot exposure using ids and prompts, never quality values."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from .data import load_cohort, read_rows, sha


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument('--output',required=True)
    a=ap.parse_args();root=Path(a.root)
    cohort,split=load_cohort(root/'data/cohort_full_v2')
    pilot_path=root/'data/frozen/pilot_v1.jsonl'
    pilot=read_rows(pilot_path)
    manifest=json.loads((pilot_path.parent/'MANIFEST.json').read_text())
    if sha(pilot_path)!=manifest['dataset_sha256']:
        raise ValueError('Pilot frozen hash mismatch')
    pilot_ids={r['query_id'] for r in pilot}
    pilot_prompts={r['query'] for r in pilot}
    matrix_ids=set()
    with (root/'pilot_matrix.csv').open() as f:
        for row in csv.DictReader(f):matrix_ids.add(row['query_id'])
    known_ids=pilot_ids|matrix_ids
    exposed={qid for qid,row in cohort.items() if qid in known_ids or row['query'] in pilot_prompts}
    overlaps={k:sorted(set(ids)&exposed) for k,ids in split.items()}
    remaining=[qid for qid in split['test'] if qid not in exposed]
    files=[pilot_path,pilot_path.parent/'MANIFEST.json',root/'pilot_matrix.csv',
           root/'PILOT_OPPORTUNITY.md',root/'analyze_pilot.py',root/'R3_ROUTER_DESIGN.md',
           root/'data/cohort_full_v2/split.json']
    report=dict(status='KNOWN_PILOT_OVERLAP' if overlaps['test'] else 'NO_KNOWN_PILOT_OVERLAP',
        pilot_ids=len(pilot_ids),matrix_ids=len(matrix_ids),overlap_counts={k:len(v) for k,v in overlaps.items()},
        overlap_ids=overlaps,test_without_known_pilot_ids=remaining,
        test_without_known_pilot_n=len(remaining),
        remaining_test_by_source=dict(Counter(cohort[q]['dataset'] for q in remaining)),
        full_test_can_be_called_untouched=False if overlaps['test'] else 'not_certified',
        split_modified=False,quality_values_used=False,
        evidence_sha256={str(p):sha(p) for p in files},
        interpretation='Conservatively treat all pilot queries as exposed: pilot_matrix.csv contains outcomes and PILOT_OPPORTUNITY informs post-pilot design. Prior training is not required for analysis exposure.',
        next_step='Do not certify original full test as untouched. Remaining ids are a provenance-defined candidate subset only, not a new frozen evaluation protocol or proof of no other exposure; independent confirmation needs an explicit amendment or a new holdout.')
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    (out/'AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    lines=['# Pilot暴露审计（仅ID/请求匹配）','',
        f"已知pilot query：{len(pilot_ids)}；与train/validation/test重叠："+str(report['overlap_counts']),
        '',f"原test中排除已知pilot后剩{len(remaining)}题。此名单只用于审查，没有改变原split，也没有把剩余题自动认证为独立holdout。",
        '', '原750题test不能整体称为未触碰。继续训练可以服务开发验证；正式独立确认需先处理这个已知暴露问题。',
        '', '没有读取或汇总新的测试质量，也没有因表现删除测试题。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:report[k] for k in ('status','overlap_counts','test_without_known_pilot_n','split_modified')},indent=2))

if __name__=='__main__':main()
