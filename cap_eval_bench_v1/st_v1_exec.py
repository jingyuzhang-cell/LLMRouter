"""Structured Transfer V1.2 — execution (5 paired blocks, shared n1).

Frozen prereg: STRUCTURED_TRANSFER_PREREG_V1_2.md
Deviation D1 (operator-approved 2026-11-01): A-arm n3/n4 receive n2[:3000]
  (V7's DEPS/template key mismatch starved them with empty input — byte-verified).
Scoring: v3 (value-level TP provenance + deduped value-level FP). No n9 gate.

Per block: 1 shared n1 call -> A arm 9 calls (n2..n10) + B arm 9 calls (n2..n10) = 19.
"""
import json, re, sys, time, hashlib
sys.path.insert(0, '/root/capital_opinion_pilot')
sys.path.insert(0, '/root/cap_eval_bench_v1')
from pilot_common import Meter, BudgetExceeded
import b_arm_budget as BB          # B-arm prompt construction = budget source of truth

SYS_DOWN = '你是一个严谨的资本市场调查助手。只输出JSON。不要编造。无法确认的标UNKNOWN。'
MAXTOK = {'n1': 4000, 'n2': 768, 'n3': 768, 'n4': 768, 'n5': 768,
          'n6': 768, 'n7': 768, 'n8': 768, 'n9': 2000, 'n10': 2000}
MODEL = 'glm53flash'

zeda = json.load(open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))
EV_FULL = ' '.join(d['text'] for d in zeda['docs'])
WINDOW = EV_FULL[:4000]
N1_TEMPLATE = open('n1_revised_prompt.txt').read().split('文档：')[0]
silver = json.load(open('dd_v51_silver_facts.json'))
VALID = [f for f in silver if f['fid'] != 'A04']
norm = BB.norm

meter = Meter(ledger_path='st_v1_LEDGER.jsonl', max_calls=105, max_guaranteed_actual=400000)

# ── D2/D3 DEVIATION (operator-approved 2026-11-02): coding-plan quota exhausted;
#    resource package covers glm-5.3 ONLY, on the standard endpoint, thinking forced.
#    Both arms use glm-5.3 + thinking low -> single-variable (transfer) design intact.
#    Token ceiling raised 250K->400K (thinking inflation; package has 20M). ──
import types as _types, urllib.request as _ureq
_STD_URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
_STD_KEY = open('/root/.zhipu_std_key').read().strip()
_MODEL_MAP = {'glm53flash': 'glm-5.3', 'glm53': 'glm-5.3'}
def _std_transport(self, alias, system, user, max_tokens, timeout_s):
    body = {'model': _MODEL_MAP.get(alias, 'glm-5.3'), 'max_tokens': max_tokens,
            'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low',
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': user}]}
    req = _ureq.Request(_STD_URL, data=json.dumps(body).encode(), method='POST')
    req.add_header('content-type', 'application/json')
    req.add_header('authorization', 'Bearer ' + _STD_KEY)
    t0 = time.monotonic()
    with _ureq.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    ch = d['choices'][0]
    u = d.get('usage', {})
    stop = {'stop': 'end_turn', 'length': 'max_tokens'}.get(ch.get('finish_reason'), ch.get('finish_reason'))
    return {'usage': {'input_tokens': u.get('prompt_tokens', 0),
                      'output_tokens': u.get('completion_tokens', 0)},
            'text': ch.get('message', {}).get('content') or '',
            'latency_s': time.monotonic() - t0,
            'stop_reason': stop}
meter._transport = _types.MethodType(_std_transport, meter)

def safe_call(*a, **kw):
    """Retry transient transport failures (429/5xx). A failed transport is NOT
    recorded by Meter, so retrying cannot double-charge."""
    import urllib.error
    last = None
    for attempt, delay in enumerate((0, 20, 45, 90), 1):
        if delay: time.sleep(delay)
        try:
            return meter.call(*a, **kw)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
            print(f'    [retry {attempt}] HTTP {e.code} on {kw.get("purpose","?")}')
    raise last

def parse_n9_supported(text):
    """n9 may return {"supported":[...]} OR [{"fact_id":...,"status":"supported"}].
    Return the set of supported fact_ids; unknown shapes -> empty set (caller falls back)."""
    o = try_json(text)
    out = set()
    if isinstance(o, dict):
        for k in ('supported', 'SUPPORTED', '支持'):
            v = o.get(k)
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, str): out.add(x)
                    elif isinstance(x, dict) and x.get('fact_id'): out.add(x['fact_id'])
    elif isinstance(o, list):
        for x in o:
            if isinstance(x, dict):
                fid = x.get('fact_id') or x.get('id')
                st = str(x.get('status') or x.get('verdict') or '').lower()
                if fid and st.startswith(('support', 'support', '确认', '已确认', 'verif')): out.add(fid)
            elif isinstance(x, str): out.add(x)
    return out

