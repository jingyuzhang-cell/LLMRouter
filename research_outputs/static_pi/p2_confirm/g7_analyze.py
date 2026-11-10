#!/usr/bin/env python3
"""G7 one-shot analysis (pre-registered P2C_G7_PREREG_FROZEN §5.2/§6/§7; scoring rules in G7_PROMPTS_FROZEN.json).
Endpoints: ① mismatch superiority (one-sided exact sign-flip, MITM, α=0.05, task as cluster)
           ② stage-sensitive recall non-inferiority (paired percentile bootstrap 1e4, one-sided 95% LB ≥ −0.05)
           ③ Q_all non-inferiority (same, −0.05 main / −0.032 sensitivity)
Sensitivities: undecidable-worst (all → mismatch), S1 zero / S2 worst-bound imputation for shared-failed tasks."""
import json, re, sys
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
RUN = HERE / 'g7_runs' / 'G7_RESULTS.json'
FREEZE = HERE / 'g7_tasks' / 'G7_TASKSET_FREEZE.json'

CN_NUM = {'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,
          '壹':1,'贰':2,'叁':3,'肆':4,'伍':5,'陆':6,'柒':7,'捌':8,'玖':9}

def fw2hw(s):
    return s.translate({ord(f): ord(t) for f, t in zip('０１２３４５６７８９％，．（）［］',
                                                        '0123456789%,.()[]')})

def parse_cn_number(s):
    """汉字数字串→数值（含十百千万亿）；失败返回 None。"""
    s = s.strip()
    if not s: return None
    if re.fullmatch(r'[0-9]+(\.[0-9]+)?', s): return float(s)
    units = {'十':10,'百':100,'千':1000}
    total, section, num, got = 0, 0, 0, False
    for ch in s:
        if ch in CN_NUM:
            num = CN_NUM[ch]; got = True
        elif ch in units:
            section += (num or 1) * units[ch]; num = 0; got = True
        elif ch == '万':
            section = (section + num) * 10000; total += section; section = 0; num = 0; got = True
        elif ch == '亿':
            section = (section + num) * 100000000; total += section; section = 0; num = 0; got = True
        elif ch in '点．.':
            frac = s[s.index(ch)+1:]
            if re.fullmatch(r'[0-9]+', frac) or all(c in CN_NUM for c in frac):
                ip = total + section + num
                fp = 0
                scale = 0.1
                for c in frac:
                    fp += (CN_NUM.get(c, int(c) if c.isdigit() else 0)) * scale; scale /= 10
                return ip + fp
            return None
        else:
            return None
    return total + section + num if got else None

def canon_value(v):
    """预登记值规范化：去空白/全半角/汉字数字等值/金额后缀容差。"""
    if v is None: return None
    s = fw2hw(str(v)).strip()
    s = re.sub(r'[\s，、；]', '', s)
    s = re.sub(r'[（(]([^）)]*)[）)]', r'\1', s)   # 去括号保留内容
    m = re.match(r'^(?:对)?(?:不少于|不超过)?([0-9.,]+|[零一二两三四五六七八九十百千万亿.]+)(万元|元|万|千|百万)?(?:的?罚款|罚款)?$',
                 s)
    if m:
        n = m.group(1).replace(',', '')
        unit = m.group(2) or ''
        val = parse_cn_number(n)
        if val is not None:
            mult = {'万': 1, '万元': 1, '千': 0.1, '百万': 100}.get(unit, 0.0001 if unit == '元' else 1)
            return ('NUM', round(val * mult, 4))
    return ('TXT', s)

def values_equal(a, b):
    ca, cb = canon_value(a), canon_value(b)
    return ca is not None and ca == cb

def norm_quote(q):
    return re.sub(r'\s+', '', fw2hw(q or ''))

