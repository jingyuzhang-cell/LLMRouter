"""Prepare reproducible train-only blinded review packets; no additional judge calls."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
from .assemble_development import snapshot, label_key, storage
from .audit_judge_sensitivity import component_quality
from .data import load_cohort, sha
from .score_available import digest
from .core import SLOTS
ROOT = Path(__file__).resolve().parents[1]


def select_groups(groups, per_stratum=4, seed=20260909):
    pools = defaultdict(list)
    for qid, rows in sorted(groups.items()):
        if set(rows) != set(SLOTS): continue
        if any(component_quality(r) is None for r in rows.values()): continue
        primary = {s:r['quality'] for s,r in rows.items()}
        alternate = {s:component_quality(r) for s,r in rows.items()}
        best = lambda scores: {s for s,v in scores.items() if abs(v-max(scores.values())) < 1e-8}
        if best(primary) != best(alternate): stratum = 'best_set_changed'
        elif any(abs(primary[s]-alternate[s]) > 1e-8 for s in SLOTS): stratum = 'score_changed_best_stable'
        else: stratum = 'consistent_control'
        pools[stratum].append(qid)
    rng = random.Random(seed); selected = []
    for stratum in ('best_set_changed', 'score_changed_best_stable', 'consistent_control'):
        candidates = pools[stratum][:]; rng.shuffle(candidates)
        selected.extend((qid,stratum) for qid in candidates[:per_stratum])
    rng.shuffle(selected)
    return selected, {s:len(v) for s,v in pools.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', required=True)
    ap.add_argument('--per-stratum', type=int, default=4)
    args = ap.parse_args()
    if args.per_stratum < 1: raise ValueError('per-stratum must be positive')
    cohort, split = load_cohort(ROOT/'data/cohort_full_v2'); train=set(split['train'])
    journal=ROOT/'data/judged_train_primary_v2/ATTEMPTS.jsonl'
    events, provenance=snapshot(journal)
    raw={s:storage.canonical_rows(ROOT/'data/raw'/f'{s}.jsonl') for s in SLOTS}
    first={}
    for event in events:
        if event.get('event') != 'grade': continue
        qid,slot=event['query_id'],event['slot']
        if qid not in train or cohort[qid]['dataset'] != 'arenahard': raise ValueError('Non-train grade')
        response=raw.get(slot,{}).get(qid)
        if response is None or event['source_sha256'] != digest(cohort[qid]) or event['response_sha256'] != digest(response): continue
        first.setdefault(label_key(event),event)
    groups=defaultdict(dict)
    for row in first.values(): groups[row['query_id']][row['slot']]=row
    selected,pools=select_groups(groups,args.per_stratum)
    out=Path(args.output); out.mkdir(parents=True,exist_ok=False)
    blind=[]; key=[]; template=[]
    for i,(qid,stratum) in enumerate(selected,1):
        case=f'case_{i:03d}'
        slots=list(SLOTS)
        random.Random(hashlib.sha256(('20260909:'+qid).encode()).hexdigest()).shuffle(slots)
        answers=[]
        for j,slot in enumerate(slots):
            candidate=chr(65+j); event=groups[qid][slot]
            answers.append(dict(candidate=candidate,answer=raw[slot][qid]['answer']))
            key.append(dict(case=case,candidate=candidate,query_id=qid,slot=slot,stratum=stratum,
                            primary=event['quality'],component_sum=component_quality(event),
                            rubric=event['rubric'],source_sha256=event['source_sha256'],response_sha256=event['response_sha256']))
            template.append(dict(case=case,candidate=candidate,correctness=None,completeness=None,clarity=None,
                                 evidence=[],unresolved_facts=[],reviewer=None,review_status='pending'))
        blind.append(dict(case=case,question=cohort[qid]['query'],answers=answers))
    for filename,rows in [('BLIND.jsonl',blind),('PRIVATE_KEY.jsonl',key),('REVIEW_TEMPLATE.jsonl',template)]:
        (out/filename).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    report=dict(partition='train',seed=20260909,requested_per_stratum=args.per_stratum,pool_sizes=pools,
                selected_queries=len(blind),selected_answers=len(key),journal_snapshot=provenance,
                implementation_sha256=sha(Path(__file__)),query_sha256=sha(ROOT/'data/cohort_full_v2/queries.jsonl'),
                split_sha256=sha(ROOT/'data/cohort_full_v2/split.json'),
                files={name:sha(out/name) for name in ('BLIND.jsonl','PRIVATE_KEY.jsonl','REVIEW_TEMPLATE.jsonl')},
                independent_review_completed=False,formal_training_ready=False,
                caveat='Stratified diagnostic sample of available complete train queries, not population reliability estimate. Blinding hides metadata, not model self-identification in unchanged answers.')
    (out/'MANIFEST.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'INSTRUCTIONS.md').write_text('''# 盲审操作

仅将 BLIND.jsonl 和 REVIEW_TEMPLATE.jsonl 交给未看过 PRIVATE_KEY.jsonl 的审阅者。答案完整保留，可能包含模型自报身份；这里仅隐藏外部模型名、原分数和抽样层信息，不能承诺完全盲法。

逐答案依据原始量表评 correctness 0–6、completeness 0–2、clarity 0–2，并提供对应原文的依据。总分由三项确定性求和。不要为了吻合原 judge 分数调整分项。遇到无法核实的事实填写 unresolved_facts，保持 pending，不能猜测通过。

完成并封存带审阅者身份的评审文件后才能打开 PRIVATE_KEY.jsonl，比较同题排序与并列关系。审查必须与后续 router 表现隔离。该分层诊断样本不能用于声称整体准确率，也不能单独认证全体标签可靠。

本工具没有执行独立复评，没有增加 API 调用，没有替换训练标签。重复调用原 judge 不应重置既有每响应两次上限。后续独立核验需要另外明确评审人员或评审器、范围及预算。
''')
    print(json.dumps(report,indent=2))

if __name__ == '__main__': main()