def strip(t):
    c = (t or '').strip()
    if c.startswith('```'):
        ls = c.split('\n')[1:]
        if ls and ls[-1].strip() == '```': ls = ls[:-1]
        c = '\n'.join(ls).strip()
    return c

def try_json(t):
    try: return BB.extract_json(t)
    except Exception: return None

# ───────────────────────── A arm (V7 contracts; D1 wiring fix) ─────────────────────────
def a_prompt(nid, up, bypass=None):
    if nid == 'n2':
        return f'{SYS_DOWN}\n基于以下初步提取结果，进一步补充遗漏的事实：\n{str(up.get("n1",""))[:3000]}\n输出JSON，字段 facts。'
    if nid == 'n3':
        return f'{SYS_DOWN}\n根据以下提取事实整理时间线（按日期排序）：\n{str(up.get("n2",""))[:3000]}\n输出JSON，字段 timeline。'
    if nid == 'n4':
        return f'{SYS_DOWN}\n汇总所有金额数据（虚增、罚款、关联交易、理财）：\n{str(up.get("n2",""))[:3000]}\n输出JSON，字段 amounts。'
    if nid == 'n5':
        return f'{SYS_DOWN}\n梳理处罚决定（处罚种类、对象、金额、依据）：\n{str(up.get("n2",""))[:2500]}\n输出JSON，字段 penalties。'
    if nid == 'n6':
        return f'{SYS_DOWN}\n识别涉事主体及关系：\n{str(up.get("n2",""))[:3000]}\n输出JSON，字段 entities。'
    if nid == 'n7':
        return (f'{SYS_DOWN}\n时间线阶段复核与划分：\n时间线:{str(up.get("n3",""))[:2000]}\n'
                f'主体:{str(up.get("n6",""))[:1500]}\n输出JSON，字段 stages。')
    if nid == 'n8':
        return f'{SYS_DOWN}\n金额交叉核验：\n{str(up.get("n4",""))[:2500]}\n输出JSON，字段 amounts_checked。'
    if nid == 'n9':
        p = str(up.get('n5', ''))[:1500]; s = str(up.get('n7', ''))[:1500]; a = str(up.get('n8', ''))[:1000]
        b = str(bypass)[:3000] if bypass else ''
        return (f'{SYS_DOWN}\n跨来源核验。你有两份输入：\n'
                f'【输入A：初始结构化提取（直接来自源头文档）】\n{b}\n\n'
                f'【输入B：中间节点核验结果】\n处罚:{p}\n阶段:{s}\n核验:{a}\n\n'
                f'请核验输入A中的全部事实（日期、金额、处罚、实体），结合输入B进行交叉验证。\n'
                f'输出JSON，字段 verified_facts，数组。每条事实保留原始值。')
    return (f'{SYS_DOWN}\n综合全部核验事实，输出完整调查报告。\n'
            f'要求：报告必须逐项包含以下内容——\n'
            f'1. 所有日期（事件日期 + 会计期间截止日）\n'
            f'2. 所有金额（虚增收入/利润 + 罚款 + 关联交易 + 理财余额）\n'
            f'3. 所有处罚类型（罚款/警告/市场禁入/责令改正）\n'
            f'4. 所有涉事公司\n'
            f'每项标注核验状态（已核验/UNKNOWN）。\n\n'
            f'核验事实：\n{str(up.get("n9",""))[:6000]}\n输出JSON，字段 report。')

A_DEPS = {'n2': ['n1'], 'n3': ['n2'], 'n4': ['n2'], 'n5': ['n2'], 'n6': ['n2'],
          'n7': ['n3', 'n6'], 'n8': ['n4'], 'n9': ['n5', 'n7', 'n8'], 'n10': ['n9']}

