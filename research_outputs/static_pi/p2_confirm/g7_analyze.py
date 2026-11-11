#!/usr/bin/env python3
"""G7 one-shot analysis (预注册 P2C_G7_PREREG_FROZEN §5.2/§6/§7)。
一次性执行：不因中间结果调整任务/提示词/评分/统计方法。
§6.5 缺失处理按任务簇：单重复可评价→用该重复率；双重复均失效→主分析剔除并计数，S1零效应/S2最不利边界两种敏感性。
终点：①错配率（任务簇单侧精确符号翻转，MITM）②召回非劣（配对百分位bootstrap 1e4，单侧95%下界≥−0.05）
     ③Q_all非劣（同上；−0.05主界+−0.032敏感性）；C/L成本时延描述；不可判定三规则+最劣敏感性。"""
import json, re, sys, unicodedata
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
RUN = HERE / 'g7_runs' / 'G7_RESULTS.json'
FREEZE = HERE / 'g7_tasks' / 'G7_TASKSET_FREEZE.json'
ARMS = ('G6-M', 'G7')

CN_NUM = {'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,
          '壹':1,'贰':2,'叁':3,'肆':4,'伍':5,'陆':6,'柒':7,'捌':8,'玖':9}

def fw2hw(s):
    return s.translate({ord(f): ord(t) for f, t in zip('０１２３４５６７８９％，．（）［］',
                                                        '0123456789%,.()[]')})

def parse_cn_number(s):
    s = s.strip()
    if not s: return None
    if re.fullmatch(r'[0-9]+(\.[0-9]+)?', s): return float(s)
    units = {'十':10,'百':100,'千':1000}
    total, section, num, got = 0, 0, 0, False
    for ch in s:
        if ch in CN_NUM: num = CN_NUM[ch]; got = True
        elif ch in units: section += (num or 1) * units[ch]; num = 0; got = True
        elif ch == '万': section = (section + num) * 10000; total += section; section = 0; num = 0; got = True
        elif ch == '亿': section = (section + num) * 100000000; total += section; section = 0; num = 0; got = True
        elif ch in '点．.':
            frac = s[s.index(ch)+1:]
            if re.fullmatch(r'[0-9]+', frac) or all(c in CN_NUM for c in frac):
                ip = total + section + num; fp = 0; scale = 0.1
                for c in frac: fp += (CN_NUM.get(c, int(c) if c.isdigit() else 0)) * scale; scale /= 10
                return ip + fp
            return None
        else: return None
    return total + section + num if got else None

def canon_value(v):
    if v is None: return None
    s = fw2hw(str(v)).strip()
    s = re.sub(r'[\s，、；]', '', s)
    s = re.sub(r'[（(]([^）)]*)[）)]', r'\1', s)
    m = re.match(r'^(?:对)?(?:不少于|不超过)?([0-9.,]+|[零一二两三四五六七八九十百千万亿.]+)(万元|元|万|千|百万)?(?:的?罚款|罚款)?$', s)
    if m:
        n = m.group(1).replace(',', ''); unit = m.group(2) or ''
        val = parse_cn_number(n)
        if val is not None:
            mult = {'万': 1, '万元': 1, '千': 0.1, '百万': 100}.get(unit, 0.0001 if unit == '元' else 1)
            return ('NUM', round(val * mult, 4))
    return ('TXT', s)

def values_equal(a, b):
    ca, cb = canon_value(a), canon_value(b)
    return ca is not None and ca == cb

def norm_quote(q):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(q or '')))

def load_contracts():
    ts = json.loads(FREEZE.read_text('utf-8')); out = {}
    for t in ts['tasks']:
        c = json.loads((HERE / 'g7_tasks' / f"batch{t['batch']}" / 'contracts' /
                        f"TASK_CONTRACT_{t['task']}_v1.0.json").read_text('utf-8'))
        docs_norm = {}
        def strip_pageno(x): return re.sub(r'\n\s*\d+\s*(?=\n|$)', '', x)
        for d, meta in c['source_pages'].items():
            if 'normalized' in meta: txt = meta['normalized']
            elif 'pages' in meta: txt = ''.join(meta['pages'].values())
            else:
                fp = HERE / 'g7_tasks' / f"batch{t['batch']}" / meta['file']
                if not fp.exists(): fp = HERE / 'g7_tasks' / f"batch{t['batch']}" / 'raw' / Path(meta['file']).name
                txt = strip_pageno(fp.read_text(errors='ignore'))
                for corr in c.get('text_corrections', []):
                    if corr.get('file') == Path(meta['file']).name or corr.get('doc') == d:
                        pos = txt.find(corr['text_layer'])
                        if pos >= 0: txt = txt[:pos] + corr['printed'] + txt[pos+len(corr['text_layer']):]
            docs_norm[d] = re.sub(r'\s+', '', unicodedata.normalize('NFKC', txt))
        facts = {}
        for f in c['required_facts']:
            ad = f.get('allowed_docs') or f.get('allowed_citation_docs') or []
            evs = []
            for e in f.get('stage_evidence', []):
                evs.append(dict(doc=e['document_id'], span=norm_quote(e['evidence_span']),
                                estage=e.get('evidence_stage')))
            single = (len(ad) == 1)
            if single:
                for e in evs:
                    if e['estage'] is None: e['estage'] = f['fact_stage']
            facts[f['fact_id']] = dict(stage=f['fact_stage'], value=f['value'], single=single,
                                       allowed=ad, unknown=(f.get('fact_class') == 'unknown_boundary'), evs=evs)
        out[t['task']] = dict(facts=facts, docs_norm=docs_norm)
    return out

