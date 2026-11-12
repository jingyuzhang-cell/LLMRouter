#!/usr/bin/env python3
"""V5 Gold 批量构建共享模块（工作线B）。零API调用。
流程：既有事实值 → 在任务文档内 grep 锚定原文行 → 组包（舜天模板）→ 签收表。
锚定结果仅供人工签收复核；未命中标记 PENDING_DOC_CHECK。
"""
import json, csv, os, re, subprocess

def norm(s):
    return re.sub(r'[\s,，、（）()〔〕\[\]]+', '', str(s))

def anchor(value_tokens, doc_paths, ctx=28):
    """在文档中锚定包含全部 token（归一化后子串）的原文片段。"""
    for p in doc_paths:
        try:
            text = open(p, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        flat = norm(text)
        toks = [norm(t) for t in value_tokens if norm(t)]
        if not toks:
            continue
        # 找到首个 token 位置，验证其余 token 在 ±400 窗口内
        for t in toks:
            i = flat.find(t)
            if i < 0:
                break
        else:
            i = flat.find(toks[0])
            lo, hi = max(0, i - 60), min(len(flat), i + 400)
            window = flat[lo:hi]
            if all(t in window for t in toks):
                # 回映射到原文近似片段：直接给归一化窗口前 ctx 字
                span = window[max(0, window.find(toks[0]) - 20):window.find(toks[0]) + ctx + 20]
                return os.path.basename(p), span
    return None, None

def build_package(task_id, company, doc_paths, nodes, slots, unknowns, dropped,
                  extra=None, status='DRAFT_FOR_HUMAN_SIGNOFF_v1.0'):
    docs = {}
    for p in doc_paths:
        import hashlib
        docs[os.path.basename(p)] = {
            'path': p,
            'sha256': hashlib.sha256(open(p, 'rb').read()).hexdigest()}
    pkg = dict(task_id=task_id, company=company, status=status,
               template_ref='../st_shun/V5_GOLD_ST_SHUN_DRAFT.json',
               docs=docs,
               dag=dict(nodes=nodes), slots=slots,
               unknown_boundary=unknowns, dropped_slots=dropped,
               scoring_contract=dict(
                   n_scored_slots=len(slots), n_unknown=len(unknowns),
                   catastrophe='TP_ratio ≤ 0.15',
                   normalization='同舜天合同(沿用E04_P2)',
                   composite_rule='同舜天合同v2', derived_rule='同舜天合同v2',
                   semantic_rule='同舜天合同v2', unknown_rule='同舜天合同v2',
                   tp_definition='终端输出对照scored slots；下游不复制上游'))
    if extra:
        pkg.update(extra)
    out_dir = task_id.lower().replace('-', '_')
    os.makedirs(out_dir, exist_ok=True)
    json.dump(pkg, open(f'{out_dir}/V5_GOLD_{task_id}_DRAFT.json', 'w'),
              indent=1, ensure_ascii=False)
    with open(f'{out_dir}/{task_id}_SIGNOFF_WORKSHEET.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['slot_id', 'node', 'kind', 'source', 'value/expected', 'doc',
                    'span', 'ai_verdict', 'human_verdict(PASS/REVISE/DROP)', 'human_note'])
        for s in slots:
            w.writerow([s['slot_id'], s['node'], s['kind'], s.get('source', 'SILVER_V23A'),
                        s['value'], s.get('doc', ''), s.get('span', ''),
                        s.get('ai_verdict', ''), '', ''])
        for u in unknowns:
            w.writerow([u['slot_id'], u['node'], 'UNKNOWN', 'SILVER_V23A',
                        u['value'], u.get('doc', ''), u.get('note', ''),
                        'PENDING_HUMAN', '', ''])
    return len(slots), len(unknowns)
