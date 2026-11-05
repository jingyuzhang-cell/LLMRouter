"""CFL-3-MIN-B runner (prereg v1.1): same frozen evidence pool, two table
constructions, 4 interleaved SINK calls. A_old = frozen m_facts->match_evidence
->PP.render chain; B_new = per-entry table on the same p_user base. Caps:
4 calls / 30,000 tokens / 0.04 yuan; reserve 2 (transport/parse only)."""
import json, os, sys, time, hashlib, urllib.request

SD = '/root/research_outputs/static_pi/stage_d'
sys.path.insert(0, f'{SD}/quality_phase_v1')
sys.path.insert(0, f'{SD}/qp3')
sys.path.insert(0, f'{SD}/v2')
sys.path.insert(0, SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import qp5a_pure_prep as PP
import qp3_primitives as P3
import scorer_qp1 as Q1
import qp1_prompts as P1
from qp5a_pure_prep import COPY_RULE
from qp4_factorial import VALUE_FORM_RULES
from qp1_prompts import P_SYS, MAXTOK
from stage_d_v2_transport import build_request, ds_key, MODEL_CFG
from cfl3_min_runner import load_contract, four_part_check

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/CFL3_MIN_B_LEDGER.jsonl'
CAPS = dict(calls=4, tokens=30_000, yuan=0.04)
calls_used = [0]; yuan_used = [0.0]; tok_used = [0]; reserve = [2]


def real_call(system, user, purpose):
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
        body = build_request('deepseek', system, user, MAXTOK['p'])
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
            if attempt == 1:
                continue
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
                                    accounting_yuan=yuan, latency_s=round(time.monotonic() - t0, 3),
                                    text=text), ensure_ascii=False) + '\n')
        if tok_used[0] >= CAPS['tokens']:
            raise RuntimeError('TOKEN CAP')
        obj = extract_any(text)
        if obj is None and attempt == 1:
            continue
        return obj, text
    raise RuntimeError('unreachable')


def main():
    contract = load_contract()
    facts = [f for f in contract['required_facts']
             if f.get('status') not in ('EXCLUDED', 'NOT_APPLICABLE')]
    recs = {json.loads(l)['purpose']: json.loads(l) for l in open(f'{OUT}/CFL3_MIN_LEDGER.jsonl')}
    # frozen pool: r1+r2 re-extractions, four-part verified, full-tuple dedup
    pool, seen = [], set()
    for rep in (1, 2):
        for e in parse2(extract_any(recs[f'cfl3min|KANGMEI|C|r{rep}|e1_reext']['text']) or {}):
            if not four_part_check(e, contract)[0]:
                continue
            v = e.get('raw') or e.get('value')
            key = (str(e.get('field')), str(e.get('bucket')), str(e.get('predicate')),
                   str(e.get('doc')), str(e.get('page')),
                   Q1._norm(e.get('quote') or ''), Q1._norm(str(v)))
            if key in seen:
                continue
            seen.add(key)
            pool.append(e)
    # pre-check (a): pool size; (b): per-slot binding feasibility
    print(f"pre-check (a): dedup verified pool = {len(pool)} entries")
    binding = []
    for f in facts:
        nm = sum(1 for e in pool if P3.name_matches(e, f))
        val_ok = any((e.get('raw') or e.get('value')) not in (None, '')
                     and P3.value_equal_anyway(e.get('raw') or e.get('value'), f)[0] for e in pool)
        binding.append(dict(fact_id=f['fact_id'], name_match_rows=nm, has_correct_value_row=val_ok))
    n_bind = sum(1 for b in binding if b['name_match_rows'] > 0)
    n_val = sum(1 for b in binding if b['has_correct_value_row'])
    print(f"pre-check (b): slots with name-match rows: {n_bind}/14; slots with correct-value rows: {n_val}/14")
    for b in binding:
        print('   ', b)
    json.dump(dict(pool_size=len(pool), binding=binding),
              open(f'{OUT}/CFL3_MIN_B_PRECHECK.json', 'w'), ensure_ascii=False, indent=1)
    # A_old prompt: frozen chain on the same pool
    mf = {}
    for e in pool:
        k = str(e.get('field') or e.get('bucket') or '')
        if k and e.get('value') not in (None, ''):
            mf.setdefault(k, e.get('value'))
    ev_map = PP.match_evidence(mf, pool, contract)
    p_old = PP.render(contract, {}, mf, ev_map, with_evidence=True)
    # B_new prompt: same base, per-entry table (values explicit)
    facts_out = [dict(field=k, value=v) for k, v in mf.items()]
    rows = [f"{e.get('field') or e.get('bucket')} | value={e.get('raw') or e.get('value')} "
            f"| doc={e.get('doc')} | page={e.get('page')} | quote={e.get('quote', '')}" for e in pool]
    p_new = (P1.p_user(contract, {'facts': facts_out}, {}, [], 'E1') + '\n\n' + VALUE_FORM_RULES
             + '\n\n已核验证据表（逐条）：\n' + '\n'.join(rows) + '\n\n' + COPY_RULE)
    print(f"prompts: A_old={len(p_old)} chars, B_new={len(p_new)} chars, pool rows={len(rows)}")
    results = []
    for arm, prompt in (('A_old', p_old), ('B_new', p_new)):
        pass
    order = [('A_old', p_old, 1), ('B_new', p_new, 1), ('A_old', p_old, 2), ('B_new', p_new, 2)]
    for arm, prompt, rep in order:
        obj, text = real_call(P_SYS, prompt, f'cfl3minb|KANGMEI|{arm}|r{rep}|p')
        res = Q1.score_task(contract, obj) if obj else None
        row = dict(arm=arm, rep=rep)
        if res:
            rows_ = res['rows']
            tp = [x for x in rows_ if x['status'] == 'TP']
            answers = {a.get('fact_id'): a for a in (obj or {}).get('answers', [])
                       if isinstance(a, dict) and a.get('fact_id')}
            pool_keys = {(str(e.get('doc')), str(e.get('page'))) for e in pool}
            row.update(q=res['q'], n_tp=len(tp),
                       tp_facts=[x['fact_id'] for x in tp],
                       wrong_assert=sum(1 for x in rows_ if x['status'].startswith('VALUE')),
                       abstentions=sum(1 for x in rows_ if x['status'] == 'ABSENT'),
                       crit_tp=sum(1 for x in rows_ if x.get('critical') and x['status'] == 'TP'),
                       support_rate=res['evidence_support_rate'])
        else:
            row.update(q=None, parse_fail=True)
        results.append(row)
        print(f"{arm} r{rep}: Q={row.get('q')} TP={row.get('n_tp')} {row.get('tp_facts')} "
              f"abst={row.get('abstentions')} wrong={row.get('wrong_assert')}")
    json.dump(dict(batch='CFL3_MIN_B', caps=CAPS,
                   used=dict(calls=calls_used[0], yuan=round(yuan_used[0], 4),
                             tokens=tok_used[0], reserve_left=reserve[0]),
                   pool_size=len(pool), results=results),
              open(f'{OUT}/CFL3_MIN_B_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\nDONE: calls={calls_used[0]}/{CAPS['calls']} tokens={tok_used[0]}/{CAPS['tokens']} "
          f"¥{yuan_used[0]:.4f}/{CAPS['yuan']} reserve_left={reserve[0]}")


if __name__ == '__main__':
    main()
