"""GLM-SINK cross-model validation (authorized): 4 calls (KANGMEI x2, MVR1 x2)
+ 1 reserve. Same frozen pools, same prompts (sha-asserted vs DS baseline
ledger rows); ONLY variable = SINK model (glm53flash vs deepseek).
Caps: 5 calls / 22,000 tokens / 0.06 yuan.
"""
import json, os, sys, time, hashlib, urllib.request, urllib.error

SD = '/root/research_outputs/static_pi/stage_d'
sys.path.insert(0, f'{SD}/quality_phase_v1')
sys.path.insert(0, f'{SD}/qp3')
sys.path.insert(0, f'{SD}/v2')
sys.path.insert(0, SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import qp5a_pure_prep as PP
import qp1_prompts as P1
import scorer_qp1 as Q1
from qp4_factorial import VALUE_FORM_RULES
from qp5a_pure_prep import COPY_RULE
from qp1_prompts import P_SYS, MAXTOK
from stage_d_v2_transport import build_request, glm_key, MODEL_CFG
from cfl3_min_runner import four_part_check, load_contract
from ts1_runner import SEL_BLOCK

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/GLMSINK_LEDGER.jsonl'
CAPS = dict(calls=5, tokens=22_000, yuan=0.06)
calls_used = [0]; yuan_used = [0.0]; tok_used = [0]; reserve = [1]


def load_led(*paths):
    led = {}
    for p in paths:
        for l in open(p):
            x = json.loads(l); led[x['purpose']] = x
    return led


def build_pool(entries, contract):
    pool, seen = [], set()
    for e in entries:
        if not four_part_check(e, contract)[0]:
            continue
        v = e.get('raw') or e.get('value')
        key = (str(e.get('field')), str(e.get('bucket')), str(e.get('doc')),
               str(e.get('page')), Q1._norm(e.get('quote') or ''), Q1._norm(str(v)))
        if key in seen:
            continue
        seen.add(key); pool.append(e)
    return pool


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


def real_call(user, purpose):
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
        body = build_request('glm53flash', P_SYS, user, MAXTOK['p'])
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        req = urllib.request.Request(MODEL_CFG['glm53flash']['url'],
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        req.add_header('authorization', 'Bearer ' + glm_key())
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
            f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias='glm53flash',
                                    purpose=purpose, prompt_sha256=sha,
                                    usage=dict(input_tokens=tin, output_tokens=tout),
                                    accounting_yuan=yuan, latency_s=lat, text=text),
                               ensure_ascii=False) + '\n')
        if tok_used[0] >= CAPS['tokens']:
            raise RuntimeError('TOKEN CAP')
        obj = extract_any(text)
        if obj is None and attempt == 1:
            continue
        return obj, lat, yuan, pool if False else None
    raise RuntimeError('unreachable')