def run_arm_a(bname, n1_out, sink):
    up = {'n1': n1_out}
    for nid in ['n2', 'n3', 'n4', 'n5', 'n6', 'n7', 'n8', 'n9', 'n10']:
        ud = {d: up.get(d, '') for d in A_DEPS[nid]}
        pr = a_prompt(nid, ud, up.get('n1', '') if nid == 'n9' else None)
        rec, text = safe_call(MODEL, SYS_DOWN, pr, max_tokens=MAXTOK[nid],
                               purpose=f'{bname}:A:{nid}', timeout_s=120)
        up[nid] = text
        sink.append({'arm': 'A', 'node': nid, 'text': text, 'usage': rec['usage'],
                     'stop': rec['stop_reason'], 'max_tokens': MAXTOK[nid],
                     'prompt_chars': rec['prompt_chars']})
    return up

# ───────────────────────── B arm (structured transfer) ─────────────────────────
def run_arm_b(bname, n1_out, sink):
    store = BB.build_store(n1_out, WINDOW, 10)
    P = BB.build_prompts(store, 10)
    up = {}
    out_by_node = {}
    for nid in ['n2', 'n3', 'n4', 'n5', 'n6']:
        sy, us = P[nid]
        rec, text = safe_call(MODEL, sy, us, max_tokens=MAXTOK[nid],
                               purpose=f'{bname}:B:{nid}', timeout_s=120)
        out_by_node[nid] = text
        sink.append({'arm': 'B', 'node': nid, 'text': text, 'usage': rec['usage'],
                     'stop': rec['stop_reason'], 'max_tokens': MAXTOK[nid],
                     'prompt_chars': rec['prompt_chars']})
    # n7 / n8: same templates as the budgeted ones, with real upstream content
    n7_user = (f'{SYS_DOWN}\n以下为时间线与主体归类的 fact_id 结果。任务：划分阶段并复核前后一致性。不得新增事实。'
               f'输出JSON，字段 {{"stages":[]}}。\n'
               + json.dumps({'timeline': str(out_by_node.get('n3', ''))[:2000],
                             'entities': str(out_by_node.get('n6', ''))[:1500]},
                            ensure_ascii=False, separators=(',', ':')))
    rec, text = safe_call(MODEL, SYS_DOWN, n7_user, max_tokens=MAXTOK['n7'],
                           purpose=f'{bname}:B:n7', timeout_s=120)
    out_by_node['n7'] = text
    sink.append({'arm': 'B', 'node': 'n7', 'text': text, 'usage': rec['usage'],
                 'stop': rec['stop_reason'], 'max_tokens': MAXTOK['n7'],
                 'prompt_chars': rec['prompt_chars']})
    n8_user = (f'{SYS_DOWN}\n以下为金额归类结果。任务：核验同一 fact_role 下口径是否冲突（累计 vs 分年）。'
               f'不得新增事实。输出JSON，字段 {{"amounts_checked":[]}}。\n'
               + json.dumps({'amounts': str(out_by_node.get('n4', ''))[:2500]},
                            ensure_ascii=False, separators=(',', ':')))
    rec, text = safe_call(MODEL, SYS_DOWN, n8_user, max_tokens=MAXTOK['n8'],
                           purpose=f'{bname}:B:n8', timeout_s=120)
    out_by_node['n8'] = text
    sink.append({'arm': 'B', 'node': 'n8', 'text': text, 'usage': rec['usage'],
                 'stop': rec['stop_reason'], 'max_tokens': MAXTOK['n8'],
                 'prompt_chars': rec['prompt_chars']})
    # n9: full store + spans + quotes -> compact id lists
    sy9, us9 = P['n9']
    rec, text = safe_call(MODEL, sy9, us9, max_tokens=MAXTOK['n9'], purpose=f'{bname}:B:n9', timeout_s=120)
    out_by_node['n9'] = text
    sink.append({'arm': 'B', 'node': 'n9', 'text': text, 'usage': rec['usage'],
                 'stop': rec['stop_reason'], 'max_tokens': MAXTOK['n9'],
                 'prompt_chars': rec['prompt_chars']})
    # n10: only SUPPORTED facts
    sup = parse_n9_supported(text)
    byid = {r['fact_id']: r for r in store}
    fed = [byid[i] for i in sup if i in byid] or [r for r in store if r['provenance_status'] != 'UNVERIFIABLE_ABSENT']
    us10 = (f'{SYS_DOWN}\n以下为已核验支持的 facts。任务：组织完整调查报告，逐项包含所有日期、金额（保留原始数字与单位）、处罚、主体。'
            f'不得新增事实。输出JSON，字段 report。\n'
            + json.dumps([dict(fact_id=r['fact_id'], fact_type=r['fact_type'],
                               fact_role=r['fact_role'], value=r['value']) for r in fed],
                         ensure_ascii=False, separators=(',', ':'))
            + '\n输出JSON，字段 report。')
    rec, text = safe_call(MODEL, SYS_DOWN, us10, max_tokens=MAXTOK['n10'], purpose=f'{bname}:B:n10', timeout_s=120)
    out_by_node['n10'] = text
    sink.append({'arm': 'B', 'node': 'n10', 'text': text, 'usage': rec['usage'],
                 'stop': rec['stop_reason'], 'max_tokens': MAXTOK['n10'],
                 'prompt_chars': rec['prompt_chars']})
    return dict(store=store, out=out_by_node, n9_supported=sorted(sup),
                n10_fed=len(fed))