def char_overlap(a, b):
    return len(set(a) & set(b))

def match_span(quote_norm, doc, fe):
    cands = [e for e in fe['evs'] if e['doc'] == doc]
    if not cands: return None, 'undecidable'
    for e in cands:
        if quote_norm == e['span']: return e['estage'], 'exact'
    best, best_ov = None, 0.0
    for e in cands:
        if not (quote_norm and e['span']): continue
        ov = char_overlap(quote_norm, e['span'])
        r = ov / min(len(quote_norm), len(e['span']))
        if r >= 0.5 and ov > best_ov: best, best_ov = e, ov
    if best: return best['estage'], 'overlap'
    return None, 'undecidable'

def score_terminal(term, ct, undecidable_worst=False):
    """按冻结评分规则（G7_PROMPTS_FROZEN.scoring_implementation）：
    UNKNOWN gold槽不计入错配/召回/Q（描述性单列）；多文书槽仅Q；单文书槽参与错配/召回/Q（Q要求阶段正确）。"""
    facts, docs_norm = ct['facts'], ct['docs_norm']
    answers = {a.get('fact_id'): a for a in (term or {}).get('answers', []) if isinstance(a, dict)}
    unknowns = set(map(str, (term or {}).get('unknown_slots') or []))
    rec = dict(mismatch_num=0, mismatch_den=0, recall_num=0, recall_den=0,
               q_num=0, q_den=0, undecidable=[], wrong_value=[], missing=[],
               unk_correct=[], unk_answered=[], detail={})
    for fid, f in facts.items():
        if f['unknown']:
            if fid in unknowns: rec['unk_correct'].append(fid)
            elif fid in answers: rec['unk_answered'].append(fid)
            else: rec['missing'].append(fid)
            continue
        rec['q_den'] += 1
        a = answers.get(fid)
        if a is None or not str(a.get('value') or '').strip():
            rec['missing'].append(fid); rec['detail'][fid] = 'missing'
            if f['single']: rec['recall_den'] += 1; rec['mismatch_den'] += 1
            continue
        val_ok = values_equal(a.get('value'), f['value'])
        q = norm_quote(a.get('quote')); doc = a.get('doc')
        verbatim = bool(doc in docs_norm and q and q in docs_norm[doc])
        if not val_ok: rec['wrong_value'].append(fid)
        if f['single']:
            rec['recall_den'] += 1; rec['mismatch_den'] += 1
            if not verbatim:
                rec['mismatch_num'] += 1; rec['detail'][fid] = 'non_verbatim'; continue
            estage, how = match_span(q, doc, f)
            if estage is None:
                rec['undecidable'].append(fid); rec['detail'][fid] = 'undecidable'
                if undecidable_worst: rec['mismatch_num'] += 1
                elif val_ok: pass   # 不可判定：不计正确（三规则1）
                continue
            if estage != f['stage']:
                rec['mismatch_num'] += 1; rec['detail'][fid] = 'stage_mismatch'; continue
            rec['detail'][fid] = 'correct' if val_ok else 'wrong_value_stage_ok'
            if val_ok: rec['recall_num'] += 1; rec['q_num'] += 1
        else:
            if val_ok and verbatim: rec['q_num'] += 1
            rec['detail'][fid] = 'correct' if (val_ok and verbatim) else ('non_verbatim' if not verbatim else 'wrong_value')
    return rec

def rate(r, num, den):
    return (r[num] / r[den]) if r[den] else None

def block_rates(rec):
    return dict(mis=rate(rec, 'mismatch_num', 'mismatch_den'),
                recall=rate(rec, 'recall_num', 'recall_den'),
                q=rate(rec, 'q_num', 'q_den'))

def subsets_sums(arr):
    out = [0]
    for v in arr: out += [x + v for x in out]
    return out

