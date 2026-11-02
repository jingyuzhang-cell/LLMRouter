"""B-arm token budget — SINGLE SOURCE OF TRUTH (zero model calls).

Every number printed here is derived in this file; the prereg quotes this output.
Run: python3 b_arm_budget.py
"""
import json, re, statistics
from collections import Counter

norm = lambda s: re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))
ZEDA = '/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'
SYS = '你是一个严谨的资本市场调查助手。只输出JSON。不要编造。无法确认的标UNKNOWN。'

def get_text(fn, pref):
    for line in open(fn):
        if not line.strip(): continue
        r = json.loads(line)
        if r['purpose'].startswith(pref): return r['text']
    return ''

def extract_json(t):
    """First complete JSON value in the text; tolerates fences and trailing prose."""
    c = (t or '').strip()
    if c.startswith('```'):
        ls = c.split('\n')[1:]
        if ls and ls[-1].strip() == '```': ls = ls[:-1]
        c = '\n'.join(ls).strip()
    try:
        return json.loads(c)
    except Exception:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(c):
        if ch in '{[':
            try:
                obj, _ = dec.raw_decode(c[i:])
                return obj
            except Exception:
                continue
    raise ValueError('no JSON value found')

def parse(t):
    return extract_json(t)

def locate_all(value, kind, window):
    """All candidate spans in the n1 window (operator: keep EVERY candidate)."""
    forms = {value, value.replace(',', '')}
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', value)
    if kind == 'date' and m:
        forms |= {f'{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日'}
    occ = [(mm.start(), mm.end()) for f in forms for mm in re.finditer(re.escape(f), window)]
    if not occ and kind == 'date' and m:
        el, yr = f'{int(m.group(2))}月{int(m.group(3))}日', m.group(1) + '年'
        occ = [(mm.start(), mm.end()) for mm in re.finditer(re.escape(el), window)
               if yr in window[max(0, mm.start() - 120):mm.end() + 120]]
    occ.sort(); ded = []
    for x in occ:
        if ded and x[0] <= ded[-1][1]:
            if x[1] > ded[-1][1]: ded[-1] = (ded[-1][0], x[1])
        else:
            ded.append(x)
    return ded

def build_store(n1_text, window, pad):
    o = parse(n1_text)
    kind_map = {'dates': 'date', 'amounts': 'amount', 'penalties': 'penalty', 'entities': 'entity'}
    code = {'dates': 'DTE', 'amounts': 'AMT', 'penalties': 'PEN', 'entities': 'ENT'}
    recs = []
    for key, t in kind_map.items():
        for it in (o.get(key) or []):
            v = it.get('value') or it.get('name') or ''
            if not v: continue
            role = str(it.get('nature') or it.get('role') or it.get('type') or '')[:16]
            spans = locate_all(v, t, window)
            prov = ('VERIFIED_UNIQUE_SPAN' if len(spans) == 1 else
                    'VERIFIED_MULTI_SPAN' if len(spans) > 1 else 'UNVERIFIABLE_ABSENT')
            quotes = [window[max(0, s - pad):e + pad].replace('\n', ' ') for s, e in spans]
            sid = spans[0][0] if spans else f'X{abs(hash(norm(v))) % 10000}'
            recs.append(dict(fact_id=f'{code[key]}{sid}', fact_type=t, fact_role=role, value=v,
                             provenance_status=prov,
                             spans=[[s, e] for s, e in spans],
                             quotes=quotes))
    seen, uniq = set(), []
    for r in recs:
        k = (r['fact_type'], norm(r['value']), r['fact_role'])
        if k in seen: continue
        seen.add(k); uniq.append(r)
    return uniq

def _conflict_candidates(store):
    """Code-side pre-screen: same normalized value under >1 fact_role (deterministic)."""
    g = {}
    for r in store:
        if r['fact_type'] != 'amount': continue
        g.setdefault(norm(r['value']), []).append(r)
    out = []
    for v, rs in g.items():
        if len({x['fact_role'] for x in rs}) > 1:
            out.append(dict(value=rs[0]['value'],
                            candidates=[dict(fact_id=x['fact_id'], fact_role=x['fact_role']) for x in rs]))
    return out

MAX_TOKENS = {'n1': 4000, 'n2': 768, 'n3': 768, 'n4': 768, 'n5': 768,
              'n6': 768, 'n7': 768, 'n8': 768, 'n9': 2000, 'n10': 2000}