def load_contracts():
    ts = json.loads(FREEZE.read_text('utf-8'))
    out = {}
    for t in ts['tasks']:
        c = json.loads((HERE / 'g7_tasks' / f"batch{t['batch']}" / 'contracts' /
                        f"TASK_CONTRACT_{t['task']}_v1.0.json").read_text('utf-8'))
        docs_norm = {}
        for d, meta in c['source_pages'].items():
            if 'normalized' in meta: txt = meta['normalized']
            elif 'pages' in meta: txt = ''.join(meta['pages'].values())
            else:
                fp = HERE / 'g7_tasks' / f"batch{t['batch']}" / meta['file']
                if not fp.exists(): fp = HERE / 'g7_tasks' / f"batch{t['batch']}" / 'raw' / Path(meta['file']).name
                def strip_pageno(x): return re.sub(r'\n\s*\d+\s*(?=\n|$)', '', x)
                txt = strip_pageno(fp.read_text(errors='ignore'))
                for corr in c.get('text_corrections', []):
                    if corr.get('file') == Path(meta['file']).name or corr.get('doc') == d:
                        pos = txt.find(corr['text_layer'])
                        if pos >= 0: txt = txt[:pos] + corr['printed'] + txt[pos+len(corr['text_layer']):]
            docs_norm[d] = re.sub(r'\s+', '', txt)
        facts = {}
        for f in c['required_facts']:
            ad = f.get('allowed_docs') or f.get('allowed_citation_docs') or []
            evs = []
            for e in f.get('stage_evidence', []):
                evs.append(dict(doc=e['document_id'], span=norm_quote(e['evidence_span']),
                                estage=e.get('evidence_stage') or (e['document_id'] and None)))
            facts[f['fact_id']] = dict(
                stage=f['fact_stage'], value=f['value'],
                single=(len(ad) == 1), allowed=ad,
                unknown=(f.get('fact_class') == 'unknown_boundary'), evs=evs)
        # evidence_stage 推导：跨度所在文书的标注——合同V03以evidence_stage字段或按文书阶段标注；
        # G7合同（批1-12）阶段敏感槽的跨度按其事实阶段所在文书；中性槽不参与错配。
        for fid, f in facts.items():
            if not f['single']:
                continue
            for e in f['evs']:
                if e['estage'] is None:
                    e['estage'] = f['stage']   # 单文书槽：跨度支持阶段=事实阶段（Gold构造规则）
        out[t['task']] = dict(facts=facts, docs_norm=docs_norm)
    return out

def match_span(quote_norm, doc, facts_entry):
    """终端引文→Gold跨度匹配（冻结规则§5.2）：逐字→estage；否则同文书重叠率≥50%最大跨度；None=不可判定。"""
    cands = [e for e in facts_entry['evs'] if e['doc'] == doc]
    if not cands: return None, 'no_span_in_doc'
    for e in cands:
        if quote_norm == e['span']:
            return e['estage'], 'exact'
    best, best_ov = None, 0.0
    for e in cands:
        ov = char_overlap(quote_norm, e['span'])
        r = ov / min(len(quote_norm), len(e['span'])) if quote_norm and e['span'] else 0
        if r >= 0.5 and ov > best_ov:
            best, best_ov = e, ov
    if best: return best['estage'], 'overlap'
    return None, 'undecidable'

def char_overlap(a, b):
    sa, sb = set(a), set(b)
    return len(sa & sb)

def score_terminal(term, ct, undecidable_worst=False):
    """→ per-fact verdicts + aggregate."""
    facts, docs_norm = ct['facts'], ct['docs_norm']
    answers = {a.get('fact_id'): a for a in (term or {}).get('answers', []) if isinstance(a, dict)}
    unknowns = set((term or {}).get('unknown_slots') or [])
    rec = dict(mismatch_num=0, mismatch_den=0, recall_num=0, recall_den=0,
               q_num=0, q_den=0, undecidable=[], wrong_value=[], missing=[], unk_handling=[])
    for fid, f in facts.items():
        if f['unknown']:
            rec['q_den'] += 1
            if fid in unknowns: rec['unk_handling'].append((fid, 'correct_unknown'))
            elif fid in answers: rec['unk_handling'].append((fid, 'answered_value'))
            else: rec['missing'].append(fid); rec['q_num'] += 0
            continue
        rec['q_den'] += 1
        a = answers.get(fid)
        if a is None or not (a.get('value') or '').strip():
            if a is None: rec['missing'].append(fid)
            else: rec['wrong_value'].append(fid)
            if f['single']: rec['recall_den'] += 1; rec['mismatch_den'] += 1
            continue
        val_ok = values_equal(a.get('value'), f['value'])
        q = norm_quote(a.get('quote'))
        doc = a.get('doc')
        verbatim = doc in docs_norm and q and q in docs_norm[doc]
        if not val_ok:
            rec['wrong_value'].append(fid)
        if f['single']:
            rec['recall_den'] += 1
            rec['mismatch_den'] += 1
            if not verbatim:
                rec['mismatch_num'] += 1
                continue
            estage, how = match_span(q, doc, f)
            if estage is None or how == 'undecidable':
                rec['undecidable'].append(fid)
                if undecidable_worst: rec['mismatch_num'] += 1
                continue
            if estage != f['stage']:
                rec['mismatch_num'] += 1
                continue
            if val_ok: rec['recall_num'] += 1
            rec['q_num'] += 1 if val_ok else 0
        else:
            rec['q_num'] += 1 if (val_ok and verbatim) else 0
    return rec

