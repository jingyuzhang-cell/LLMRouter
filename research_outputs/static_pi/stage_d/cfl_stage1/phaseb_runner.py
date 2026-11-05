"""Phase B: MVR1 DS+J minimal validation. TS-4's MVR1 B-arm prompt (B_sel base +
frozen J block, sha-asserted) with deepseek SINK. 2 reps + 1 reserve.
Caps: 3 calls / 12K tokens / 0.04 yuan."""
import json, os, sys, time, hashlib, urllib.request, urllib.error
SD = '/root/research_outputs/static_pi/stage_d'
sys.path.insert(0, f'{SD}/quality_phase_v1'); sys.path.insert(0, f'{SD}/qp3')
sys.path.insert(0, f'{SD}/v2'); sys.path.insert(0, SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import scorer_qp1 as Q1
import scorer_qp1_v2 as V2
from qp1_prompts import P_SYS, MAXTOK
from stage_d_v2_transport import build_request, ds_key, MODEL_CFG
from cfl3_min_runner import four_part_check
from ts4_runner import dedup, bnew_prompt, j_block, build_j_rows

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/PHASEB_LEDGER.jsonl'
CAPS = dict(calls=3, tokens=12_000, yuan=0.04)
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
        t0 = time.monotonic(); d = None
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
    c_m = load_any('MVR1')
    ents = []
    for node in ('e0', 'e1'):
        ents += parse2(extract_any(led[f'qp8r|MVR1|DS|r1|{node}']['text']) or {})
    pool = dedup(ents, c_m)
    j = build_j_rows(c_m, pool, 'MVR1')
    p = bnew_prompt(c_m, pool, sel=True) + '\n\n' + j_block(j)
    ts1 = {json.loads(l)['purpose']: json.loads(l) for l in open(f'{OUT}/TS1_LEDGER.jsonl')}
    base_sha = hashlib.sha256(json.dumps(build_request('deepseek', P_SYS,
        bnew_prompt(c_m, pool, sel=True), MAXTOK['p']), sort_keys=True,
        ensure_ascii=False).encode()).hexdigest()
    assert base_sha == ts1['ts1|MVR1|B_sel|r1|p']['prompt_sha256'], 'PROMPT DRIFT'
    print(f'prompt base sha OK (TS-1 B_sel); J rows={sorted(j)}; prompt={len(p)} chars')
    results = []
    for rep in (1, 2):
        obj = real_call(p, f'phaseb|MVR1|DS_J|r{rep}|p')
        r2v = V2.score_task_v2(c_m, obj)
        rows = r2v['rows']
        tp = [x['fact_id'] for x in rows if x['status'] == 'TP']
        wrong = [x['fact_id'] for x in rows if x['status'].startswith('VALUE')]
        # v2b value-axis (unit inheritance)
        from decimal import Decimal
        facts = {f['fact_id']: f for f in c_m['required_facts']}
        answers = {a.get('fact_id'): a for a in obj.get('answers', []) if isinstance(a, dict)}
        tp2b = 0
        for fid, f in facts.items():
            a = answers.get(fid)
            if not a or a.get('value') in (None, ''): continue
            x = V2._num_unit(a.get('value')); y = V2._num_unit(f.get('value'))
            if not (x and y and x[0] == y[0]): continue
            doc = c_m['source_pages'].get(str(a.get('doc')))
            pg = (doc or {}).get('pages', {}).get(str(a.get('page')))
            if pg and Q1._norm(a.get('quote') or '') and Q1._norm(a.get('quote')) in Q1._norm(pg.get('text','')) \
               and Q1.value_in_quote(a.get('value'), a.get('quote','')):
                tp2b += 1
        row = dict(rep=rep, q_v1=Q1.score_task(c_m, obj)['q'], q_v2=r2v['q'],
                   q_v2b=round(tp2b/len(facts), 4), tp=tp, wrong=wrong,
                   abst=sum(1 for x in rows if x['status'] == 'ABSENT'),
                   precision=round(len(tp)/max(1,len(tp)+len(wrong)),3))
        results.append(row)
        print(f"r{rep}: v2={row['q_v2']} v2b={row['q_v2b']} TP={len(tp)} wrong={len(wrong)} "
              f"abst={row['abst']} P={row['precision']} tp_list={tp}")
    json.dump(dict(batch='PHASE_B', caps=CAPS,
                   used=dict(calls=calls_used[0], yuan=round(yuan_used[0],4), tokens=tok_used[0]),
                   results=results), open(f'{OUT}/PHASEB_RESULTS.json','w'), ensure_ascii=False, indent=1)
    print(f"DONE: {calls_used[0]}/{CAPS['calls']} calls, {tok_used[0]}/{CAPS['tokens']} tok, ¥{yuan_used[0]:.4f}")

if __name__ == '__main__':
    main()
