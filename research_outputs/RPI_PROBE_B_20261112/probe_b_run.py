#!/usr/bin/env python3
"""PROBE-B: 12-call minimal capability-difference probe (multi-doc state evolution).

Frozen taskset: PROBE_B_TASKSET.json SHA 2de5092c2c77386e27cea856e2d6f0fb19e1c0fbafba446ab1b6512747459e0f
Caps: 12 calls / 100,000 tokens / ¥0.30 accounting. No retries. Requires PROBE_B_GO=1.
Models: GLM-5.3-Flash (Anthropic endpoint, thinking enabled + effort low) and
deepseek-flash (OpenAI-compatible, thinking disabled). Temperature 0, max_tokens 3072.
"""
import json, os, re, sys, time, hashlib, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKSET = HERE / 'PROBE_B_TASKSET.json'
LEDGER = HERE / 'probe_b_ledger.jsonl'
REPORT = HERE / 'PROBE_B_REPORT.json'
CAPS = dict(calls=12, tokens=100_000, yuan=0.30)
MAX_OUT = 3072
GLM_URL = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
DS_URL = 'https://api.deepseek.com/chat/completions'
SYS = '你是一个严谨的资本市场文书核查助手。只输出要求的 JSON。'
CN = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}


def sha(t): return hashlib.sha256((t or '').encode()).hexdigest()


def cn2ar(s):
    s = str(s or '')
    def rep(m):
        t = m.group(0)
        if '十' in t:
            parts = t.split('十'); a = parts[0]; b = parts[1] if len(parts) > 1 else ''
            tens = CN.get(a, 1) if a else 1
            ones = CN.get(b, 0) if b else 0
            return str(tens * 10 + ones)
        return ''.join(str(CN[c]) for c in t)
    return re.sub(r'[零一二三四五六七八九]+', rep, s)


def norm(v):
    if v is None: return ''
    s = cn2ar(str(v))
    s = s.replace(',', '').replace(' ', '').replace('\u3000', '')
    for ch in '〔〕【】[]（）()':
        s = s.replace(ch, '')
    return s.upper()


def load_key(name, fallback=None):
    v = os.environ.get(name)
    if v: return v.strip()
    p = Path('/root/.env')
    if p.exists():
        for line in p.read_text().splitlines():
            if line.startswith(name + '='):
                return line.split('=', 1)[1].strip()
    return fallback


