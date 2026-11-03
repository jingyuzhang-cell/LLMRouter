"""QP1 dev runner: Baseline / E1 / E2 / E3 on 4 dev tasks x 2 reps.

Hard caps (operator-authorized dev run): 224 calls, 586,030 tokens, ¥0.648.
Resumable via purpose-keyed cache; checkpoint after each cell.
"""
import json, os, random, re, sys, time
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp1_prompts as P
import scorer_qp1 as Q
from real_provider_v22 import extract_any
from stage_d_v2_transport import Transport, Ledger

ROOT = '/root/research_outputs/static_pi/stage_d'
QP = f'{ROOT}/quality_phase_v1'
DEV = ['E06', 'MVR1', 'KANGMEI', 'GUOEN']
ARMS = ['Baseline', 'E1', 'E2', 'E3']
REPS = (1, 2)
SEED = 20261103
CAP_CALLS, CAP_TOKENS, CAP_YUAN = 224, 586_030, 0.648


def load_contract(ev):
    c = [t for t in json.load(open(f'{ROOT}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if t['event_key'] == ev][0]['contract']
    if not os.path.isabs(c):
        c = f'{ROOT}/v23a/{c}'
    return json.load(open(c))


def norm(x):
    import unicodedata
    t = unicodedata.normalize('NFKC', str(x if x is not None else ''))
    return re.sub(r'\s+', '', t)


def value_supported(value, quote):
    q = norm(quote)
    if not q:
        return False
    nums = re.findall(r'\d[\d,，.]*', str(value))
    if nums:
        return any(norm(n).replace(',', '') in q.replace(',', '').replace('，', '') for n in nums)
    core = norm(value).split('_')[-1]
    return bool(core and core[:12] in q)


def verify_code(contract, merged):
    facts = merged.get('facts', []) if isinstance(merged, dict) else []
    pages = contract['source_pages']
    ok, bad = [], []
    for f in facts:
        doc, page, quote = f.get('doc'), f.get('page'), f.get('quote', '')
        pg = (pages.get(str(doc)) or {}).get('pages', {}).get(str(page))
        good = bool(pg and norm(quote) and norm(quote) in norm(pg.get('text', '')) and
                    value_supported(f.get('value'), quote))
        (ok if good else bad).append(f)
    return ok, bad


def filter_checks(merged, v_out):
    facts = merged.get('facts', []) if isinstance(merged, dict) else []
    checks = v_out.get('checks', []) if isinstance(v_out, dict) else []
    bad = {norm(c.get('fact')) for c in checks if str(c.get('verdict', '')).upper() == 'UNSUPPORTED'}
    keep = [f for f in facts if norm(f.get('field') or f.get('value')) not in bad]
    return dict(facts=keep)


def run_cell(arm, ev, rep, contract, call):
    docs = sorted(contract['source_pages'].keys())
    half = (len(docs) + 1) // 2
    e0_docs, e1_docs = docs[:half], docs[half:] or docs[:1]
    e0 = extract_any(call('e0', P.E_SYS, P.e_user(contract, e0_docs, arm), P.MAXTOK['E']))
    e1 = extract_any(call('e1', P.E_SYS, P.e_user(contract, e1_docs, arm), P.MAXTOK['E']))
    t = extract_any(call('t', P.M_SYS, P.t_user(contract, e0), P.MAXTOK['t']))
    m = extract_any(call('m', P.M_SYS, P.m_user(contract, {'e0': e0, 'e1': e1}), P.MAXTOK['m']))
    r = extract_any(call('r', P.R_SYS, P.r_user(contract, m), P.MAXTOK['r']))
    if arm in ('Baseline', 'E1'):
        v = extract_any(call('v', P.V_SYS, P.v_user(contract, m, r), P.MAXTOK['v']))
        merged = filter_checks(m, v)
        verified = merged.get('facts', [])
    else:
        verified, rejected = verify_code(contract, m)
        merged = dict(facts=verified)
    p = extract_any(call('p', P.P_SYS, P.p_user(contract, merged, r, verified, arm), P.MAXTOK['p']))
    res = Q.score_task(contract, p)
    return dict(task=ev, arm=arm, rep=rep, n=res['n_facts'], q=res['q'],
                value=res['fact_value_correct_rate'], loc=res['evidence_localization_rate'],
                sup=res['evidence_support_rate'], unk=res['unknown_accuracy'],
                gate=res['critical_gate'], statuses=sorted({r['status'] for r in res['rows']}))


def main():
    ledger = Ledger(f'{QP}/QP1_LEDGER.jsonl')
    tr = Transport(ledger, cap_calls=CAP_CALLS, cap_tokens=CAP_TOKENS)
    results, status = [], 'COMPLETE'
    order = []
    for ev in DEV:
        for rep in REPS:
            block = [(ev, rep, a) for a in ARMS]
            random.Random(SEED).shuffle(block)
            order.extend(block)

    def call(node, system, user, max_tokens):
        if ledger.cost > CAP_YUAN:
            raise RuntimeError('cost cap')
        rec = tr.call('glm53flash', system, user, max_tokens,
                      purpose=f'qp1|{CURRENT["ev"]}|{CURRENT["arm"]}|r{CURRENT["rep"]}|{node}')
        return rec['text']

    CURRENT = {}
    for ev, rep, arm in order:
        CURRENT.update(ev=ev, arm=arm, rep=rep)
        contract = load_contract(ev)
        before = len(ledger.records)
        try:
            results.append(run_cell(arm, ev, rep, contract, call))
            print(f"  {ev:9s} {arm:9s} r{rep} calls+{len(ledger.records)-before:2d} "
                  f"total={len(ledger.records):3d} Q={results[-1]['q']:.3f} "
                  f"val={results[-1]['value']:.2f} loc={results[-1]['loc']:.2f} "
                  f"sup={results[-1]['sup']:.2f} gate={results[-1]['gate']}", flush=True)
        except Exception as e:
            results.append(dict(task=ev, arm=arm, rep=rep, error=f'{type(e).__name__}: {e}'[:160]))
            low = str(e).lower()
            status = 'ERROR_AUTH' if ('401' in low or '403' in low or 'unauthorized' in low) else (
                'INCOMPLETE' if 'cap' in low else 'ERROR')
            print(f"  {ev} {arm} r{rep} ERROR {e}", flush=True)
        json.dump(dict(status=status, used=dict(calls=len(ledger.records), tokens=ledger.tokens,
                                                yuan=round(ledger.cost, 4)), results=results),
                  open(f'{QP}/QP1_DEV_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{QP}/QP1_DEV_PROGRESS.json.tmp', f'{QP}/QP1_DEV_PROGRESS.json')
        if status != 'COMPLETE':
            break
    json.dump(dict(batch='QP1_DEV', status=status, seed=SEED, caps=dict(
        calls=CAP_CALLS, tokens=CAP_TOKENS, yuan=CAP_YUAN),
        used=dict(calls=len(ledger.records), tokens=ledger.tokens, yuan=round(ledger.cost, 4)),
        results=results), open(f'{QP}/QP1_DEV_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={len(ledger.records)}/{CAP_CALLS} tokens={ledger.tokens}/{CAP_TOKENS} "
          f"¥{ledger.cost:.3f}/{CAP_YUAN}")


if __name__ == '__main__':
    main()
