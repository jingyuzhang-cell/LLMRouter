"""Stage-1 E06 fresh cells: unified chain (GLM frozen pool -> J={H1,H2} -> V ->
DS SINK). 2 reps + 1 reserve (transport/parse only). Caps 3/12K/0.05.
Dual denominators: Q_all(/17), Q_answerable(/12, 5 uncoverable excluded)."""
import json, os, sys, time, hashlib, urllib.request, urllib.error
SD = '/root/research_outputs/static_pi/stage_d'
sys.path.insert(0, f'{SD}/quality_phase_v1'); sys.path.insert(0, f'{SD}/qp3')
sys.path.insert(0, f'{SD}/v2'); sys.path.insert(0, SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import scorer_qp1 as Q1
import scorer_qp1_v2 as V2
import qp3_primitives as P3
from qp1_prompts import P_SYS, MAXTOK
from stage_d_v2_transport import build_request, ds_key, MODEL_CFG
from cfl3_min_runner import four_part_check
from ts4_runner import dedup, bnew_prompt, j_block

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/STAGE1_E06_LEDGER.jsonl'
CAPS = dict(calls=3, tokens=12_000, yuan=0.05)
UNCOVERABLE = {'DV3', 'DV4', 'H3', 'H4', 'H5'}
calls_used = [0]; yuan_used = [0.0]; tok_used = [0]; reserve = [1]

def load_any(t):
    p = [x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if x['event_key'] == t][0]['contract']
    if not os.path.isabs(p): p = f'{SD}/v23a/{p}'
    return json.load(open(p))

def real_call(user, purpose):
    for attempt in (1, 2):
        if attempt == 2:
            if reserve[0] < 1: raise RuntimeError('NO RESERVE LEFT')
            reserve[0] -= 1; print(f'  [reserve consumed: {purpose}]')
        if calls_used[0] >= CAPS['calls']: raise RuntimeError('CALLS CAP')
        body = build_request('deepseek', P_SYS, user, MAXTOK['p'])
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        req = urllib.request.Request(MODEL_CFG['deepseek']['url'],
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        req.add_header('authorization', 'Bearer ' + ds_key())
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode())
        except Exception:
            if attempt == 1: continue
            raise
        ch = d['choices'][0]; u = d.get('usage', {})
        c = ch.get('message', {}).get('content', '')
        text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
        tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
        yuan = round(tin * 0.8e-6 + tout * 2.8e-6, 8)
        calls_used[0] += 1; yuan_used[0] += yuan; tok_used[0] += tin + tout
        with open(LEDGER, 'a') as f:
            f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias='deepseek',
                purpose=purpose, prompt_sha256=sha,
                usage=dict(input_tokens=tin, output_tokens=tout),
                accounting_yuan=yuan, latency_s=round(time.monotonic()-t0,3), text=text),
                ensure_ascii=False) + '\n')
        if tok_used[0] >= CAPS['tokens']: raise RuntimeError('TOKEN CAP')
        obj = extract_any(text)
        if obj is None and attempt == 1: continue
        return obj
    raise RuntimeError('unreachable')

def main():
    led = {}
    for pth in (f'{SD}/qp8/QP8R_STAGE1_LEDGER.jsonl', f'{SD}/qp9/QP9_LEDGER.jsonl'):
        for l in open(pth):
            x = json.loads(l); led[x['purpose']] = x
    c = load_any('E06')
    pool, seen = [], set()
    for node in ('e0', 'e1'):
        for e in parse2(extract_any(led[f'qp8r|E06|GLM|r1|{node}']['text']) or {}):
            if not four_part_check(e, c)[0]: continue
            v = e.get('raw') or e.get('value')
            key = (str(e.get('field')), str(e.get('doc')), str(e.get('page')),
                   Q1._norm(e.get('quote') or ''), Q1._norm(str(v)))
            if key in seen: continue
            seen.add(key); pool.append(e)
    facts = {f['fact_id']: f for f in c['required_facts'] if f.get('status') not in ('EXCLUDED','NOT_APPLICABLE')}
    j = {}
    for fid in ('H1', 'H2'):
        f = facts[fid]
        for e in pool:
            if P3.name_matches(e, f) and (e.get('raw') or e.get('value')) not in (None, ''):
                j[fid] = dict(value=str(e.get('raw') or e.get('value')), doc=e.get('doc'),
                              page=e.get('page'), quote=e.get('quote'))
                break
    assert set(j) == {'H1', 'H2'}, 'J binding regression'
    prompt = bnew_prompt(c, pool, sel=True) + '\n\n' + j_block(j)
    print(f"pool={len(pool)} J={sorted(j)} prompt={len(prompt)} chars")
    results = []
    done = {}
    if os.path.exists(LEDGER):
        for l in open(LEDGER):
            x = json.loads(l); done[x['purpose']] = x
        calls_used[0] = len(done)
        for x in done.values():
            yuan_used[0] += x['accounting_yuan']
            tok_used[0] += x['usage']['input_tokens'] + x['usage']['output_tokens']
        print(f'[resume] {len(done)} completed cells replayed')
    for rep in (1, 2):
        hit = done.get(f'stage1|E06|DS_J|r{rep}|p')
        if hit is not None:
            from real_provider_v22 import extract_any as _ea
            obj = _ea(hit['text'])
        else:
            obj = real_call(prompt, f'stage1|E06|DS_J|r{rep}|p')
        r = V2.score_task_v2(c, obj)
        rows = r['rows']
        tp = [x['fact_id'] for x in rows if x['status'] == 'TP']
        wrong = [x['fact_id'] for x in rows if x['status'].startswith('VALUE')]
        abst = [x['fact_id'] for x in rows if x['status'] == 'ABSENT']
        tp_ans = [t for t in tp if t not in UNCOVERABLE]
        n_ans = sum(1 for fid in facts if fid not in UNCOVERABLE)
        answers = {a.get('fact_id'): a for a in (obj or {}).get('answers', []) if isinstance(a, dict)}
        j_echo = [fid for fid in j if Q1._norm(str(answers.get(fid, {}).get('value',''))) == Q1._norm(j[fid]['value'])]
        row = dict(rep=rep, q_all=r['q'], q_answerable=round(len(tp_ans)/n_ans, 4),
                   tp=tp, wrong=wrong, abst=abst,
                   precision=round(len(tp)/max(1, len(tp)+len(wrong)), 3),
                   support=r.get('evidence_support_rate', None) if 'evidence_support_rate' in r else None,
                   j_echoed=j_echo, uncoverable_handled={f: (f in abst) for f in UNCOVERABLE})
        results.append(row)
        print(f"r{rep}: Q_all={row['q_all']} Q_answerable={row['q_answerable']} TP={len(tp)} {tp}")
        print(f"     wrong={wrong} abst={abst} P={row['precision']} J_echo={j_echo}")
    json.dump(dict(batch='STAGE1_E06', caps=CAPS,
                   used=dict(calls=calls_used[0], yuan=round(yuan_used[0],4), tokens=tok_used[0]),
                   results=results), open(f'{OUT}/STAGE1_E06_RESULTS.json','w'), ensure_ascii=False, indent=1)
    print(f"DONE: {calls_used[0]}/{CAPS['calls']} calls, {tok_used[0]}/{CAPS['tokens']} tok, ¥{yuan_used[0]:.4f}")

if __name__ == '__main__':
    main()