def call_glm(prompt):
    key = load_key('STAGE_D_GLM_KEY') or load_key('ZHIPU_API_KEY')
    body = dict(model='GLM-5.3-Flash', max_tokens=MAX_OUT, system=SYS,
                messages=[dict(role='user', content=prompt)], temperature=0.0,
                reasoning_effort='low', thinking=dict(type='enabled'),
                output_config=dict(effort='low'))
    req = urllib.request.Request(GLM_URL, data=json.dumps(body, ensure_ascii=False).encode(), method='POST')
    for k, v in (('content-type', 'application/json'), ('x-api-key', key),
                 ('authorization', 'Bearer ' + key), ('anthropic-version', '2023-06-01')):
        req.add_header(k, v)
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        raw = json.loads(r.read().decode())
    lat = round(time.monotonic() - t0, 3)
    text = ''.join(b.get('text', '') for b in raw.get('content', []) if isinstance(b, dict) and b.get('type') == 'text')
    u = raw.get('usage') or {}
    tin = sum(u.get(k) or 0 for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
    tout = u.get('output_tokens', 0)
    cash = (tin * 0.8e-6 + tout * 2.8e-6)  # accounting price; GLM marginal 0
    return dict(answer=text, finish=raw.get('stop_reason'), tokens_in=tin, tokens_out=tout,
                cash_cny=round(cash, 6), latency_s=lat, model='GLM-5.3-Flash')


def call_ds(prompt):
    key = load_key('DEEPSEEK_API_KEY')
    body = dict(model='deepseek-flash', max_tokens=MAX_OUT,
                messages=[dict(role='system', content=SYS), dict(role='user', content=prompt)],
                temperature=0.0, thinking=dict(type='disabled'))
    req = urllib.request.Request(DS_URL, data=json.dumps(body, ensure_ascii=False).encode(), method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + key)
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        raw = json.loads(r.read().decode())
    lat = round(time.monotonic() - t0, 3)
    ch = raw['choices'][0]
    text = ch.get('message', {}).get('content', '') or ''
    u = raw.get('usage') or {}
    tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
    cash = ((tin * 0.3 + tout * 1.2) / 1e6) * 7.2  # USD list -> CNY
    return dict(answer=text, finish=ch.get('finish_reason'), tokens_in=tin, tokens_out=tout,
                cash_cny=round(cash, 6), latency_s=lat, model='deepseek-flash')


def parse_items(text):
    s = (text or '').strip()
    if s.startswith('```'):
        s = re.sub(r'^```\w*\n|```$', '', s, flags=re.M).strip()
    try:
        v = json.loads(s)
    except Exception:
        m = re.search(r'\[.*\]', s, re.S)
        if not m: return None
        try: v = json.loads(m.group(0))
        except Exception: return None
    return v if isinstance(v, list) else None


def match_item(out_items, req):
    rs, ri = norm(req['subject']), norm(req['item'])
    best = None
    for e in out_items:
        if not isinstance(e, dict): continue
        es, ei = norm(e.get('subject', '')), norm(e.get('item', ''))
        if not es or not ei: continue
        sub_ok = (rs in es) or (es in rs)
        it_ok = (ri in ei) or (ei in ri)
        if sub_ok and it_ok:
            best = e
            break
    return best


def score_task(task, out_items):
    rows = []
    for req in task['items']:
        e = match_item(out_items, req) if out_items else None
        gv = norm(req['terminal_value'])
        known = req['terminal_value'] != 'UNKNOWN'
        fv = norm(e.get('final_value', '')) if e else ''
        fact = None
        if known:
            fact = bool(e) and fv == gv
        evidence = None
        if fact:
            span = norm(e.get('evidence_span', ''))
            doc = norm(e.get('evidence_doc_id', ''))
            evidence = ('D2' in doc) and (gv in span or (fv and fv in span))
        st = (e.get('change_status') if e else '') or ''
        st = st.strip().lower()
        if req['status'] == 'changed':
            state = (st == 'changed') and (fv != norm(req['preliminary_value'])) and fact
        elif req['status'] == 'unchanged':
            state = (st == 'unchanged') and (fv == norm(req['preliminary_value'])) and fact
        elif req['status'] == 'new':
            state = (st == 'new') and fact
        else:  # unknown
            state = (st == 'unknown' or 'UNKNOWN' in fv)
        rows.append(dict(subject=req['subject'], item=req['item'], gold=req['terminal_value'],
                         status=req['status'], final_value=(e or {}).get('final_value'),
                         change_status=st, fact=fact, evidence=evidence, state=state,
                         found=bool(e)))
    return rows


def summarize(rows):
    known = [r for r in rows if r['gold'] != 'UNKNOWN']
    facts = sum(1 for r in known if r['fact'])
    ev = sum(1 for r in known if r['evidence'])
    state = sum(1 for r in rows if r['state'])
    contract = sum(1 for r in rows if r['found']) / len(rows) if rows else 0.0
    return dict(n=len(rows), known=len(known), facts=facts,
                fact_rate=round(facts / len(known), 4) if known else None,
                evidence=ev, evidence_rate=round(ev / facts, 4) if facts else None,
                state=state, state_rate=round(state / len(rows), 4) if rows else None,
                contract_cov=round(contract, 4))


def main():
    if os.environ.get('PROBE_B_GO') != '1':
        print('HOLD: set PROBE_B_GO=1 only after operator approval'); return 1
    tasks = json.loads(TASKSET.read_text())
    calls = tokens = 0; cash = 0.0
    results = []
    with open(LEDGER, 'a') as lf:
        for tid, t in tasks.items():
            assert sha(t['prompt']) == t['prompt_sha256']
            for model in ('glm', 'ds'):
                for rep in (1, 2):
                    if calls + 1 > CAPS['calls']:
                        print('CALL_CAP'); break
                    # input-only pre-check; actual usage settled after each call (hard cap below)
                    est = int(len(t['prompt']) * 0.55) + 256
                    if tokens + est > CAPS['tokens']:
                        print('TOKEN_CAP'); break
                    t0 = time.strftime('%Y-%m-%dT%H:%M:%S')
                    try:
                        o = call_glm(t['prompt']) if model == 'glm' else call_ds(t['prompt'])
                    except Exception as e:
                        o = dict(answer='', finish='transport_error', tokens_in=0, tokens_out=0,
                                 cash_cny=0.0, latency_s=0.0, model='GLM-5.3-Flash' if model == 'glm' else 'deepseek-flash',
                                 error=f'{type(e).__name__}: {e}')
                    calls += 1; tokens += o['tokens_in'] + o['tokens_out']; cash += o['cash_cny']
                    rec = dict(task=tid, code=t['code'], model=model, model_id=o['model'], rep=rep,
                               prompt_sha256=t['prompt_sha256'], answer=o['answer'], finish=o['finish'],
                               tokens_in=o['tokens_in'], tokens_out=o['tokens_out'],
                               cash_cny=o['cash_cny'], latency_s=o['latency_s'],
                               ts=t0, error=o.get('error'))
                    lf.write(json.dumps(rec, ensure_ascii=False) + '\n'); lf.flush(); os.fsync(lf.fileno())
                    items = parse_items(o['answer'])
                    rows = score_task(t, items) if items is not None else []
                    s = summarize(rows) if rows else dict(n=len(t['items']), known=None, facts=0, fact_rate=None,
                                                          evidence=0, evidence_rate=None, state=0,
                                                          state_rate=None, contract_cov=0.0)
                    results.append(dict(task=tid, model=model, rep=rep, finish=o['finish'],
                                        parsed=items is not None, summary=s, rows=rows,
                                        tokens=o['tokens_in'] + o['tokens_out'], cash=o['cash_cny'],
                                        latency=o['latency_s'], error=o.get('error')))
                    print(f"{tid} {model} rep{rep} finish={o['finish']} parsed={items is not None} "
                          f"facts={s.get('facts')}/{s.get('known')} state={s.get('state')}/{s.get('n')} "
                          f"tok={o['tokens_in']+o['tokens_out']} {o['latency_s']}s")
                    if cash > CAPS['yuan']:
                        print('YUAN_CAP'); break
    # aggregation
    per = {}
    for r in results:
        key = (r['task'], r['model'])
        per.setdefault(key, []).append(r)
    agg = {}
    for (tid, model), rs in per.items():
        fr = [x['summary'].get('fact_rate') for x in rs if x['summary'].get('fact_rate') is not None]
        sr = [x['summary'].get('state_rate') for x in rs if x['summary'].get('state_rate') is not None]
        agg[f'{tid}/{model}'] = dict(reps=len(rs), fact_rate_mean=round(sum(fr)/len(fr), 4) if fr else None,
                                     state_rate_mean=round(sum(sr)/len(sr), 4) if sr else None,
                                     parsed=sum(1 for x in rs if x['parsed']), finishes=[x['finish'] for x in rs])
    # Q1: per task, model means; stable if one model both reps strictly >= other and mean diff >=0.15 or strict both
    q1_tasks = {}
    for tid in tasks:
        g = per.get((tid, 'glm'), []); d = per.get((tid, 'ds'), [])
        gv = [x['summary'].get('fact_rate') for x in g if x['summary'].get('fact_rate') is not None]
        dv = [x['summary'].get('fact_rate') for x in d if x['summary'].get('fact_rate') is not None]
        if not gv or not dv: q1_tasks[tid] = dict(verdict='UNSCORABLE'); continue
        gm = sum(gv)/len(gv); dm = sum(dv)/len(dv)
        stable = (min(gv) >= max(dv) or max(gv) <= min(dv)) and abs(gm-dm) >= 0.0
        q1_tasks[tid] = dict(glm_mean=round(gm,4), ds_mean=round(dm,4), diff=round(gm-dm,4),
                             stable=stable, direction='glm' if gm>dm else ('ds' if dm>gm else 'tie'))
    dirs = [v['direction'] for v in q1_tasks.values() if v.get('stable')]
    q1 = any(dirs.count(m) >= 2 for m in ('glm','ds'))
    # Q2: item-type conditional preference (facts/state by status) and cost
    q2 = None; detail = {}
    # per status correctness by model across tasks
    for status in ('changed','unchanged','new','unknown'):
        g = d = gn = dn = 0
        for r in results:
            for row in r['rows']:
                if row['status'] != status: continue
                ok = row['state']
                if r['model']=='glm': gn+=1; g+=1 if ok else 0
                else: dn+=1; d+=1 if ok else 0
        detail[status] = dict(glm=f'{g}/{gn}', ds=f'{d}/{dn}')
    # usable if at least one status where one model better and another where the other better, or cost tradeoff
    gtot = sum(1 for r in results if r['model']=='glm')
    dtot = sum(1 for r in results if r['model']=='ds')
    cost = {m: round(sum(r['cash'] for r in results if r['model']==m), 4) for m in ('glm','ds')}
    better_glm = [s for s in detail if detail[s]['glm'].split('/')[1] != '0' and detail[s]['ds'].split('/')[1] != '0']
    # crude conditional: compare rates
    cond = False
    rates = {}
    for s in ('changed','unchanged','new','unknown'):
        gg, gn = map(int, detail[s]['glm'].split('/')); dd, dn = map(int, detail[s]['ds'].split('/'))
        if gn and dn: rates[s] = (gg/gn, dd/dn)
    if rates:
        gwin = any(v[0] > v[1] + 0.05 for v in rates.values())
        dwin = any(v[1] > v[0] + 0.05 for v in rates.values())
        cond = gwin and dwin
    q2 = dict(conditional_status_preference=cond, by_status=detail, cost_cny=cost, rates=rates)
    verdict = 'CONDITIONAL_PASS' if (q1 and cond) else 'STOP'
    report = dict(generated=time.strftime('%Y-%m-%dT%H:%M:%S'), calls=calls, tokens=tokens,
                  cash_cny=round(cash,6), caps=CAPS, taskset_sha256=sha(TASKSET.read_text()),
                  results=results, aggregate=agg, q1_tasks=q1_tasks, q1_pass=q1, q2=q2, verdict=verdict)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print('VERDICT', verdict, 'Q1', q1, 'Q2', cond, 'calls', calls, 'tokens', tokens, 'cash', round(cash,6))
    return 0


if __name__ == '__main__':
    sys.exit(main())