def J(x): return len(json.dumps(x, ensure_ascii=False, separators=(',', ':')))

def build_prompts(store, pad):
    by = lambda t: [x for x in store if x['fact_type'] == t]
    def slim(r):
        # LEAN: positions live only in n9; consumers reference by fact_id
        return dict(fact_id=r['fact_id'], fact_type=r['fact_type'], fact_role=r['fact_role'],
                    value=r['value'], provenance_status=r['provenance_status'])
    def with_quote(r):
        d = slim(r); d['quote'] = r['quotes'][0] if r['quotes'] else ''
        return d
    return {
        'n2':  (SYS, f'{SYS}\n以下为代码预筛出的候选：同一归一化数值被赋予不同 fact_role 的条目。任务：判定哪些确属冲突、哪些其实是同一事实的不同表述；用 fact_id 引用；不得新增事实。输出JSON，字段 {{"duplicates":[],"role_conflicts":[]}}。\n'
                     + json.dumps(_conflict_candidates(store), ensure_ascii=False, separators=(',', ':'))),
        'n3':  (SYS, f'{SYS}\n以下为候选日期事实（含全部候选 span）。任务：按日期排序并划分阶段，用 fact_id 引用。不得改写事实值。输出JSON，字段 {{"timeline":[{{"fact_id":"","order":0,"stage":""}}]}}。\n'
                     + json.dumps([slim(r) for r in by('date')], ensure_ascii=False, separators=(',', ':'))),
        'n4':  (SYS, f'{SYS}\n以下为候选金额事实（含全部候选 span）。任务：按 fact_role 归类并标注口径，用 fact_id 引用。不得改写事实值。输出JSON，字段 {{"amounts":[{{"fact_id":"","bucket":""}}]}}。\n'
                     + json.dumps([slim(r) for r in by('amount')], ensure_ascii=False, separators=(',', ':'))),
        'n5':  (SYS, f'{SYS}\n以下为候选处罚事实。任务：识别种类/对象/依据，用 fact_id 引用；无则空数组。输出JSON，字段 {{"penalties":[]}}。\n'
                     + json.dumps([slim(r) for r in by('penalty')], ensure_ascii=False, separators=(',', ':'))),
        'n6':  (SYS, f'{SYS}\n以下为候选实体事实。任务：识别主体及角色关系，用 fact_id 引用。不得改写实体名。输出JSON，字段 {{"entities":[{{"fact_id":"","role":""}}]}}。\n'
                     + json.dumps([slim(r) for r in by('entity')], ensure_ascii=False, separators=(',', ':'))),
        'n7':  (SYS, f'{SYS}\n以下为时间线与主体归类的 fact_id 结果。任务：划分阶段并复核前后一致性。不得新增事实。输出JSON，字段 {{"stages":[]}}。\n'
                     + json.dumps({'timeline': '<n3输出>', 'entities': '<n6输出>'}, ensure_ascii=False)),
        'n8':  (SYS, f'{SYS}\n以下为金额归类结果。任务：核验同一 fact_role 下口径是否冲突（累计 vs 分年）。不得新增事实。输出JSON，字段 {{"amounts_checked":[]}}。\n'
                     + json.dumps({'amounts': '<n4输出>'}, ensure_ascii=False)),
        'n9':  (SYS, f'{SYS}\n以下为候选事实及其全部候选证据片段与溯源状态。任务：逐条判定——须至少有一个证据位置能支持该 fact_role 才可 supported；语境含否认/申辩/请求时不得判 supported；无法区分语境时判 unknown。只输出 fact_id。\n'
                     + json.dumps([with_quote(r) for r in store], ensure_ascii=False, separators=(',', ':'))),
        'n10': (SYS, f'{SYS}\n以下为已核验支持的 facts。任务：组织完整调查报告，逐项包含所有日期、金额（保留原始数字与单位）、处罚、主体。不得新增事实。输出JSON，字段 report。\n'
                     + json.dumps([dict(fact_id=r['fact_id'], fact_type=r['fact_type'], fact_role=r['fact_role'], value=r['value'])
                                   for r in store if r['provenance_status'] != 'UNVERIFIABLE_ABSENT'], ensure_ascii=False, separators=(',', ':'))),
    }

