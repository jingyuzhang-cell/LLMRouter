"""CFL-3-CrossTask runner (Plan alpha, authorized): 3 tasks x 2 arms x 2 reps.
MVR1 (DS, primary), ZEDA (DS, weak-pool), E06 (GLM pool + GLM SINK, family test).
Pools = frozen caches only (zero E calls). A_old = frozen old chain; B_new =
per-entry table (both constructions verbatim from cfl3_min_b_runner).
Caps: 14 calls (12 normal + 2 reserve, transport/parse only) / 52K tokens / 0.08 yuan.
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
import qp3_primitives as P3
import scorer_qp1 as Q1
from qp4_factorial import VALUE_FORM_RULES
from qp5a_pure_prep import COPY_RULE
from qp1_prompts import P_SYS, MAXTOK
from stage_d_v2_transport import build_request, ds_key, glm_key, MODEL_CFG
from cfl3_min_runner import four_part_check

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/CFL3_CROSSTASK_LEDGER.jsonl'
CAPS = dict(calls=14, tokens=52_000, yuan=0.08)
TASKS = dict(MVR1=dict(model='deepseek', src='qp8r|{t}|DS|r1|{n}'),
             ZEDA=dict(model='deepseek', src='qp9|{t}|E|deepseek|{n}'),
             E06=dict(model='glm53flash', src='qp8r|{t}|GLM|r1|{n}'))
calls_used = [0]; yuan_used = [0.0]; tok_used = [0]; reserve = [2]


def load_ledgers():
    led = {}
    for p in (f'{SD}/qp8/QP8R_STAGE1_LEDGER.jsonl', f'{SD}/qp9/QP9_LEDGER.jsonl'):
        for l in open(p):
            x = json.loads(l); led[x['purpose']] = x
    return led


def load_contract(t):
    p = [x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if x['event_key'] == t][0]['contract']
    if not os.path.isabs(p): p = f'{SD}/v23a/{p}'
    return json.load(open(p))


def real_call(alias, system, user, purpose):
    for attempt in (1, 2):
        if attempt == 2:
            if reserve[0] < 1:
                raise RuntimeError('NO RESERVE LEFT')
            reserve[0] -= 1
            print(f'  [reserve consumed: {purpose}]')
        if calls_used[0] >= CAPS['calls']:
            raise RuntimeError('CALLS CAP')
        if yuan_used[0] + 0.01 > CAPS['yuan'] * 0.95:
            raise RuntimeError('YUAN CAP')
        body = build_request(alias, system, user, MAXTOK['p'])
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        req = urllib.request.Request(MODEL_CFG[alias]['url'],
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        req.add_header('authorization', 'Bearer ' + (ds_key() if alias == 'deepseek' else glm_key()))
        t0 = time.monotonic()
        for backoff in (0, 60, 120, 180):
            if backoff:
                print(f'  [429 backoff {backoff}s: {purpose}]')
                time.sleep(backoff)
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


def evidence_retention(obj, pool):
    answers = [a for a in (obj or {}).get('answers', []) if isinstance(a, dict)]
    covered = 0
    for e in pool:
        hit = False
        for a in answers:
            if str(a.get('doc')) == str(e.get('doc')) and str(a.get('page')) == str(e.get('page')):
                nq, ne = Q1._norm(a.get('quote') or ''), Q1._norm(e.get('quote') or '')
                if nq and ne and (nq == ne or nq in ne or ne in nq):
                    hit = True; break
        covered += hit
    return covered / len(pool) if pool else None


def main():
    led = load_ledgers()
    done = {}
    if os.path.exists(LEDGER):
        for l in open(LEDGER):
            x = json.loads(l)
            done[x['purpose']] = x
            calls_used[0] += 1; yuan_used[0] += x['accounting_yuan']
            tok_used[0] += x['usage']['input_tokens'] + x['usage']['output_tokens']
        reserve[0] = 0  # both reserves consumed by transport failures (401 pair, then 429 pair)
        print(f'[resume] {len(done)} completed cells replayed; reserve={reserve[0]}')
    all_results = []
    for task, cfg in TASKS.items():
        contract = load_contract(task)
        pool, seen = [], set()
        for node in ('e0', 'e1'):
            r = led[cfg['src'].format(t=task, n=node)]
            for e in parse2(extract_any(r['text']) or {}):
                if not four_part_check(e, contract)[0]:
                    continue
                v = e.get('raw') or e.get('value')
                key = (str(e.get('field')), str(e.get('bucket')), str(e.get('predicate')),
                       str(e.get('doc')), str(e.get('page')),
                       Q1._norm(e.get('quote') or ''), Q1._norm(str(v)))
                if key in seen:
                    continue
                seen.add(key); pool.append(e)
        mf = {}
        for e in pool:
            k = str(e.get('field') or e.get('bucket') or '')
            if k and e.get('value') not in (None, ''):
                mf.setdefault(k, e.get('value'))
        ev_map = PP.match_evidence(mf, pool, contract)
        p_old = PP.render(contract, {}, mf, ev_map, with_evidence=True)
        rows = [f"{e.get('field') or e.get('bucket')} | value={e.get('raw') or e.get('value')} "
                f"| doc={e.get('doc')} | page={e.get('page')} | quote={e.get('quote', '')}" for e in pool]
        p_new = (P1.p_user(contract, {'facts': [dict(field=k, value=v) for k, v in mf.items()]}, {}, [], 'E1')
                 + '\n\n' + VALUE_FORM_RULES
                 + '\n\n已核验证据表（逐条）：\n' + '\n'.join(rows) + '\n\n' + COPY_RULE)
        print(f"== {task} ({cfg['model']}): pool={len(pool)} m_keys={len(mf)} ev_map={len(ev_map)}")
        for arm, prompt in (('A_old', p_old), ('B_new', p_new)):
            for rep in (1, 2):
                purpose = f'cfl3ct|{task}|{arm}|r{rep}|p'
                hit = done.get(purpose)
                if hit is not None:
                    obj = extract_any(hit['text']); lat = hit['latency_s']; y = hit['accounting_yuan']
                else:
                    obj, lat, y = real_call(cfg['model'], P_SYS, prompt, purpose)
                res = Q1.score_task(contract, obj) if obj else None
                row = dict(task=task, arm=arm, rep=rep, latency_s=lat, yuan=y)
                if res:
                    rows_ = res['rows']
                    row.update(q=res['q'],
                               tp=[x['fact_id'] for x in rows_ if x['status'] == 'TP'],
                               wrong=[x['fact_id'] for x in rows_ if x['status'].startswith('VALUE')],
                               abst=sum(1 for x in rows_ if x['status'] == 'ABSENT'),
                               retention=evidence_retention(obj, pool))
                else:
                    row.update(parse_fail=True)
                all_results.append(row)
                print(f"  {arm} r{rep}: Q={row.get('q')} TP={len(row.get('tp', []))} "
                      f"wrong={len(row.get('wrong', []))} abst={row.get('abst')} "
                      f"ret={row.get('retention')} lat={lat}s")
        # per-task P_marginal (rep means)
        def m(arm, k):
            vs = [r[k] for r in all_results if r['task'] == task and r['arm'] == arm and not r.get('parse_fail')]
            return sum(vs) / len(vs) if vs else None
        dtp = (lambda a, b: (sum(len(r.get('tp', [])) for r in all_results if r['task']==task and r['arm']==b) -
                             sum(len(r.get('tp', [])) for r in all_results if r['task']==task and r['arm']==a)))
        dwr = (lambda a, b: (sum(len(r.get('wrong', [])) for r in all_results if r['task']==task and r['arm']==b) -
                             sum(len(r.get('wrong', [])) for r in all_results if r['task']==task and r['arm']==a)))
        dt_, dw = dtp('A_old', 'B_new'), dwr('A_old', 'B_new')
        pm = round(dt_ / (dt_ + dw), 3) if dt_ > 0 and (dt_ + dw) > 0 else 'N/A'
        print(f"  -> dTP={dt_} dWrong={dw} P_marginal={pm}\n")
    json.dump(dict(batch='CFL3_CROSSTASK', caps=CAPS,
                   used=dict(calls=calls_used[0], yuan=round(yuan_used[0], 4),
                             tokens=tok_used[0], reserve_left=reserve[0]),
                   results=all_results), open(f'{OUT}/CFL3_CROSSTASK_RESULTS.json', 'w'),
              ensure_ascii=False, indent=1)
    print(f"DONE: calls={calls_used[0]}/{CAPS['calls']} tokens={tok_used[0]}/{CAPS['tokens']} "
          f"¥{yuan_used[0]:.4f}/{CAPS['yuan']} reserve_left={reserve[0]}")


if __name__ == '__main__':
    main()