def main():
    # KANGMEI: MIN-B pool + MIN-B B_new prompt (no SEL block); sha vs MIN-B ledger
    c_k = load_contract()
    r3 = load_led(f'{OUT}/CFL3_MIN_LEDGER.jsonl')
    ents_k = []
    for rep in (1, 2):
        ents_k += parse2(extract_any(r3[f'cfl3min|KANGMEI|C|r{rep}|e1_reext']['text']) or {})
    pool_k = build_pool(ents_k, c_k)
    p_k = bnew_prompt(c_k, pool_k, sel=False)
    sha_k = hashlib.sha256(json.dumps(build_request('glm53flash', P_SYS, p_k, MAXTOK['p']),
                                      sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    mb = load_led(f'{OUT}/CFL3_MIN_B_LEDGER.jsonl')
    # MIN-B rows were deepseek bodies; compare the DS-body sha instead
    sha_k_ds = hashlib.sha256(json.dumps(build_request('deepseek', P_SYS, p_k, MAXTOK['p']),
                                         sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert sha_k_ds == mb['cfl3minb|KANGMEI|B_new|r1|p']['prompt_sha256'], 'KANGMEI PROMPT DRIFT'
    print(f'KANGMEI: pool={len(pool_k)} prompt sha == MIN-B B_new r1 (DS body): OK')
    # MVR1: CrossTask pool + TS-1 B_sel prompt (with SEL block); sha vs TS1 ledger
    led9 = load_led(f'{SD}/qp8/QP8R_STAGE1_LEDGER.jsonl', f'{SD}/qp9/QP9_LEDGER.jsonl')
    p_ = [x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
          if x['event_key'] == 'MVR1'][0]['contract']
    if not os.path.isabs(p_): p_ = f'{SD}/v23a/{p_}'
    c_m = json.load(open(p_))
    ents_m = []
    for node in ('e0', 'e1'):
        ents_m += parse2(extract_any(led9[f'qp8r|MVR1|DS|r1|{node}']['text']) or {})
    pool_m = build_pool(ents_m, c_m)
    p_m = bnew_prompt(c_m, pool_m, sel=True)
    sha_m_ds = hashlib.sha256(json.dumps(build_request('deepseek', P_SYS, p_m, MAXTOK['p']),
                                         sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    ts1 = load_led(f'{OUT}/TS1_LEDGER.jsonl')
    assert sha_m_ds == ts1['ts1|MVR1|B_sel|r1|p']['prompt_sha256'], 'MVR1 PROMPT DRIFT'
    print(f'MVR1: pool={len(pool_m)} prompt sha == TS-1 B_sel r1 (DS body): OK')

    baselines = dict(
        KANGMEI=dict(q=[0.571429, 0.571429], tp=[8, 8], wrong=[5, 5], abst=[1, 1],
                     src='CFL-3-MIN-B B_new'),
        MVR1=dict(q=[0.25, 0.25], tp=[4, 4], wrong=[12, 11], abst=[0, 1],
                  src='TS-1 B_sel'))
    results = []
    order = [('KANGMEI', c_k, p_k, pool_k), ('MVR1', c_m, p_m, pool_m)] * 1
    for task, contract, prompt, pool in [('KANGMEI', c_k, p_k, pool_k), ('MVR1', c_m, p_m, pool_m)]:
        b = baselines[task]
        for rep in (1, 2):
            obj, lat, y, _ = real_call(prompt, f'glmsink|{task}|B_glm|r{rep}|p')
            res = Q1.score_task(contract, obj) if obj else None
            row = dict(task=task, rep=rep, latency_s=lat, yuan=y)
            if res:
                rows_ = res['rows']
                tp_ids = [x['fact_id'] for x in rows_ if x['status'] == 'TP']
                answers = {a.get('fact_id'): a for a in (obj or {}).get('answers', [])
                           if isinstance(a, dict)}
                pq = [Q1._norm(e.get('quote') or '') for e in pool]
                traceable = all(any(Q1._norm(answers.get(fid, {}).get('quote') or '') and
                                    (Q1._norm(answers[fid]['quote'] or '') == q or
                                     Q1._norm(answers[fid]['quote'] or '') in q or q in Q1._norm(answers[fid]['quote'] or ''))
                                    for q in pq if q) for fid in tp_ids)
                row.update(q=res['q'], tp=tp_ids,
                           wrong=[x['fact_id'] for x in rows_ if x['status'].startswith('VALUE')],
                           abst=sum(1 for x in rows_ if x['status'] == 'ABSENT'),
                           support_rate=res['evidence_support_rate'],
                           tp_traceable_to_pool=traceable,
                           base_q=b['q'][rep - 1], base_tp=b['tp'][rep - 1],
                           base_wrong=b['wrong'][rep - 1], base_abst=b['abst'][rep - 1])
            else:
                row.update(parse_fail=True, base_q=b['q'][rep - 1])
            results.append(row)
            print(f"{task} B_glm r{rep}: Q={row.get('q'):.3f} (DS {b['q'][rep-1]:.3f}) "
                  f"TP={len(row.get('tp', []))} (DS {b['tp'][rep-1]}) "
                  f"wrong={len(row.get('wrong', []))} (DS {b['wrong'][rep-1]}) "
                  f"abst={row.get('abst')} trace={row.get('tp_traceable_to_pool')} lat={lat}s")
    json.dump(dict(batch='GLM_SINK', caps=CAPS,
                   used=dict(calls=calls_used[0], yuan=round(yuan_used[0], 4),
                             tokens=tok_used[0], reserve_left=reserve[0]),
                   results=results), open(f'{OUT}/GLMSINK_RESULTS.json', 'w'),
              ensure_ascii=False, indent=1)
    print(f"\nDONE: calls={calls_used[0]}/{CAPS['calls']} tokens={tok_used[0]}/{CAPS['tokens']} "
          f"¥{yuan_used[0]:.4f}/{CAPS['yuan']} reserve_left={reserve[0]}")


if __name__ == '__main__':
    main()