# ── measured tokens/char from real calls (min / median / max per node) ──
def measured_ratios():
    rows = {}
    for fn in ('v7_repetition_LEDGER.jsonl', 'v8_n1_upgrade_LEDGER.jsonl'):
        for line in open(fn):
            if not line.strip(): continue
            r = json.loads(line)
            pc, it = r.get('prompt_chars'), r.get('usage', {}).get('input_tokens')
            if not pc or not it: continue
            node = r['purpose'].split(':')[1]
            if node == 'n6' and it / pc < 0.1: continue      # known cache artifact
            rows.setdefault(node, []).append(it / pc)
    return {n: (min(v), statistics.median(v), max(v)) for n, v in rows.items()}

def a_arm_baseline():
    """Measured A-arm (V7) per-block totals, and n1-only share."""
    n1_in = n1_out = tot_in = tot_out = 0; blocks = 0
    for k in range(1, 5):
        b_in = b_out = 0; calls = 0
        for line in open('v7_repetition_LEDGER.jsonl'):
            if not line.strip(): continue
            r = json.loads(line)
            if not r['purpose'].startswith(f'REP-V7-B{k}:'): continue
            u = r['usage']; node = r['purpose'].split(':')[1]
            b_in += u.get('input_tokens', 0); b_out += u.get('output_tokens', 0); calls += 1
            if node == 'n1':
                n1_in += u.get('input_tokens', 0); n1_out += u.get('output_tokens', 0)
        if calls == 10:
            tot_in += b_in; tot_out += b_out; blocks += 1
    return dict(blocks=blocks, total_in=tot_in / blocks, total_out=tot_out / blocks,
                n1_in=n1_in / blocks, n1_out=n1_out / blocks)

OUT_TOK = {'n2': 75, 'n3': 350, 'n4': 850, 'n5': 75, 'n6': 500,
           'n7': 280, 'n8': 200, 'n9': 350, 'n10': 2000}

