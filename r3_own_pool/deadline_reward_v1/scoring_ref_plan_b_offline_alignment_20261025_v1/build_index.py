"""Offline evidence-position index. No model calls or semantic truth assignments."""
import hashlib
import json
from pathlib import Path
from collections import Counter

RUN = Path('/root/r3_own_pool/deadline_reward_v1/scoring_ref_plan_b_request_binding_20261023_v1/REAL_RUN_20261023_050231')
OUT = Path(__file__).resolve().parent

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

manifest = json.loads((RUN / 'FINAL_DELIVERY_MANIFEST.json').read_text())
original = {n: sha(RUN / n) for n in manifest['files']}
assert original == manifest['files'], 'Frozen run identity mismatch; stop.'
data = json.loads((RUN / 'SOURCE_CONSTRAINED_REFERENCE.json').read_text())
tasks = []
counts = Counter()
for number in range(1, 11):
    tid = f'CT{number:02}'
    records = []
    for family in ('deepseek', 'qwen'):
        for i, checked in enumerate(data['review_checks'][f'{tid}_{family}'].get('facts', []), 1):
            records.append({'id': f'{tid}_{family}_F{i:03}', 'family': family,
                            'original_fact_index': i - 1, 'checked_record': checked})
    links = []
    linked = set()
    for a in records:
        if a['family'] != 'deepseek':
            continue
        ac = a['checked_record']['citation']
        if not ac.get('traceable'):
            continue
        al = ac['location']
        for b in records:
            if b['family'] != 'qwen':
                continue
            bc = b['checked_record']['citation']
            if not bc.get('traceable'):
                continue
            bl = bc['location']
            identity_keys = ('source_doc_id', 'source_raw_sha256')
            location_keys = ('page', 'section_id', 'source_page_text_sha256')
            if any(ac.get(k) != bc.get(k) for k in identity_keys):
                continue
            if any(al.get(k) != bl.get(k) for k in location_keys):
                continue
            overlap = min(al['end'], bl['end']) - max(al['start'], bl['start'])
            if overlap <= 0:
                continue
            af, bf = a['checked_record']['fact'], b['checked_record']['fact']
            differing = [k for k in ('subject', 'predicate', 'value', 'date', 'date_type', 'amount', 'unit', 'status') if af.get(k) != bf.get(k)]
            links.append({'left': a['id'], 'right': b['id'],
                          'source_doc_id': ac['source_doc_id'], 'page': al.get('page'),
                          'section_id': al.get('section_id'), 'overlap_chars': overlap,
                          'left_span': [al['start'], al['end']], 'right_span': [bl['start'], bl['end']],
                          'literal_field_differences': differing,
                          'status': 'SHARED_SOURCE_SPAN_ONLY',
                          'semantic_equivalence': 'UNADJUDICATED', 'correctness': 'UNADJUDICATED'})
            linked.update((a['id'], b['id']))
    unlinked = [r['id'] for r in records if r['id'] not in linked]
    item = {'task_id': tid, 'facts': records, 'evidence_overlap_links': links,
            'unlinked_fact_ids': unlinked,
            'missing_review': not data['review_checks'][f'{tid}_deepseek'].get('facts'),
            'counts': {'fact_records': len(records), 'overlap_links': len(links),
                       'linked_fact_records': len(linked), 'unlinked_fact_records': len(unlinked)}}
    assert len(linked) + len(unlinked) == len(records)
    tasks.append(item)
    counts.update(item['counts'])
assert counts['fact_records'] == data['source_rule_counts']['fact_claims']
assert original == {n: sha(RUN / n) for n in original}, 'Original artifacts changed.'
result = {'purpose': 'Offline navigation aid for two-family source-constrained review',
          'input_path': str(RUN / 'SOURCE_CONSTRAINED_REFERENCE.json'),
          'input_sha256': sha(RUN / 'SOURCE_CONSTRAINED_REFERENCE.json'),
          'rules': ['Same task, different family, same original document hash and extracted page hash.',
                    'Any positive source-character overlap creates a navigation link; no similarity threshold.',
                    'Retain all many-to-many links; do not merge claims or infer consensus.',
                    'Literal field differences are not semantic disagreements.',
                    'No overlap or missing review is not an error or a correctness judgment.'],
          'totals': dict(counts), 'tasks': tasks,
          'new_model_requests': 0, 'new_terminal_Q': None,
          'independent_gold': False, 'original_artifacts_unchanged': True}
dest = OUT / 'EVIDENCE_POSITION_INDEX.json'
assert not dest.exists(), 'Do not overwrite an existing index.'
dest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
lines = ['# 双模型事实证据位置索引（零调用）', '',
         '本索引仅将引用同一原始文档、同一页且字符范围重叠的事实并排定位。它不更改原审计，不合并事实，不判定语义等价或正确，也不产生新的Q。', '',
         '|任务|事实记录|证据重叠关联|有关联的事实记录|无关联记录|', '|---|---:|---:|---:|---:|']
for t in tasks:
    c = t['counts']
    lines.append(f"|{t['task_id']}|{c['fact_records']}|{c['overlap_links']}|{c['linked_fact_records']}|{c['unlinked_fact_records']}|")
lines.extend(['', f"共{counts['fact_records']}条事实记录，{counts['overlap_links']}条多对多位置关联，覆盖{counts['linked_fact_records']}条记录；另{counts['unlinked_fact_records']}条保持未关联。关联数不是独立事实数，也不是共识数。", '',
              '## 结果边界', '',
              '- 原19份可解析核验结果与截断响应均保持原样；CT04缺少DeepSeek完整核验，不能用Qwen单侧结果补齐。',
              '- 原16个冲突项的4个机器共识候选与12个未决项保持原结论。',
              '- 共享证据可能描述不同事实，也可能支持不同解释；字面字段差异保留，语义判断仍待裁决。',
              '- 原任务缺少明确的最终问题及必要事实全集，完整性和相关性仍不可评分。未产生策略收益或排序结论。',
              '- 既有7事件保留开发曝光；双模型一致不构成独立Gold。', '',
              '## 下一步所需输入', '',
              '先从原有任务定义中确定每题最终问题和必要交付项，并在新版本中明确限定评分范围；若实际不存在，不能从模型答案倒推补题。之后才可核验逐项语义支持及比较策略交付物。本索引不启动补跑或付费实验。', '',
              '机读记录保留两侧原判断、引文、页码、字符位置及未执行的语义裁决标记，见 EVIDENCE_POSITION_INDEX.json。', '',
              f"输入SHA256：`{result['input_sha256']}`。原始交付清单{len(original)}项哈希全部一致。新增API调用0。"])
(OUT / 'ALIGNMENT_RESULT.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({'totals': dict(counts), 'original_files_verified': len(original), 'output': str(OUT)}, ensure_ascii=False))