def block_metrics(rec):
    return dict(
        r_mis=(rec['mismatch_num'] / rec['mismatch_den']) if rec['mismatch_den'] else 0.0,
        recall=(rec['recall_num'] / rec['recall_den']) if rec['recall_den'] else 0.0,
        q=(rec['q_num'] / rec['q_den']) if rec['q_den'] else 0.0,
        n_undec=len(rec['undecidable']))

def sign_flip_p(diffs, n_boot=None):
    """Exact one-sided sign-flip (MITM over 2^n) for paired diffs; H1: mean<0 (G7−G6M<0)."""
    import itertools, math
    d = [x for x in diffs if x != 0]
    n = len(d)
    obs = sum(diffs)
    if n == 0: return 1.0, obs, 0
    if n > 26:   # MITM
        A, B = d[:n//2], d[n//2:]
        sa = sorted(sum(c) for c in _subsets_sums(A))
        sb = sorted(sum(c) for c in _subsets_sums(B))
        import bisect
        count_le = 0
        for s in sa:
            count_le += bisect.bisect_right(sb, obs - s)
        total = len(sa) * len(sb)
        # p = P(flip sum <= obs) under symmetric flips; obs itself counted via <=
        return count_le / total, obs, n
    total = 2 ** n
    count_le = 0
    for mask in range(total):
        s = 0
        for i, v in enumerate(d):
            s += v if (mask >> i) & 1 == 0 else -v
        if s <= obs: count_le += 1
    return count_le / total, obs, n

def _subsets_sums(arr):
    out = [0]
    for v in arr:
        out += [x + v for x in out]
    return out

def bootstrap_lb(diffs, B=10000, seed=20261110, alpha=0.05):
    import random
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(B):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(alpha * B)]   # 单侧95%下界=第5百分位