def sign_flip_p(diffs):
    """单侧精确符号翻转（H1: G7−G6M<0）。返回 (p, obs_sum, n_nonzero)。"""
    import bisect
    d = [x for x in diffs if x != 0]
    n = len(d); obs = sum(diffs)
    if n == 0: return 1.0, obs, 0
    A, B = d[:n//2], d[n//2:]
    sa, sb = sorted(subsets_sums(A)), sorted(subsets_sums(B))
    cnt = 0
    for s in sa: cnt += bisect.bisect_right(sb, obs - s)
    return cnt / (2 ** n), obs, n

def bootstrap_lb(diffs, B=10000, seed=20261110, alpha=0.05):
    import random
    rng = random.Random(seed); n = len(diffs)
    ms = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return ms[int(alpha * B)], ms, rng

def main():
    contracts = load_contracts()
    results = json.loads(RUN.read_text('utf-8'))

    # ===== 块级→任务簇（§6.5）=====
    task_status = defaultdict(dict)     # task → rep → 'ok'|'failed'
    per_rep = defaultdict(lambda: defaultdict(dict))   # task → arm → rep → rates
    arm_recs = defaultdict(lambda: defaultdict(dict))  # task → arm → rep → rec（含undecidable等）
    for key, blk in results.items():
        t, rep = key.rsplit('_r', 1)
        if 'stopped' in blk or blk.get('shared_fault'):
            task_status[t][rep] = 'failed'; continue
        ok = True
        for arm in ARMS:
            term = blk['arms'].get(arm)
            if term is None: ok = False; continue
            rec = score_terminal(term, contracts[t])
            arm_recs[t][arm][rep] = rec
            per_rep[t][arm][rep] = block_rates(rec)
        task_status[t][rep] = 'ok' if ok else 'failed'

    dual_fail = sorted(t for t, d in task_status.items() if len(d) == 2 and all(s != 'ok' for s in d.values()))
    single_ok = sorted(t for t, d in task_status.items() if any(s == 'ok' for s in d.values()))
    included = [t for t in per_rep if per_rep[t]['G6-M'] and per_rep[t]['G7'] and t not in dual_fail]

    def task_means(t):
        out = {}
        for arm in ARMS:
            reps = per_rep[t][arm]
            for m in ('mis', 'recall', 'q'):
                vals = [v[m] for v in reps.values() if v[m] is not None]
                out[f'{m}_{arm}'] = sum(vals) / len(vals) if vals else None
        return out

    rows = []
    for t in sorted(included):
        tm = task_means(t)
        if None in tm.values():
            continue
        rows.append(dict(task=t, **tm,
                         n_reps_G6M=len(per_rep[t]['G6-M']), n_reps_G7=len(per_rep[t]['G7'])))
    D = {m: [r[f'{m}_G7'] - r[f'{m}_G6-M'] for r in rows] for m in ('mis', 'recall', 'q')}

    p_mis, obs_mis, n_nz = sign_flip_p(D['mis'])
    lb_rec, _, _ = bootstrap_lb(D['recall'])
    lb_q, _, _ = bootstrap_lb(D['q'])
    mean = lambda xs: (sum(xs) / len(xs)) if xs else None

    def analyze(Dm, Dr, Dq, tag):
        p, o, nz = sign_flip_p(Dm)
        lbr, _, _ = bootstrap_lb(Dr) if Dr else (None, [], None)
        lbq, _, _ = bootstrap_lb(Dq) if Dq else (None, [], None)
        return dict(tag=tag, n=len(Dm), mean_d_mis=mean(Dm), p_mis=p, eff_n=nz,
                    cond1=(p < 0.05 and (mean(Dm) or 0) < 0),
                    mean_d_recall=mean(Dr), lb_recall=lbr, cond2=(lbr is not None and lbr >= -0.05),
                    mean_d_q=mean(Dq), lb_q=lbq, cond3=(lbq is not None and lbq >= -0.05),
                    cond3_m32=(lbq is not None and lbq >= -0.032),
                    joint=(p < 0.05 and (mean(Dm) or 0) < 0 and lbr is not None and lbr >= -0.05
                           and lbq is not None and lbq >= -0.05))

    main_res = analyze(D['mis'], D['recall'], D['q'], 'main')
    # S1 零效应插补（仅补双重复失效任务，d=0）
    n_ex = len(dual_fail)
    s1 = analyze(D['mis'] + [0.0]*n_ex, D['recall'] + [0.0]*n_ex, D['q'] + [0.0]*n_ex, 'S1_zero')
    # S2 对G7最不利边界插补
    s2 = analyze(D['mis'] + [1.0]*n_ex, D['recall'] + [-1.0]*n_ex, D['q'] + [-1.0]*n_ex, 'S2_worst')

    # 不可判定最劣敏感性：全部不可判定改判错配后重算（需逐块重算）
    worst_rows = []
    for t in sorted(included):
        vals = []
        for arm in ARMS:
            per = []
            for rep, rec0 in arm_recs[t][arm].items():
                rec = score_terminal(results[f'{t}_r{rep}']['arms'][arm], contracts[t], undecidable_worst=True)
                per.append(block_rates(rec)['mis'])
            vals.append(sum(per) / len(per))
        worst_rows.append(vals[1] - vals[0])
    p_worst, obs_worst, nz_worst = sign_flip_p(worst_rows)

    # 不可判定分臂统计
    und = {a: sum(len(r['undecidable']) for t in arm_recs for rep, r in arm_recs[t][a].items()) for a in ARMS}
    den = {a: sum(r['mismatch_den'] for t in arm_recs for rep, r in arm_recs[t][a].items()) for a in ARMS}

    # ===== C/L 成本时延（账本）=====
    ledger = [json.loads(l) for l in (HERE / 'g7_runs' / 'LEDGER.jsonl').read_text('utf-8').splitlines() if l.strip()]
    done = [r for r in ledger if r.get('phase') == 'done']
    cost = {}
    for arm_key in ('shared', 'G6-M', 'G7'):
        sub = [r for r in done if r.get('arm') == arm_key]
        cost[arm_key] = dict(calls=len(sub),
                             tokens_in=sum(r.get('in') or 0 for r in sub),
                             tokens_out=sum(r.get('out') or 0 for r in sub),
                             yuan_accounting=round(sum(r.get('yuan_accounting') or 0 for r in sub), 4),
                             yuan_marginal=round(sum(r.get('yuan_marginal') or 0 for r in sub), 4))
    kinds = defaultdict(lambda: dict(calls=0, tokens=0, yuan=0.0))
    for r in done:
        k = r.get('kind') or 'normal'
        kinds[k]['calls'] += 1
        kinds[k]['tokens'] += (r.get('in') or 0) + (r.get('out') or 0)
        kinds[k]['yuan'] += r.get('yuan_accounting') or 0
    # 区组墙钟（秒，1s分辨率；块内首末调用时间差）
    block_wall = {}
    for key, blk in results.items():
        sub = [r for r in done if r.get('task') == key.rsplit('_r', 1)[0] and str(r.get('rep')) == key.rsplit('_r', 1)[1]]
        ts = sorted(r['ts'] for r in sub)
        if len(ts) >= 2:
            from datetime import datetime
            f = lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%S')
            block_wall[key] = (f(ts[-1]) - f(ts[0])).total_seconds()
    reanchor_stats = dict(
        blocks_with_g7=len([1 for v in results.values() if 'arms' in v]),
        reanchor_calls=sum((v.get('audit') or {}).get('G7', {}).get('reanchor_calls') or 0
                           for v in results.values() if 'audit' in v),
        verify_calls=sum((v.get('audit') or {}).get('G7', {}).get('verify_calls') or 0
                         for v in results.values() if 'audit' in v),
        final_failed_total=sum(len((v.get('audit') or {}).get('G7', {}).get('final_failed') or [])
                               for v in results.values() if 'audit' in v))

    out = dict(
        n_tasks_total=len(task_status), n_included=len(rows),
        dual_failed_tasks=dual_fail, n_dual_failed=len(dual_fail),
        single_rep_tasks=[t for t in single_ok if len([s for s in task_status[t].values() if s == 'ok']) == 1],
        main=main_res, sensitivity_S1=s1, sensitivity_S2=s2,
        undecidable_sensitivity=dict(p=p_worst, mean_d=mean(worst_rows), eff_n=nz_worst,
                                     direction_changed=(p_worst >= 0.05)),
        undecidable=dict(G6M=und['G6-M'], G7=und['G7'],
                         rate_G6M=(und['G6-M'] / den['G6-M']) if den['G6-M'] else None,
                         rate_G7=(und['G7'] / den['G7']) if den['G7'] else None),
        cost=cost, kinds=dict(kinds), block_wall_sec=dict(mean=mean(list(block_wall.values())),
                                                          n=len(block_wall)),
        reanchor=reanchor_stats,
        per_task=rows)
    print(json.dumps({k: v for k, v in out.items() if k != 'per_task'}, ensure_ascii=False, indent=1))
    (HERE / 'g7_runs' / 'G7_ANALYSIS_MAIN.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), 'utf-8')
    print('\nper-task rows → g7_runs/G7_ANALYSIS_MAIN.json')

if __name__ == '__main__':
    main()