def main():
    zeda = json.load(open(ZEDA))
    EV = ' '.join(d['text'] for d in zeda['docs'])
    W = EV[:4000]
    n1_text = get_text('v7_repetition_LEDGER_responses.jsonl', 'REP-V7-B4:n1')
    R = measured_ratios()
    A = a_arm_baseline()

    print("=" * 78)
    print("B-ARM TOKEN BUDGET — single source of truth")
    print("=" * 78)
    print(f"measured tokens/char by node (min/median/max over real calls):")
    for n in [f'n{i}' for i in range(1, 11)]:
        if n in R: print(f"  {n:4s} {R[n][0]:.4f} / {R[n][1]:.4f} / {R[n][2]:.4f}")
    print(f"\nA-arm measured (V7, {A['blocks']} complete blocks):")
    print(f"  per-block total: in={A['total_in']:.0f} out={A['total_out']:.0f} sum={A['total_in']+A['total_out']:.0f}")
    print(f"  of which n1:     in={A['n1_in']:.0f} out={A['n1_out']:.0f} sum={A['n1_in']+A['n1_out']:.0f}")

    n1_tok = A['n1_in'] + A['n1_out']          # shared n1, charged to BOTH arms
    A_non_n1 = (A['total_in'] + A['total_out']) - n1_tok
    print(f"  A non-n1 (n2..n10): {A_non_n1:.0f}")

    results = {}
    print("\n" + "=" * 78)
    print("PAD SENSITIVITY (n9 evidence snippet length) — same design family")
    print("=" * 78)
    print(f"{'pad':>4s} {'store':>6s} {'n2':>6s} {'n3':>6s} {'n4':>6s} {'n5':>5s} {'n6':>6s} {'n7':>5s} {'n8':>5s} {'n9':>7s} {'n10':>6s} | {'B_nonN1_min':>11s} {'mid':>7s} {'max':>7s} | {'ratio_mid':>9s}")
    for pad in (10, 15, 20, 25, 35):
        store = build_store(n1_text, W, pad)
        P = build_prompts(store, pad)
        chars = {'n1': 4884}
        for k, (sy, us) in P.items(): chars[k] = len(sy) + len(us)
        tot = {'min': 0, 'mid': 0, 'max': 0}
        for n in ['n1', 'n2', 'n3', 'n4', 'n5', 'n6', 'n7', 'n8', 'n9', 'n10']:
            if n == 'n1':
                continue
            rmin, rmid, rmax = R[n]
            for tag, rv in (('min', rmin), ('mid', rmid), ('max', rmax)):
                tot[tag] += int(chars[n] * rv) + OUT_TOK[n]
        # B total = shared n1 (charged) + B non-n1
        b_tot = {k: n1_tok + v for k, v in tot.items()}
        a_tot = n1_tok + A_non_n1
        ratio = b_tot['mid'] / a_tot
        results[pad] = dict(store=len(store), chars=chars, non_n1=tot, b_total=b_tot,
                            a_total=a_tot, ratio={k: b_tot[k] / a_tot for k in tot})
        print(f"{pad:>4d} {len(store):>6d} {chars['n2']:>6d} {chars['n3']:>6d} {chars['n4']:>6d} {chars['n5']:>5d} "
              f"{chars['n6']:>6d} {chars['n7']:>5d} {chars['n8']:>5d} {chars['n9']:>7d} {chars['n10']:>6d} | "
              f"{tot['min']:>11d} {tot['mid']:>7d} {tot['max']:>7d} | {ratio:>8.3f}x")

    pad = 10
    res = results[pad]
    print("\n" + "=" * 78)
    print(f"ADOPTED DESIGN: pad={pad}")
    print("=" * 78)
    print(f"{'node':5s} {'chars':>7s} {'in_min':>7s} {'in_mid':>7s} {'in_max':>7s} {'out_tok':>7s} {'total_mid':>9s}")
    for n in ['n1', 'n2', 'n3', 'n4', 'n5', 'n6', 'n7', 'n8', 'n9', 'n10']:
        ch = res['chars'][n]
        if n == 'n1':
            print(f"{n:5s} {ch:>7d} {A['n1_in']:>7.0f} {A['n1_in']:>7.0f} {A['n1_in']:>7.0f} {A['n1_out']:>7.0f} {n1_tok:>9.0f}")
            continue
        rmin, rmid, rmax = R[n]
        print(f"{n:5s} {ch:>7d} {int(ch*rmin):>7d} {int(ch*rmid):>7d} {int(ch*rmax):>7d} {OUT_TOK[n]:>7d} "
              f"{int(ch*rmid)+OUT_TOK[n]:>9d}")
    print(f"\nB non-n1 total (min/mid/max): {res['non_n1']['min']} / {res['non_n1']['mid']} / {res['non_n1']['max']}")
    print(f"A non-n1 total:               {A_non_n1:.0f}")
    print(f"shared n1 (charged to both):  {n1_tok:.0f}")
    print(f"A full pipeline:              {res['a_total']:.0f}")
    print(f"B full pipeline (min/mid/max):{res['b_total']['min']:.0f} / {res['b_total']['mid']:.0f} / {res['b_total']['max']:.0f}")
    print(f"B/A ratio (min/mid/max):      {res['ratio']['min']:.3f}x / {res['ratio']['mid']:.3f}x / {res['ratio']['max']:.3f}x")
    print(f"max_tokens (IDENTICAL both arms): {MAX_TOKENS}")
    print(f"gate 1.15 -> mid {'PASS' if res['ratio']['mid'] <= 1.15 else 'FAIL'}; "
          f"worst case {'PASS' if res['ratio']['max'] <= 1.15 else 'FAIL'}")

    json.dump(dict(
        method='chars(actual built prompts) x measured tokens/char(min/median/max per node) + output tokens; '
               'shared n1 charged to both arms',
        adopted_pad=pad, fact_records=res['store'], per_node_chars=res['chars'],
        out_tokens_assumed=OUT_TOK, max_tokens_frozen=MAX_TOKENS, a_arm=A, a_non_n1=A_non_n1, n1_tokens_shared=n1_tok,
        b_non_n1=res['non_n1'], b_total=res['b_total'], a_total=res['a_total'],
        ratios={k: round(v, 4) for k, v in res['ratio'].items()},
        pad_sweep={str(p): dict(store=v['store'], n9_chars=v['chars']['n9'],
                                ratio_mid=round(v['ratio']['mid'], 4),
                                ratio_max=round(v['ratio']['max'], 4)) for p, v in results.items()},
        calls='5 blocks x (1 shared n1 + 9 A + 9 B) = 95; cap 105',
    ), open('TOKEN_BUDGET_B_ARM.json', 'w'), ensure_ascii=False, indent=1)
    print("\nSaved TOKEN_BUDGET_B_ARM.json")

if __name__ == '__main__':
    main()
