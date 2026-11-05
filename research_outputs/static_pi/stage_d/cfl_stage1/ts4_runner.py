"""TS-4: entity-value binding (J node) minimal contrast (J_NODE_AUDIT.md design).
A arm = frozen baselines (0 calls). B arm = same baseline prompts + gold-blind
deterministic J-block (fact_id-keyed bound rows). J rules from the audit:
year/item adjacency (KANGMEI B3-B5), composite item-amount pairs (B6),
text-quote (C1), per-subject fine clause (MVR1 F2-F3), enumeration-same-amount
(F4-F6); F1 left unbound (cross-clause). Caps: 5 calls (4+1 reserve) / 20K / 0.06.
"""
import json, os, sys, re, time, hashlib, urllib.request, urllib.error

SD = '/root/research_outputs/static_pi/stage_d'
sys.path.insert(0, f'{SD}/quality_phase_v1')
sys.path.insert(0, f'{SD}/qp3')
sys.path.insert(0, f'{SD}/v2')
sys.path.insert(0, SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import qp1_prompts as P1
import scorer_qp1 as Q1
import qp3_primitives as P3
from qp4_factorial import VALUE_FORM_RULES
from qp5a_pure_prep import COPY_RULE
from qp1_prompts import P_SYS, MAXTOK
from stage_d_v2_transport import build_request, ds_key, glm_key, MODEL_CFG
from cfl3_min_runner import four_part_check, load_contract
from ts1_runner import SEL_BLOCK

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/TS4_LEDGER.jsonl'
CAPS = dict(calls=5, tokens=20_000, yuan=0.06)
BLIND = dict(KANGMEI={'B3', 'B4', 'B5', 'B6', 'C1'},
             MVR1={'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F12'})
BASE = dict(KANGMEI=dict(model='deepseek', q=0.571, wrong=5),
            MVR1=dict(model='glm53flash', q=0.438, wrong=8.5))
calls_used = [0]; yuan_used = [0.0]; tok_used = [0]; reserve = [1]
NUM = r'(\d[\d,，.]*\s*(?:亿元|万元|元|%))'


def load_any(t):
    p = [x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if x['event_key'] == t][0]['contract']
    if not os.path.isabs(p): p = f'{SD}/v23a/{p}'
    return json.load(open(p))


def dedup(ents, c):
    pool, seen = [], set()
    for e in ents:
        if not four_part_check(e, c)[0]:
            continue
        v = e.get('raw') or e.get('value')
        key = (str(e.get('field')), str(e.get('bucket')), str(e.get('predicate')),
               str(e.get('doc')), str(e.get('page')),
               Q1._norm(e.get('quote') or ''), Q1._norm(str(v)))
        if key in seen:
            continue
        seen.add(key); pool.append(e)
    return pool


def clause_bind(pool, f):
    """KANGMEI B3-B5: subject-year + predicate-item adjacent in quote -> amount."""
    subj = str(f.get('subject') or ''); pred = str(f.get('predicate') or '')
    year = re.search(r'(20\d{2})年?', subj)
    item = re.sub(r'[/／].*$', '', pred)  # 虚增货币资金
    if not year or not item:
        return None
    y = year.group(1)
    for e in pool:
        qn = Q1._norm(e.get('quote') or '')
        iy, ii = qn.find(y), qn.find(Q1._norm(item))
        if iy < 0 or ii < 0 or abs(iy - ii) > 60:
            continue
        m = re.search(NUM, e.get('quote') or '')
        # prefer number right after the item occurrence in the raw quote
        raw = e.get('quote') or ''
        pos = Q1._norm(raw[:raw.find(item) + len(item) if item in raw else 0])
        m2 = re.search(re.escape(item) + r'[^0-9]{0,6}' + NUM, raw)
        val = (m2 or m).group(1) if (m2 or m) else None
        if val:
            return dict(fact_id=f['fact_id'], value=val, doc=e.get('doc'),
                        page=e.get('page'), quote=e.get('quote'))
    return None


def composite_bind(pool, f):
    """KANGMEI B6: item-amount pairs for each '/'-separated predicate item."""
    pred = str(f.get('predicate') or '')
    items = [x for x in re.split(r'[/／、]', pred) if x]
    vals = []
    ref = None
    for it in items:
        hit = None
        for e in pool:
            raw = e.get('quote') or ''
            m = re.search(re.escape(it) + r'[^0-9]{0,8}' + NUM, raw)
            if m:
                hit = (m.group(1), e); break
        if not hit:
            return None
        vals.append(hit[0]); ref = ref or hit[1]
    return dict(fact_id=f['fact_id'], value='/'.join(vals), doc=ref.get('doc'),
                page=ref.get('page'), quote=ref.get('quote'))


def text_bind(pool, f):
    """C1: name-matched row with a text value -> bind row value."""
    for e in pool:
        if P3.name_matches(e, f):
            v = e.get('raw') or e.get('value')
            if v not in (None, ''):
                return dict(fact_id=f['fact_id'], value=str(v), doc=e.get('doc'),
                            page=e.get('page'), quote=e.get('quote'))
    return None


def fine_bind(pool, f):
    """MVR1 F2-F6: 对{主体}…处以X万元 / {主体}∈列举…分别处以X万元."""
    subj = str(f.get('subject') or '')
    if not subj:
        return None
    for e in pool:
        raw = e.get('quote') or ''
        if subj not in raw:
            continue
        if '分别' in raw:
            m = re.search(r'分别[^0-9]{0,12}' + NUM, raw)
            if m:
                return dict(fact_id=f['fact_id'], value=m.group(1), doc=e.get('doc'),
                            page=e.get('page'), quote=raw)
        pos = raw.find(subj)
        m = re.search(NUM, raw[pos:pos + 80]) if pos >= 0 else None
        if m and ('处以' in raw[pos:pos + 80] or '罚款' in raw[pos:pos + 80]):
            return dict(fact_id=f['fact_id'], value=m.group(1), doc=e.get('doc'),
                        page=e.get('page'), quote=raw)
    return None


def build_j_rows(contract, pool, task):
    facts = {f['fact_id']: f for f in contract['required_facts']
             if f.get('status') not in ('EXCLUDED', 'NOT_APPLICABLE')}
    rows = {}
    if task == 'KANGMEI':
        for fid in ('B3', 'B4', 'B5'):
            rows[fid] = clause_bind(pool, facts[fid])
        rows['B6'] = composite_bind(pool, facts['B6'])
        rows['C1'] = text_bind(pool, facts['C1'])
    else:
        for fid in ('F2', 'F3', 'F4', 'F5', 'F6'):
            rows[fid] = fine_bind(pool, facts[fid])
        # F1/F7/F12: F1 cross-clause (unbound by design); F7 uncoverable
        for fid in ('F1', 'F7'):
            rows[fid] = None
        r = None
        for e in pool:
            if Q1._norm(str(facts['F12'].get('value'))) and \
               Q1.value_in_quote(facts['F12'].get('value'), e.get('quote') or '') and \
               str(facts['F12'].get('subject')) in (e.get('quote') or ''):
                m = re.search(NUM, e.get('quote') or '')
                if m:
                    r = dict(fact_id='F12', value=m.group(1), doc=e.get('doc'),
                             page=e.get('page'), quote=e.get('quote'))
                    break
        rows['F12'] = r
    return {k: v for k, v in rows.items() if v}


def j_block(jrows):
    lines = ['【已绑定事实（实体-数值配对节点核验，值与引文逐字一致；'
             'answers 中这些槽位直接采用下列 value/doc/page/quote，勿改写值）：】']
    for fid, r in sorted(jrows.items()):
        lines.append(f"fact_id={fid} | value={r['value']} | doc={r['doc']} | "
                     f"page={r['page']} | quote={r['quote'][:120]}")
    return '\n'.join(lines)


def bnew_prompt(contract, pool, sel=False):
    mf = {}
    for e in pool:
        k = str(e.get('field') or e.get('bucket') or '')
        if k and e.get('value') not in (None, ''):
            mf.setdefault(k, e.get('value'))
    rows = [f"{e.get('field') or e.get('bucket')} | value={e.get('raw') or e.get('value')} "
            f"| doc={e.get('doc')} | page={e.get('page')} | quote={e.get('quote', '')}" for e in pool]
    p = (P1.p_user(contract, {'facts': [dict(field=k, value=v) for k, v in mf.items()]}, {}, [], 'E1')
         + '\n\n' + VALUE_FORM_RULES
         + '\n\n已核验证据表（逐条）：\n' + '\n'.join(rows) + '\n\n' + COPY_RULE)
    return p + SEL_BLOCK if sel else p


def real_call(alias, user, purpose):
    for attempt in (1, 2):
        if attempt == 2:
            if reserve[0] < 1:
                raise RuntimeError('NO RESERVE LEFT')
            reserve[0] -= 1
            print(f'  [reserve consumed: {purpose}]')
        if calls_used[0] >= CAPS['calls']:
            raise RuntimeError('CALLS CAP')
        if yuan_used[0] + 0.008 > CAPS['yuan'] * 0.95:
            raise RuntimeError('YUAN CAP')
        body = build_request(alias, P_SYS, user, MAXTOK['p'])
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        req = urllib.request.Request(MODEL_CFG[alias]['url'],
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        req.add_header('authorization', 'Bearer ' + (ds_key() if alias == 'deepseek' else glm_key()))
        t0 = time.monotonic()
        d = None
        try:
            for backoff in (0, 60, 120, 180):
                if backoff:
                    print(f'  [429 backoff {backoff}s: {purpose}]'); time.sleep(backoff)
                try:
                    with urllib.request.urlopen(req, timeout=180) as r:
                        d = json.loads(r.read().decode())
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429 and backoff < 180:
                        continue
                    raise
        except Exception:
            if attempt == 1:
                continue
            raise
        if d is None:
            if attempt == 1:
                continue
            raise RuntimeError('transport failed')
        ch = d['choices'][0]; u = d.get('usage', {})
        c = ch.get('message', {}).get('content', '')
        text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
        tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
        yuan = round(tin * 0.8e-6 + tout * 2.8e-6, 8)
        lat = round(time.monotonic() - t0, 3)
        calls_used[0] += 1; yuan_used[0] += yuan; tok_used[0] += tin + tout
        with open(LEDGER, 'a') as f:
            f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias=alias,
                                    purpose=purpose, prompt_sha256=sha,
                                    usage=dict(input_tokens=tin, output_tokens=tout),
                                    accounting_yuan=yuan, latency_s=lat, text=text),
                               ensure_ascii=False) + '\n')
        if tok_used[0] >= CAPS['tokens']:
            raise RuntimeError('TOKEN CAP')
        obj = extract_any(text)
        if obj is None and attempt == 1:
            continue
        return obj, lat, yuan
    raise RuntimeError('unreachable')