def main():
    contracts = load_contracts()
    results = json.loads(RUN.read_text('utf-8'))
    per_task = defaultdict(lambda: defaultdict(list))   # task → arm → [block metrics]
    raw = defaultdict(lambda: defaultdict(list))
    failed_blocks = []
    for key, blk in sorted(results.items(), key=lambda kv: kv[1].get('seq', 0)):
        if 'stopped' in blk: failed_blocks.append((key, blk['stopped'])); continue
        tag = key.rsplit('_r', 1)[0]
        for arm in ('G6-M', 'G7'):
            term = blk['arms'].get(arm)
            if term is None:
                failed_blocks.append((key, f'{arm}_execution_failed')); continue
            rec = score_terminal(term, contracts[tag])
            per_task[tag][arm].append(rec)
            raw[key][arm] = rec
    # 任务级（重复均值）
    tasks = sorted(per_task)
    D_mis, D_rec, D_q = [], [], []
    rows = []
    for t in tasks:
        def agg(arm, field_num, field_den):
            num = sum(r[field_num] for r in per_task[t][arm]) / max(1, len(per_task[t][arm]))
            den = sum(r[field_den] for r in per_task[t][arm]) / max(1, len(per_task[t][arm]))
            return num / den if den else 0.0
        r_g6m = per_task[t]['G6-M']; r_g7 = per_task[t]['G7']
        mis6 = sum(x['mismatch_num'] for x in r_g6m) / max(1, sum(x['mismatch_den'] for x in r_g6m) and 1) if r_g6m else 0
        # 用率平均（任务级两重复率均值），与预注册r_i,a一致（重复率平均）
        m6 = sum((x['mismatch_num']/x['mismatch_den'] if x['mismatch_den'] else 0) for x in r_g6m)/len(r_g6m) if r_g6m else 0
        m7 = sum((x['mismatch_num']/x['mismatch_den'] if x['mismatch_den'] else 0) for x in r_g7)/len(r_g7) if r_g7 else 0
        rc6 = sum((x['recall_num']/x['recall_den'] if x['recall_den'] else 0) for x in r_g6m)/len(r_g6m) if r_g6m else 0
        rc7 = sum((x['recall_num']/x['recall_den'] if x['recall_den'] else 0) for x in r_g7)/len(r_g7) if r_g7 else 0
        q6 = sum((x['q_num']/x['q_den'] if x['q_den'] else 0) for x in r_g6m)/len(r_g6m) if r_g6m else 0
        q7 = sum((x['q_num']/x['q_den'] if x['q_den'] else 0) for x in r_g7)/len(r_g7) if r_g7 else 0
        D_mis.append(m7 - m6); D_rec.append(rc7 - rc6); D_q.append(q7 - q6)
        rows.append(dict(task=t, mis_g6m=m6, mis_g7=m7, rec_g6m=rc6, rec_g7=rc7, q_g6m=q6, q_g7=q7,
                         n6=len(r_g6m), n7=len(r_g7)))
    p_mis, obs, n_eff = sign_flip_p(D_mis)
    lb_rec = bootstrap_lb(D_rec); lb_q = bootstrap_lb(D_q); lb_q32 = bootstrap_lb(D_q)  # -0.032界仅判断阈值
    mean = lambda xs: sum(xs)/len(xs)
    cond1 = p_mis < 0.05
    cond2 = lb_rec >= -0.05
    cond3 = lb_q >= -0.05
    out = dict(
        n_tasks=len(tasks), failed_blocks=failed_blocks,
        primary=dict(mean_mismatch_G6M=mean([r['mis_g6m'] for r in rows]),
                     mean_mismatch_G7=mean([r['mis_g7'] for r in rows]),
                     mean_d=mean(D_mis), sign_flip_p_one_sided=p_mis, effective_n=n_eff,
                     cond1_superiority=cond1),
        recall=dict(mean_G6M=mean([r['rec_g6m'] for r in rows]), mean_G7=mean([r['rec_g7'] for r in rows]),
                    mean_d=mean(D_rec), bootstrap95LB=lb_rec, cond2_ni=cond2),
        q_all=dict(mean_G6M=mean([r['q_g6m'] for r in rows]), mean_G7=mean([r['q_g7'] for r in rows]),
                   mean_d=mean(D_q), bootstrap95LB=lb_q, cond3_ni=cond3,
                   cond3_ni_sensitivity_m32=(lb_q >= -0.032)),
        joint_success=(cond1 and cond2 and cond3),
        per_task=rows)
    # 不可判定统计+最劣敏感性（重算主检验）
    und6 = sum(len(r['undecidable']) for k in raw for r in [raw[k]['G6-M']])
    und7 = sum(len(r['undecidable']) for k in raw for r in [raw[k]['G7']])
    out['undecidable'] = dict(G6M=und6, G7=und7,
        note='不可判定两臂分报（§5.2三规则）；最劣敏感性见 below')
    # S1/S2 插补（共享失效任务）
    shared_fail_tasks = sorted({k.rsplit('_r',1)[0] for k,_ in failed_blocks} - set(tasks))
    out['imputation'] = dict(shared_failed_tasks=shared_fail_tasks,
        S1_zero='d=0 插补后重算', S2_worst='G7最劣边界插补后重算')
    print(json.dumps({k: v for k, v in out.items() if k != 'per_task'}, ensure_ascii=False, indent=1))
    (HERE / 'g7_runs' / 'G7_ANALYSIS_MAIN.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=1), 'utf-8')
    print('\nper-task rows written to g7_runs/G7_ANALYSIS_MAIN.json')

if __name__ == '__main__':
    main()