# ───────────────────────── v3 scoring ─────────────────────────
NUM = re.compile(r'\d[\d,，]*\.?\d*\s*(?:万元|亿元|万|亿|元|%)')
DATE = re.compile(r'\d{4}\s*[-年]\s*\d{1,2}\s*[-月]\s*\d{1,2}\s*日?')

def collect_values(o, acc=None):
    if acc is None: acc = []
    if isinstance(o, dict):
        for v in o.values(): collect_values(v, acc)
    elif isinstance(o, list):
        for v in o: collect_values(v, acc)
    elif isinstance(o, str): acc.append(o)
    else: acc.append(str(o))
    return acc

def variants(f):
    vs = [norm(f['value'])]
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
    if f['kind'] == 'date' and m:
        vs.append(norm(f'{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日'))
    return [v for v in vs if v]

def in_text(f, textn):
    return any(v in textn for v in variants(f))

def in_window(f):
    """v3 window rule: full forms, or elided date (M月D日) with the year in +/-120 chars."""
    n = norm(WINDOW)
    if any(v in n for v in variants(f)):
        return True
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
    if f['kind'] == 'date' and m:
        el = f'{int(m.group(2))}月{int(m.group(3))}日'
        yr = m.group(1) + '年'
        for mm in re.finditer(re.escape(el), WINDOW):
            if yr in WINDOW[max(0, mm.start() - 120):mm.end() + 120]:
                return True
    return False

def claims(rep):
    return [('num', re.sub(r'\s+', '', m.group(0))) for m in NUM.finditer(rep)] + \
           [('date', re.sub(r'\s+', '', m.group(0))) for m in DATE.finditer(rep)]

def claim_supported(c, textn):
    k, s = c
    cs = {s, s.replace(',', '').replace('，', '')}
    if k == 'date':
        m = re.match(r'(\d{4})[-年](\d{1,2})[-月](\d{1,2})', s)
        if m:
            y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
            cs |= {f'{y}年{mo}月{d}日', f'{y}-{mo:02d}-{d:02d}', f'{mo}月{d}日'}
    return any(norm(x) in textn for x in cs if x)

def score(n10_text, n1_text):
    obj = try_json(n10_text)
    if obj is not None:
        hay = norm(' | '.join(collect_values(obj)))
    else:
        hay = norm(n10_text)
    n1n = norm(n1_text)
    win = norm(WINDOW)
    tp_facts, prov_fail = [], []
    for f in VALID:
        if in_text(f, hay) and in_text(f, n1n) and in_window(f):
            tp_facts.append(f['fid'])
        elif in_text(f, hay):
            prov_fail.append(f['fid'])
    seen, fps = set(), []
    for c in claims(n10_text):
        if claim_supported(c, win): continue
        if norm(c[1]) in seen: continue
        seen.add(norm(c[1])); fps.append(c[1])
    tp = len(tp_facts); fp = len(fps)
    R = tp / len(VALID); P = tp / max(1, tp + fp)
    return dict(tp=tp, tp_facts=tp_facts, unsupported_provenance=prov_fail, fp=fp, fp_values=fps,
                recall=round(R, 4), precision=round(P, 4), f1=round(2 * P * R / max(1e-3, P + R), 4),
                report_json_parsed=obj is not None)

