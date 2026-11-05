"""CFL-3-MIN runner (CFL3_MIN_PREREGISTRATION.md v1.0 + Variant A ruling).

A arm = frozen QP9 A_static KANGMEI (0 calls). B arm = frozen CFL-2 C_S2 (0 calls).
C arm (new): e1 directed re-extraction -> V re-verify (0 calls, gate >=1)
-> conditional SINK re-answer -> Gold terminal scoring + repaired-entry attribution.
Caps: 8 calls / 55,000 tokens / 0.10 yuan. Reserve: 2 calls, transport/parse
failure ONLY (no quality-conditioned retries). Independent ledger.
"""
import json, os, sys, time, hashlib, urllib.request

SD = '/root/research_outputs/static_pi/stage_d'
sys.path.insert(0, f'{SD}/quality_phase_v1')
sys.path.insert(0, f'{SD}/qp3')
sys.path.insert(0, f'{SD}/v2')
sys.path.insert(0, SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import qp2_chain as CH
import qp5a_pure_prep as PP
import scorer_qp1 as Q1
from qp1_prompts import E_SYS, e_user, P_SYS, MAXTOK
from stage_d_v2_transport import build_request, ds_key, MODEL_CFG

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/CFL3_MIN_LEDGER.jsonl'
CAPS = dict(calls=8, tokens=55_000, yuan=0.10)
ADDENDUM = ('\n【重抽要求（本次追加）】上一轮抽取存在"值与引文错配"：部分事实值并未出现在其引用的原文中。'
            '本次抽取必须遵守：每条事实的 value 必须能在该条目给出的 quote 中直接找到（数字、日期、编号允许'
            '千分位/单位换算，但数值本身必须出现在 quote 内）；doc 与 page 必须是 quote 的真实出处；'
            '无法给出含该值的引文时，该条目留空，不要凭记忆填值。')

calls_used = [0]; yuan_used = [0.0]; tok_used = [0]; reserve = [2]


def load_contract():
    p = [x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if x['event_key'] == 'KANGMEI'][0]['contract']
    if not os.path.isabs(p): p = f'{SD}/v23a/{p}'
    return json.load(open(p))


def real_call(system, user, purpose, mt):
    """Fresh DS call; reserve retry ONLY on transport failure or parse failure."""
    for attempt in (1, 2):
        if attempt == 2:
            if reserve[0] < 1:
                raise RuntimeError('NO RESERVE LEFT')
            reserve[0] -= 1
            print(f'  [reserve consumed: {purpose}]')
        if calls_used[0] >= CAPS['calls']:
            raise RuntimeError('CALLS CAP')
        if yuan_used[0] + 0.015 > CAPS['yuan'] * 0.95:
            raise RuntimeError('YUAN CAP')
        body = build_request('deepseek', system, user, mt)
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
        lat = round(time.monotonic() - t0, 3)
        calls_used[0] += 1; yuan_used[0] += yuan; tok_used[0] += tin + tout
        rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias='deepseek', purpose=purpose,
                   prompt_sha256=sha, usage=dict(input_tokens=tin, output_tokens=tout),
                   accounting_yuan=yuan, latency_s=lat, text=text)
        with open(LEDGER, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        if tok_used[0] >= CAPS['tokens']:
            raise RuntimeError('TOKEN CAP')
        obj = extract_any(text)
        if obj is None and attempt == 1:
            continue  # parse failure -> reserve retry
        return obj, text
    raise RuntimeError('unreachable')


def four_part_check(e, contract):
    doc = contract['source_pages'].get(str(e.get('doc')))
    pg = (doc or {}).get('pages', {}).get(str(e.get('page')))
    if doc is None: return False, 'doc'
    if pg is None: return False, 'page'
    q = e.get('quote') or ''
    if not q or Q1._norm(q) not in Q1._norm(pg.get('text', '')): return False, 'quote'
    if not Q1.value_in_quote(e.get('raw') or e.get('value'), q): return False, 'grounded'
    return True, None


def main():
    contract = load_contract()
    led8 = {}
    for l in open(f'{SD}/qp8/QP8R_STAGE1_LEDGER.jsonl'):
        x = json.loads(l); led8[x['purpose']] = x
    e0_text = led8['qp8r|KANGMEI|DS|r1|e0']['text']  # frozen e0 (out of scope this run)
    e1_docs = sorted(contract['source_pages'].keys())[2:] or ['2020-05-15']
    e1_docs = ['2020-05-15']  # frozen scope per prereg §2

    results = []
    for rep in (1, 2):
        row = dict(rep=rep)
        # Step 1: e1 directed re-extraction
        user_e1 = e_user(contract, e1_docs, 'E1') + ADDENDUM
        e1_obj, e1_text = real_call(E_SYS, user_e1, f'cfl3min|KANGMEI|C|r{rep}|e1_reext', 2000)
        new_e1_entries = parse2(e1_obj or {})
        # Step 2: V re-verify (zero calls)
        checks = [four_part_check(e, contract) for e in new_e1_entries]
        ok_entries = [e for (ok, _), e in zip(checks, new_e1_entries) if ok]
        ver_all, _ = CH.verify_evidence(parse2(extract_any(e0_text) or {}) + new_e1_entries, contract)
        row.update(n_new_entries=len(new_e1_entries),
                   n_four_part_ok=len(ok_entries),
                   n_verify_evidence=len(ver_all),
                   fail_reasons={r: sum(1 for _, rr in checks if rr == r)
                                 for r in ('doc', 'page', 'quote', 'grounded')})
        print(f"r{rep}: e1 re-ext entries={len(new_e1_entries)} four-part-ok={len(ok_entries)} "
              f"verify_evidence={len(ver_all)} fails={row['fail_reasons']}")
        if len(ok_entries) < 1:
            row.update(stage='STOPPED_AT_V', sink_called=False)
            results.append(row); continue
        # Step 3: SINK re-answer with rebuilt table (frozen chain)
        all_entries = parse2(extract_any(e0_text) or {}) + new_e1_entries
        mf = {}
        for e in all_entries:
            k = str(e.get('field') or e.get('bucket') or '')
            if k and e.get('value') not in (None, ''):
                mf.setdefault(k, e.get('value'))
        ver, _ = CH.verify_evidence(all_entries, contract)
        prompt = PP.render(contract, {}, mf, PP.match_evidence(mf, ver, contract), with_evidence=True)
        sink_obj, sink_text = real_call(P_SYS, prompt, f'cfl3min|KANGMEI|C|r{rep}|p_reanswer', MAXTOK['p'])
        # Step 4: Gold terminal scoring + repaired-entry attribution
        res = Q1.score_task(contract, sink_obj) if sink_obj else None
        if res:
            rows = res['rows']
            tp_rows = [x for x in rows if x['status'] == 'TP']
            answers = {a.get('fact_id'): a for a in (sink_obj or {}).get('answers', [])
                       if isinstance(a, dict) and a.get('fact_id')}
            new_keys = {(str(e.get('doc')), str(e.get('page')), Q1._norm(e.get('quote') or ''))
                        for e in ok_entries}
            def from_new(fid):
                a = answers.get(fid) or {}
                return (str(a.get('doc')), str(a.get('page')), Q1._norm(a.get('quote') or '')) in new_keys \
                    or any(str(a.get('doc')) == d and str(a.get('page')) == p and Q1._norm(a.get('quote') or '')
                           and Q1._norm(a.get('quote') or '') in qn
                           for d, p, qn in ((d, p, q) for d, p, q in new_keys))
            repaired_tp = [x['fact_id'] for x in tp_rows if from_new(x['fact_id'])]
            row.update(stage='SCORED', sink_called=True, q=res['q'],
                       n_tp=len(tp_rows), crit_tp=sum(1 for x in rows if x.get('critical') and x['status'] == 'TP'),
                       repaired_tp=repaired_tp,
                       wrong_assert=sum(1 for x in rows if x['status'].startswith('VALUE')),
                       abstentions=sum(1 for x in rows if x['status'] == 'ABSENT'),
                       support_rate=res['evidence_support_rate'])
        else:
            row.update(stage='SINK_UNPARSEABLE', sink_called=True)
        results.append(row)
        print(f"r{rep}: Q={row.get('q')} TP={row.get('n_tp')} repaired={row.get('repaired_tp')} "
              f"abst={row.get('abstentions')} wrong={row.get('wrong_assert')}")
    json.dump(dict(batch='CFL3_MIN', variant='A', caps=CAPS,
                   used=dict(calls=calls_used[0], yuan=round(yuan_used[0], 4), tokens=tok_used[0],
                             reserve_left=reserve[0]),
                   results=results), open(f'{OUT}/CFL3_MIN_RESULTS.json', 'w'),
              ensure_ascii=False, indent=1)
    print(f"\nDONE: calls={calls_used[0]}/{CAPS['calls']} tokens={tok_used[0]}/{CAPS['tokens']} "
          f"¥{yuan_used[0]:.4f}/{CAPS['yuan']} reserve_left={reserve[0]}")


if __name__ == '__main__':
    main()
