"""CFL-2 runner (frozen protocol, CFL2_PREREGISTRATION.md v1.0).

A arm  = frozen QP9 A_static first-pass outputs (0 calls, integrity-checked).
B arm  = S0-trigger (ac<0.60) plain re-sample, DS, same prompt.
C arm  = S2-trigger (unsupported/answered>0.50, answered>=3) recovery with the
         frozen grounding-feedback template appended, DS.
Independent ledger CFL2_LEDGER.jsonl. Recovery calls are ALWAYS fresh samples
(no prompt cache). Caps: 40 calls / 0.20 yuan / 60K tokens.
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
from qp1_prompts import P_SYS, MAXTOK
from stage_d_v2_transport import build_request, ds_key, MODEL_CFG

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/CFL2_LEDGER.jsonl'
TASKS = ['MVR1', 'KANGMEI', 'ZEDA', 'ZIJING']
CAPS = dict(calls=40, tokens=60_000, yuan=0.20)
S0_THRESH = 0.60
S2_RATE, S2_MIN = 0.50, 3
REASON_ZH = {'no_quote': '引用为空', 'value_not_in_quote': '值未见于引用',
             'page_missing': '引用页不存在', 'quote_not_in_page': '引文不在该页'}

calls_used = [0]; yuan_used = [0.0]; tok_used = [0]


def load_contract(t):
    p = [x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if x['event_key'] == t][0]['contract']
    if not os.path.isabs(p): p = f'{SD}/v23a/{p}'
    return json.load(open(p))


def real_call_fresh(system, user, purpose):
    """Fresh DS sample; one re-attempt on transport/parse failure (per prereg)."""
    for attempt in ('', '_attempt2'):
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
        except Exception as e:
            if attempt == '':
                print(f'  [transport fail {purpose}, retry once] {type(e).__name__}')
                continue
            raise
        ch = d['choices'][0]; u = d.get('usage', {})
        c = ch.get('message', {}).get('content', '')
        text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
        tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
        yuan = round(tin * 0.8e-6 + tout * 2.8e-6, 8)
        lat = round(time.monotonic() - t0, 3)
        rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias='deepseek',
                   purpose=purpose + attempt, prompt_sha256=sha,
                   usage=dict(input_tokens=tin, output_tokens=tout),
                   accounting_yuan=yuan, latency_s=lat, text=text)
        with open(LEDGER, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        calls_used[0] += 1; yuan_used[0] += yuan; tok_used[0] += tin + tout
        if tok_used[0] >= CAPS['tokens']:
            raise RuntimeError('TOKEN CAP')
        obj = extract_any(text)
        if obj is None and attempt == '':
            print(f'  [parse fail {purpose}, resample once]')
            continue
        return obj, yuan, lat, text
    raise RuntimeError('unreachable')


def s2_fire_sink(ans, contract):
    q = ans.get('quote') or ''; v = ans.get('value')
    if not q: return True, 'no_quote'
    if not Q1.value_in_quote(v, q): return True, 'value_not_in_quote'
    doc = contract.get('source_pages', {}).get(str(ans.get('doc')))
    pg = (doc or {}).get('pages', {}).get(str(ans.get('page')))
    if pg is None: return True, 'page_missing'
    if Q1._norm(q) not in Q1._norm(pg.get('text', '')): return True, 'quote_not_in_page'
    return False, None


def sink_prompt_and_entries(task, contract):
    """Deterministic QP9-identical SINK prompt from frozen E cache."""
    led = {}
    for path, pref in ((f'{SD}/qp8/QP8R_STAGE1_LEDGER.jsonl', 'qp8r'),
                       (f'{SD}/qp9/QP9_LEDGER.jsonl', 'qp9')):
        for l in open(path):
            x = json.loads(l)
            led[x['purpose']] = x
    ents = []
    for node in ('e0', 'e1'):
        r = led.get(f'qp8r|{task}|DS|r1|{node}') or led.get(f'qp9|{task}|E|deepseek|{node}')
        ents += parse2(extract_any(r['text']) or {})
    mf = {}
    for e in ents:
        k = str(e.get('field') or e.get('bucket') or '')
        if k and e.get('value') not in (None, ''):
            mf.setdefault(k, e.get('value'))
    ver, _ = CH.verify_evidence(ents, contract)
    prompt = PP.render(contract, {}, mf, PP.match_evidence(mf, ver, contract), with_evidence=True)
    return prompt


def feedback_block(contract, sink_obj):
    lines = []
    for a in (sink_obj or {}).get('answers', []):
        if isinstance(a, dict) and a.get('fact_id') and a.get('value') not in (None, ''):
            fire, why = s2_fire_sink(a, contract)
            if fire:
                lines.append(f"{a['fact_id']} — {REASON_ZH[why]}")
    body = '\n'.join(lines)
    return ('【自检反馈】上一轮回答存在证据支持异常：以下条目的值未能在其引用的原文中得到验证：\n'
            f'{body}\n'
            '请重新输出完整 JSON 答案：值必须与所引用原文一致；doc/page/quote 必须逐字取自'
            '上方证据表中的原始条目；确实无法从证据支持的条目请移入 abstentions，不要编造。')


def score(contract, sink_obj):
    res = Q1.score_task(contract, sink_obj) if sink_obj else None
    if res is None:
        return dict(q=0.0, crit_tp=0, wrong_assert=len(contract['required_facts']),
                    abstentions=len(contract['required_facts']), support_rate=0.0)
    rows = res['rows']
    return dict(q=res['q'],
                crit_tp=sum(1 for x in rows if x.get('critical') and x['status'] == 'TP'),
                wrong_assert=sum(1 for x in rows if x['status'].startswith('VALUE')),
                abstentions=sum(1 for x in rows if x['status'] == 'ABSENT'),
                support_rate=res['evidence_support_rate'])


def main():
    qp9 = {}
    for l in open(f'{SD}/qp9/QP9_LEDGER.jsonl'):
        x = json.loads(l); qp9[x['purpose']] = x
    results = []
    for task in TASKS:
        contract = load_contract(task)
        prompt = sink_prompt_and_entries(task, contract)
        # integrity: prompt sha must equal QP9 A_static p sha
        body = build_request('deepseek', P_SYS, prompt, MAXTOK['p'])
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        assert sha == qp9[f'qp9|{task}|A_static|r1|p']['prompt_sha256'], f'PROMPT DRIFT {task}'
        for rep in (1, 2):
            first_text = qp9[f'qp9|{task}|A_static|r{rep}|p']['text']
            first_obj = extract_any(first_text)
            facts = [f for f in contract['required_facts']
                     if f.get('status') not in ('EXCLUDED', 'NOT_APPLICABLE')]
            answers = [a for a in (first_obj or {}).get('answers', [])
                       if isinstance(a, dict) and a.get('fact_id') and a.get('value') not in (None, '')]
            ac = len({a['fact_id'] for a in answers}) / max(1, len(facts))
            s0_fire = ac < S0_THRESH
            fires = [s2_fire_sink(a, contract) for a in answers]
            rate = sum(1 for f_, _ in fires if f_) / len(answers) if answers else 0.0
            s2_fire = rate > S2_RATE and len(answers) >= S2_MIN
            cells = {}
            # A: frozen
            cells['A_static'] = score(contract, first_obj) | dict(recovery=False, new_calls=0)
            # B: S0 trigger -> plain resample
            if s0_fire:
                obj, y, lat, txt = real_call_fresh(P_SYS, prompt, f'cfl2|{task}|B_S0|r{rep}|p_retry')
                cells['B_S0'] = score(contract, obj) | dict(recovery=True, new_calls=1)
            else:
                cells['B_S0'] = cells['A_static'] | dict(recovery=False, new_calls=0)
            # C: S2 trigger -> grounding feedback recovery
            if s2_fire:
                fb = feedback_block(contract, first_obj)
                obj, y, lat, txt = real_call_fresh(P_SYS, prompt + '\n\n' + fb,
                                                   f'cfl2|{task}|C_S2|r{rep}|p_recover')
                cells['C_S2'] = score(contract, obj) | dict(recovery=True, new_calls=1)
            else:
                cells['C_S2'] = cells['A_static'] | dict(recovery=False, new_calls=0)
            for arm, c in cells.items():
                results.append(dict(task=task, rep=rep, arm=arm, ac=round(ac, 3),
                                    s2_rate=round(rate, 3), s0_fire=s0_fire, s2_fire=s2_fire, **c))
            print(f"{task} r{rep}: ac={ac:.2f} S0={s0_fire} S2rate={rate:.2f} S2={s2_fire} | "
                  + ' '.join(f"{a}:Q={c['q']:.3f}" for a, c in cells.items()))
    json.dump(dict(batch='CFL2', caps=CAPS,
                   used=dict(calls=calls_used[0], yuan=round(yuan_used[0], 4),
                             tokens=tok_used[0]),
                   results=results), open(f'{OUT}/CFL2_RESULTS.json', 'w'),
              ensure_ascii=False, indent=1)
    print(f"\nCOMPLETE: calls={calls_used[0]}/{CAPS['calls']} ¥{yuan_used[0]:.4f}/{CAPS['yuan']} "
          f"tokens={tok_used[0]}/{CAPS['tokens']}")


if __name__ == '__main__':
    main()