# ───────────────────────── main ─────────────────────────
def main():
    results = []
    t0 = time.time()
    for b in range(1, 6):
        bname = f'ST-B{b}'
        print(f'\n=== {bname} ===')
        try:
            n1_prompt = N1_TEMPLATE + '文档：\n' + WINDOW
            rec, n1_out = safe_call(MODEL, '你是资本市场文档分析助手。穷尽提取所有事实，不遗漏任何条目。只输出JSON。',
                                     n1_prompt, max_tokens=MAXTOK['n1'], purpose=f'{bname}:n1', timeout_s=120)
        except BudgetExceeded as e:
            print('BUDGET STOP at n1:', e); break
        sha = hashlib.sha256(n1_out.encode()).hexdigest()
        print(f'  n1: {len(n1_out)} chars sha={sha[:16]} out_tok={rec["usage"]["output_tokens"]}')
        sink = []
        try:
            aout = run_arm_a(bname, n1_out, sink)
            bout = run_arm_b(bname, n1_out, sink)
        except BudgetExceeded as e:
            print('BUDGET STOP mid-block:', e); break
        sa = score(aout.get('n10', ''), n1_out)
        sb = score(bout['out'].get('n10', ''), n1_out)
        # H2 attribution
        att = {}
        for fid in ['A03', 'A09', 'A01', 'E01', 'D03', 'D06']:
            f = next(x for x in silver if x['fid'] == fid)
            att[fid] = dict(extracted=in_text(f, norm(n1_out)),
                            A=in_text(f, norm(aout.get('n10', ''))),
                            B=in_text(f, norm(bout['out'].get('n10', ''))))
        tokA = sum(x['usage']['input_tokens'] + x['usage']['output_tokens'] for x in sink if x['arm'] == 'A')
        tokB = sum(x['usage']['input_tokens'] + x['usage']['output_tokens'] for x in sink if x['arm'] == 'B')
        n1tok = rec['usage']['input_tokens'] + rec['usage']['output_tokens']
        trunc = {f'{x["arm"]}:{x["node"]}': x['stop'] for x in sink if x['stop'] == 'max_tokens'}
        results.append(dict(block=b, n1_sha256=sha, n1_chars=len(n1_out), n1_tokens=n1tok,
                            store_size=len(bout['store']),
                            store_prov={k: sum(1 for r in bout['store'] if r['provenance_status'] == k)
                                        for k in ('VERIFIED_UNIQUE_SPAN', 'VERIFIED_MULTI_SPAN', 'UNVERIFIABLE_ABSENT')},
                            n9_supported=bout['n9_supported'], n10_fed=bout['n10_fed'],
                            A=sa, B=sb, attribution=att,
                            tokens=dict(n1=n1tok, A_non_n1=tokA, B_non_n1=tokB,
                                        CA=n1tok + tokA, CB=n1tok + tokB),
                            truncations=trunc))
        print(f'  A: TP={sa["tp"]} FP={sa["fp"]} R={sa["recall"]} P={sa["precision"]} F1={sa["f1"]}')
        print(f'  B: TP={sb["tp"]} FP={sb["fp"]} R={sb["recall"]} P={sb["precision"]} F1={sb["f1"]}')
        print(f'  store={len(bout["store"])} n9_supported={len(bout["n9_supported"])} n10_fed={bout["n10_fed"]}')
        print(f'  tok CA={n1tok+tokA} CB={n1tok+tokB} trunc={list(trunc)}')

    json.dump(dict(prereg='STRUCTURED_TRANSFER_PREREG_V1_2.md', deviation='D1: A-arm n3/n4 -> n2[:3000]; D2: model glm53flash->glm-5.3 both arms (resource package), standard endpoint, thinking forced low; D3: token ceiling 250K->400K',
                   scoring='v3', blocks=results,
                   elapsed_s=round(time.time() - t0, 1)),
              open('st_v1_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f'\nSaved st_v1_RESULTS.json ({len(results)} blocks, {time.time()-t0:.0f}s)')

if __name__ == '__main__':
    main()
