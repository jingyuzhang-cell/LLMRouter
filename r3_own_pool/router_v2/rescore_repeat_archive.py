"""Reuse verified raw generations under a new panel, never inherit old scores."""
import argparse
import json
from pathlib import Path
from .data import load_cohort
from .score_available import digest
from . import run_repeat_stability as repeat


def migrate(source, panel, output):
    source, panel, out = Path(source), Path(panel), Path(output)
    if out.exists(): raise FileExistsError(out)
    old = json.loads((source/'PROTOCOL.json').read_text())
    old_panel = Path(old['panel'])
    if repeat.sha(old_panel) != old['panel_sha256']: raise ValueError('Old panel changed')
    prior = {r['query_id']:r for r in repeat.read_jsonl(old_panel)}
    bound = {r['query_id']:r for r in repeat.bind_panel(repeat.read_jsonl(panel), repeat.ROOT/'data/cohort_full_v2')}
    cohort, _ = load_cohort(repeat.ROOT/'data/cohort_full_v2')
    args = argparse.Namespace(panel=str(panel.resolve()), slot='large', repeats=5, temperature=.7, top_p=1., stable_threshold=.8, workers=8)
    for k in ['repeats','temperature','top_p']:
        if old[k] != getattr(args,k): raise ValueError('Generation protocol mismatch')
    if old['max_tokens_by_task_type'] != repeat.MAX_TOKENS: raise ValueError('Token budget changed')
    repeat.write_protocol(out,args)
    source_raw = source/'large.jsonl'; seen=set(); rows=[]; changed=0
    for index, row in enumerate(repeat.read_jsonl(source_raw)):
        q = row['query_id']
        if q not in bound: continue
        if q not in prior or any(prior[q][k] != bound[q][k] for k in ['query','dataset','task_type']): raise ValueError('Query binding mismatch')
        if row.get('source_sha256') != digest(cohort[q]): raise ValueError('Unbound archive response')
        key = (q,row['repeat_index'])
        if key in seen: raise ValueError('Duplicate archive generation')
        seen.add(key)
        if row['slot']!='large' or row['model']!=repeat.SLOTS['large']['model']: raise ValueError('Model mismatch')
        if row.get('status') not in ['ok','truncated','parse_failed'] or row.get('error'): continue
        if any(row[k] != getattr(args,k) for k in ['temperature','top_p']): raise ValueError('Row sampling mismatch')
        if int(row['repeat_index']) not in range(args.repeats):raise ValueError('Repeat index outside protocol')
        result = repeat.score_answer(bound[q],row.get('answer'),row['status'])
        changed += int(row.get('quality') != result.get('quality'))
        rows.append({**row,**result,'panel_index':bound[q]['panel_index'],
            'label_protocol_version':2,'scorer_sha256':repeat.sha(repeat.__file__),
            'panel_sha256':repeat.sha(panel),'cohort_sha256':repeat.sha(repeat.ROOT/'data/cohort_full_v2/queries.jsonl'),
            'raw_reuse':{'source':str(source_raw.resolve()),'source_sha256':repeat.sha(source_raw),'line':index+1,
                         'generation_collector_sha256':old.get('collector_sha256'),'old_quality':row.get('quality')}})
    with (out/'large.jsonl').open('x') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    report = dict(reused_generations=len(rows),queries=len(set(r['query_id'] for r in rows)),rescored_label_changes=changed,
                  source_raw_sha256=repeat.sha(source_raw),source_protocol_sha256=repeat.sha(source/'PROTOCOL.json'),
                  target_panel_sha256=repeat.sha(panel),new_generation_calls=0,old_files_modified=False,
                  limitations=['Original latency was collected at concurrency 8; retain as exploratory measurement',
                               'Query eligibility follows new fold selections; reuse never selects by repeat quality'])
    (out/'REUSE_AUDIT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ['source','panel','output']:ap.add_argument('--'+n,required=True)
    a=ap.parse_args();migrate(a.source,a.panel,a.output)
