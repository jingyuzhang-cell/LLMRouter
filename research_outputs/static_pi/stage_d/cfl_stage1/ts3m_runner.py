"""TS-3M: GLM-5.3 (non-flash) SINK vs frozen baselines (authorized: 4+1 calls /
24K tokens / 0.15 yuan). Anthropic endpoint, thinking disabled, key=bigmodel-api-5
(read from provider config, never written to disk). Prompt sha asserted equal to
the frozen baseline prompts (via deepseek-body sha). KANGMEI -> MIN-B B_new prompt;
MVR1 -> TS-1 B_sel prompt. Conservative pricing 4e-6/16e-6 per token.
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
from stage_d_v2_transport import build_request
from cfl3_min_runner import four_part_check, load_contract
from ts1_runner import SEL_BLOCK

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/TS3M_LEDGER.jsonl'
CAPS = dict(calls=5, tokens=24_000, yuan=0.15)
BLIND = dict(KANGMEI={'B3', 'B4', 'B5', 'B6', 'C1'},
             MVR1={'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F12'})
BASE = dict(KANGMEI=dict(q=0.571, wrong=5), MVR1=dict(q=0.438, wrong=8.5))
ENDPOINT = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
calls_used = [0]; yuan_used = [0.0]; tok_used = [0]; reserve = [1]


def api5_key():
    cfg = json.load(open('/root/.zcode/v2/provider_config.json'))
    for r in cfg['config']['providerConfigRules']['providerRules']:
        if r.get('providerId') == 'bigmodel-api-5':
            return (r['config']['access']['apiKey'] or '').strip()
    raise RuntimeError('api-5 key not found')


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


def real_call(system, user, purpose):
    for attempt in (1, 2):
        if attempt == 2:
            if reserve[0] < 1:
                raise RuntimeError('NO RESERVE LEFT')
            reserve[0] -= 1
            print(f'  [reserve consumed: {purpose}]')
        if calls_used[0] >= CAPS['calls']:
            raise RuntimeError('CALLS CAP')
        if yuan_used[0] + 0.02 > CAPS['yuan'] * 0.95:
            raise RuntimeError('YUAN CAP')
        body = {'model': 'GLM-5.3', 'max_tokens': MAXTOK['p'],
                'thinking': {'type': 'disabled'}, 'system': system,
                'messages': [{'role': 'user', 'content': user}]}
        req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), method='POST')
        k = api5_key()
        req.add_header('content-type', 'application/json')
        req.add_header('x-api-key', k)
        req.add_header('authorization', 'Bearer ' + k)
        req.add_header('anthropic-version', '2023-06-01')
        t0 = time.monotonic()
        d = None
        try:
            for backoff in (0, 60, 120, 180):
                if backoff:
                    print(f'  [429 backoff {backoff}s: {purpose}]'); time.sleep(backoff)
                try:
                    with urllib.request.urlopen(req, timeout=240) as r:
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
        # anthropic response shape
        blocks = d.get('content', [])
        text = ''.join(b.get('text', '') for b in blocks if isinstance(b, dict))
        u = d.get('usage', {})
        tin = u.get('input_tokens', 0); tout = u.get('output_tokens', 0)
        yuan = round(tin * 4e-6 + tout * 16e-6, 8)  # conservative assumed price
        lat = round(time.monotonic() - t0, 3)
        calls_used[0] += 1; yuan_used[0] += yuan; tok_used[0] += tin + tout
        with open(LEDGER, 'a') as f:
            f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias='glm53',
                                    purpose=purpose, prompt_sha256=hashlib.sha256(
                                        (system + '||' + user).encode()).hexdigest()[:16],
                                    usage=dict(input_tokens=tin, output_tokens=tout),
                                    accounting_yuan_assumed=yuan, latency_s=lat, text=text),
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
    p_k = bnew_prompt(c_k, pool_k, sel=False)
    c_m = load_any('MVR1')
    ents_m = []
    for node in ('e0', 'e1'):
        ents_m += parse2(extract_any(led[f'qp8r|MVR1|DS|r1|{node}']['text']) or {})
    pool_m = dedup(ents_m, c_m)
    p_m = bnew_prompt(c_m, pool_m, sel=True)
    mb = {json.loads(l)['purpose']: json.loads(l) for l in open(f'{OUT}/CFL3_MIN_B_LEDGER.jsonl')}
    ts1 = {json.loads(l)['purpose']: json.loads(l) for l in open(f'{OUT}/TS1_LEDGER.jsonl')}
    assert hashlib.sha256(json.dumps(build_request('deepseek', P_SYS, p_k, MAXTOK['p']),
        sort_keys=True, ensure_ascii=False).encode()).hexdigest() == \
        mb['cfl3minb|KANGMEI|B_new|r1|p']['prompt_sha256'], 'KANGMEI DRIFT'
    assert hashlib.sha256(json.dumps(build_request('deepseek', P_SYS, p_m, MAXTOK['p']),
        sort_keys=True, ensure_ascii=False).encode()).hexdigest() == \
        ts1['ts1|MVR1|B_sel|r1|p']['prompt_sha256'], 'MVR1 DRIFT'
    print('prompt sha assertions OK (KANGMEI=MIN-B B_new, MVR1=TS-1 B_sel)')
    results = []
    for task, contract, prompt in (('KANGMEI', c_k, p_k), ('MVR1', c_m, p_m)):
        for rep in (1, 2):
            obj, lat, y = real_call(P_SYS, prompt, f'ts3m|{task}|glm53|r{rep}|p')
            res = Q1.score_task(contract, obj) if obj else None
            row = dict(task=task, rep=rep, latency_s=lat, yuan_assumed=y)
            if res:
                rows_ = res['rows']
                tp = [x['fact_id'] for x in rows_ if x['status'] == 'TP']
                wrong = [x['fact_id'] for x in rows_ if x['status'].startswith('VALUE')]
                row.update(q=res['q'], tp=tp, wrong=wrong,
                           abst=sum(1 for x in rows_ if x['status'] == 'ABSENT'),
                           precision=round(len(tp) / max(1, len(tp) + len(wrong)), 3),
                           support=res['evidence_support_rate'],
                           blind_fixed=sorted(set(tp) & BLIND[task]))
            else:
                row.update(parse_fail=True)
            results.append(row)
            print(f"{task} GLM-5.3 r{rep}: Q={row.get('q')} (base {BASE[task]['q']}) "
                  f"P={row.get('precision')} TP={len(row.get('tp', []))} "
                  f"wrong={len(row.get('wrong', []))} (base {BASE[task]['wrong']}) "
                  f"abst={row.get('abst')} blind={row.get('blind_fixed')} lat={lat}s")
    json.dump(dict(batch='TS3M', caps=CAPS,
                   used=dict(calls=calls_used[0], yuan_assumed=round(yuan_used[0], 4),
                             tokens=tok_used[0], reserve_left=reserve[0]),
                   results=results), open(f'{OUT}/TS3M_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\nDONE: calls={calls_used[0]}/{CAPS['calls']} tokens={tok_used[0]}/{CAPS['tokens']} "
          f"¥assumed={yuan_used[0]:.4f}/{CAPS['yuan']} reserve_left={reserve[0]}")


if __name__ == '__main__':
    main()