def main():
    r3 = {json.loads(l)['purpose']: json.loads(l) for l in open(f'{OUT}/CFL3_MIN_LEDGER.jsonl')}
    led = {}
    for pth in (f'{SD}/qp8/QP8R_STAGE1_LEDGER.jsonl', f'{SD}/qp9/QP9_LEDGER.jsonl'):
        for l in open(pth):
            x = json.loads(l); led[x['purpose']] = x
    c_k = load_contract()
    ents_k = []
    for rep in (1, 2):
        ents_k += parse2(extract_any(r3[f'cfl3min|KANGMEI|C|r{rep}|e1_reext']['text']) or {})
    pool_k = dedup(ents_k, c_k)
    c_m = load_any('MVR1')
    ents_m = []
    for node in ('e0', 'e1'):
        ents_m += parse2(extract_any(led[f'qp8r|MVR1|DS|r1|{node}']['text']) or {})
    pool_m = dedup(ents_m, c_m)

    # J rows (gold-blind) + zero-call verification gate
    j_k = build_j_rows(c_k, pool_k, 'KANGMEI')
    j_m = build_j_rows(c_m, pool_m, 'MVR1')
    for task, c, jrows in (('KANGMEI', c_k, j_k), ('MVR1', c_m, j_m)):
        facts = {f['fact_id']: f for f in c['required_facts']}
        print(f"== {task} J rows (gold-blind):")
        for fid, r in sorted(jrows.items()):
            ok = Q1.value_in_quote(r['value'], r['quote'])
            posthoc = P3.value_equal_anyway(r['value'], facts[fid])[0]
            print(f"  {fid}: value={str(r['value'])[:34]!r} in_own_quote={ok} posthoc_gold_match={posthoc}")
    json.dump(dict(KANGMEI=j_k, MVR1=j_m), open(f'{OUT}/TS4_J_ROWS.json', 'w'),
              ensure_ascii=False, indent=1)

    p_k = bnew_prompt(c_k, pool_k, sel=False) + '\n\n' + j_block(j_k)
    p_m = bnew_prompt(c_m, pool_m, sel=True) + '\n\n' + j_block(j_m)
    results = []
    for task, contract, prompt, jrows in (('KANGMEI', c_k, p_k, j_k),
                                          ('MVR1', c_m, p_m, j_m)):
        for rep in (1, 2):
            obj, lat, y = real_call(BASE[task]['model'], prompt, f'ts4|{task}|J|r{rep}|p')
            res = Q1.score_task(contract, obj) if obj else None
            row = dict(task=task, rep=rep, latency_s=lat, yuan=y)
            if res:
                rows_ = res['rows']
                tp = [x['fact_id'] for x in rows_ if x['status'] == 'TP']
                wrong = [x['fact_id'] for x in rows_ if x['status'].startswith('VALUE')]
                answers = {a.get('fact_id'): a for a in (obj or {}).get('answers', [])
                           if isinstance(a, dict)}
                j_used = [fid for fid in jrows
                          if fid in answers and str(answers[fid].get('value', '')).strip()
                          and Q1._norm(str(answers[fid].get('value'))) == Q1._norm(jrows[fid]['value'])]
                row.update(q=res['q'], tp=tp, wrong=wrong,
                           abst=sum(1 for x in rows_ if x['status'] == 'ABSENT'),
                           precision=round(len(tp) / max(1, len(tp) + len(wrong)), 3),
                           blind_fixed=sorted(set(tp) & BLIND[task]),
                           j_rows_echoed=j_used)
            else:
                row.update(parse_fail=True)
            results.append(row)
            print(f"{task} J r{rep}: Q={row.get('q')} (base {BASE[task]['q']}) "
                  f"TP={len(row.get('tp', []))} wrong={len(row.get('wrong', []))} "
                  f"(base {BASE[task]['wrong']}) blind={row.get('blind_fixed')} "
                  f"J_echoed={row.get('j_rows_echoed')}")
    json.dump(dict(batch='TS4', caps=CAPS,
                   used=dict(calls=calls_used[0], yuan=round(yuan_used[0], 4),
                             tokens=tok_used[0], reserve_left=reserve[0]),
                   results=results), open(f'{OUT}/TS4_RESULTS.json', 'w'),
              ensure_ascii=False, indent=1)
    print(f"\nDONE: calls={calls_used[0]}/{CAPS['calls']} tokens={tok_used[0]}/{CAPS['tokens']} "
          f"¥{yuan_used[0]:.4f}/{CAPS['yuan']} reserve_left={reserve[0]}")


if __name__ == '__main__':
    main()
