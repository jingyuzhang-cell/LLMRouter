"""TS-2: slot-level candidate matching (authorized: 4 calls / ~0.03 yuan).
KANGMEI -> deepseek x2; MVR1 -> glm53flash x2. Gold-blind candidates:
name_matches OR subject/predicate in entry-name OR subject in quote.
Frozen gates: task-mean Q>=0.70; per-rep precision>=0.70 and wrong<=baseline;
blind fixes KANGMEI>=2/5, MVR1>=4/8; F1-F4 still wrong -> pivot declared.
No reserve authorized: transport/parse failure -> honest stop. Caps 4/18K/0.05.
"""
import json, os, sys, time, hashlib, urllib.request, urllib.error

SD = '/root/research_outputs/static_pi/stage_d'
sys.path.insert(0, f'{SD}/quality_phase_v1')
sys.path.insert(0, f'{SD}/qp3')
sys.path.insert(0, f'{SD}/v2')
sys.path.insert(0, SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import qp1_prompts as P1
import qp3_primitives as P3
import scorer_qp1 as Q1
from qp1_prompts import P_SYS, MAXTOK
from stage_d_v2_transport import build_request, ds_key, glm_key, MODEL_CFG
from cfl3_min_runner import four_part_check, load_contract
from ts1_runner import SEL_BLOCK

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/TS2_LEDGER.jsonl'
CAPS = dict(calls=4, tokens=18_000, yuan=0.05)
BLIND = dict(KANGMEI={'B3', 'B4', 'B5', 'B6', 'C1'},
             MVR1={'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F12'})
BASE = dict(KANGMEI=dict(model='deepseek', q=0.571, wrong=5.0),
            MVR1=dict(model='glm53flash', q=0.438, wrong=8.5))
calls_used = [0]; yuan_used = [0.0]; tok_used = [0]


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
        key = (str(e.get('field')), str(e.get('doc')), str(e.get('page')),
               Q1._norm(e.get('quote') or ''), Q1._norm(str(v)))
        if key in seen:
            continue
        seen.add(key); pool.append(e)
    return pool


def candidates(f, pool):
    subj = str(f.get('subject') or ''); pred = str(f.get('predicate') or '')
    out = []
    for e in pool:
        name = f"{e.get('field') or ''}|{e.get('bucket') or ''}|{e.get('predicate') or ''}"
        if (P3.name_matches(e, f) or (subj and subj in name) or (pred and pred in name)
                or (subj and subj in (e.get('quote') or ''))):
            out.append(e)
    return out


def slot_prompt(contract, pool):
    facts = [f for f in contract['required_facts']
             if f.get('status') not in ('EXCLUDED', 'NOT_APPLICABLE')]
    blocks = []
    for f in facts:
        cands = candidates(f, pool)
        lines = [f"槽位 {f['fact_id']}（主体：{f.get('subject')}；要求：{f.get('predicate')}）"]
        if cands:
            for i, e in enumerate(cands, 1):
                lines.append(f"  候选{i}: field={e.get('field') or e.get('bucket')} | "
                             f"value={e.get('raw') or e.get('value')} | doc={e.get('doc')} | "
                             f"page={e.get('page')} | quote={e.get('quote', '')}")
        else:
            lines.append('  候选: 无（该槽位无候选证据，应写入 abstentions）')
        blocks.append('\n'.join(lines))
    return (P1.p_user(contract, {}, {}, [], 'E1') + '\n\n【逐槽候选证据】\n' +
            '\n\n'.join(blocks) + SEL_BLOCK)


def real_call(alias, user, purpose):
    if calls_used[0] >= CAPS['calls']:
        raise RuntimeError('CALLS CAP')
    if yuan_used[0] + 0.008 > CAPS['yuan'] * 0.95:
        raise RuntimeError('YUAN CAP')
    body = build_request(alias, P_SYS, user, MAXTOK['p'])
    sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    req = urllib.request.Request(MODEL_CFG[alias]['url'], data=json.dumps(body).encode(), method='POST')
    req.add_header('content-type', 'application/json')
    req.add_header('authorization', 'Bearer ' + (ds_key() if alias == 'deepseek' else glm_key()))
    t0 = time.monotonic()
    d = None
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
    if d is None:
        raise RuntimeError('transport failed — honest stop (no reserve authorized)')
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
    return extract_any(text), lat, yuan


def main():
    r3 = {json.loads(l)['purpose']: json.loads(l) for l in open(f'{OUT}/CFL3_MIN_LEDGER.jsonl')}
    led = {}
    for pth in (f'{SD}/qp8/QP8R_STAGE1_LEDGER.jsonl', f'{SD}/qp9/QP9_LEDGER.jsonl'):
        for l in open(pth):
            x = json.loads(l); led[x['purpose']] = x
    pools = {}
    c_k = load_contract()
    ents_k = []
    for rep in (1, 2):
        ents_k += parse2(extract_any(r3[f'cfl3min|KANGMEI|C|r{rep}|e1_reext']['text']) or {})
    pools['KANGMEI'] = (c_k, dedup(ents_k, c_k))
    c_m = load_any('MVR1')
    ents_m = []
    for node in ('e0', 'e1'):
        ents_m += parse2(extract_any(led[f'qp8r|MVR1|DS|r1|{node}']['text']) or {})
    pools['MVR1'] = (c_m, dedup(ents_m, c_m))
    results = []
    for task in ('KANGMEI', 'MVR1'):
        contract, pool = pools[task]
        facts = [f for f in contract['required_facts']
                 if f.get('status') not in ('EXCLUDED', 'NOT_APPLICABLE')]
        zeros = [f['fact_id'] for f in facts if not candidates(f, pool)]
        prompt = slot_prompt(contract, pool)
        print(f"== {task} ({BASE[task]['model']}): pool={len(pool)} zero-candidate slots={zeros} "
              f"prompt={len(prompt)} chars")
        for rep in (1, 2):
            obj, lat, y = real_call(BASE[task]['model'], prompt, f'ts2|{task}|slot|r{rep}|p')
            res = Q1.score_task(contract, obj) if obj else None
            row = dict(task=task, rep=rep, latency_s=lat, yuan=y)
            if res:
                rows_ = res['rows']
                tp = [x['fact_id'] for x in rows_ if x['status'] == 'TP']
                wrong = [x['fact_id'] for x in rows_ if x['status'].startswith('VALUE')]
                abst = sum(1 for x in rows_ if x['status'] == 'ABSENT')
                row.update(q=res['q'], tp=tp, wrong=wrong, abst=abst,
                           precision=round(len(tp) / max(1, len(tp) + len(wrong)), 3),
                           blind_fixed=sorted(set(tp) & BLIND[task]))
            else:
                row.update(parse_fail=True)
            results.append(row)
            print(f"  r{rep}: Q={row.get('q')} P={row.get('precision')} TP={len(row.get('tp', []))} "
                  f"wrong={len(row.get('wrong', []))} abst={row.get('abst')} "
                  f"blind_fixed={row.get('blind_fixed')}")
    json.dump(dict(batch='TS2', caps=CAPS,
                   used=dict(calls=calls_used[0], yuan=round(yuan_used[0], 4),
                             tokens=tok_used[0]), results=results),
              open(f'{OUT}/TS2_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\nDONE: calls={calls_used[0]}/{CAPS['calls']} tokens={tok_used[0]}/{CAPS['tokens']} "
          f"¥{yuan_used[0]:.4f}/{CAPS['yuan']}")


if __name__ == '__main__':
    main()
