"""QP5-A v2 runner: pure evidence-provision contrast (authorized 24 SINK calls).

Both arms share cached upstream (QP4 D cells); only the SINK is re-called with
the P2 prompts from qp5a_pure_prep.render(). Block = (task, rep); B1/B2 order
randomized per block (seed 20261103). Caps: 30 calls / ¥0.60 (pre-charge guard).
Scoring: frozen QP1-final (scorer_qp1), strict.
"""
import json, os, random, sys, hashlib
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp4_factorial as F
import qp5a_pure_prep as PP
import qp1_prompts as P1
import scorer_qp1 as Q1
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'
SEED = 20261103
CAPS = dict(calls=30, tokens=10_000_000, yuan=0.60)
RESERVE = 0.05


def load_upstream():
    led = {}
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        led[(p[1], p[2], p[3], p[4])] = x
    return led


def build_pair(led, t, rep):
    contract = F.load_contract(t)
    e0 = extract_any(led[(t, 'D', f'r{rep}', 'e0')]['text'])
    e1 = extract_any(led[(t, 'D', f'r{rep}', 'e1')]['text'])
    m = extract_any(led[(t, 'D', f'r{rep}', 'm')]['text'])
    r = extract_any(led[(t, 'D', f'r{rep}', 'r')]['text'])
    import qp2_chain as CH
    import qp3_primitives as P3
    entries = P3.normalize_stage(e0) + P3.normalize_stage(e1)
    verified, _ = CH.verify_evidence(entries, contract)
    m_facts = {}
    for e in P3.normalize_stage(m):
        k = PP.fact_key(e)
        if k and e.get('value') not in (None, ''):
            m_facts.setdefault(k, e.get('value'))
    ev_map = PP.match_evidence(m_facts, verified, contract)
    b1 = PP.render(contract, r, m_facts, ev_map, with_evidence=False)
    b2 = PP.render(contract, r, m_facts, ev_map, with_evidence=True)
    return contract, b1, b2, ev_map


class Guard:
    def __init__(self, caps):
        from stage_d_v2_transport import Ledger
        self.ledger = Ledger(f'{QP}/QP5A_LEDGER.jsonl')
        self.index = dict(self.ledger.index)
        for path in (f'{QP}/QP1_LEDGER.jsonl', f'{QP}/QP2_LEDGER.jsonl', f'{QP}/QP4_LEDGER.jsonl'):
            if os.path.exists(path):
                for line in open(path):
                    rec = json.loads(line)
                    self.index.setdefault((rec['purpose'], rec['prompt_sha256']), rec)
        self.caps = caps

    def call(self, alias, system, user, max_tokens, purpose, mean_cost):
        from stage_d_v2_transport import build_request
        body = build_request(alias, system, user, max_tokens)
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hit = self.index.get((purpose, sha))
        if hit is not None:
            return hit
        if len(self.ledger.records) + 1 > self.caps['calls']:
            raise RuntimeError('calls cap')
        if self.ledger.cost + mean_cost > self.caps['yuan'] * (1 - RESERVE):
            raise RuntimeError('cost cap')
        return self._real(alias, body, purpose, sha)

    def _real(self, alias, body, purpose, sha):
        import urllib.request, time
        from stage_d_v2_transport import glm_key, MODEL_CFG
        req = urllib.request.Request(MODEL_CFG[alias]['url'],
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        req.add_header('authorization', 'Bearer ' + glm_key())
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=180) as resp:
            d = json.loads(resp.read().decode())
        ch = d['choices'][0]
        u = d.get('usage', {})
        c = ch.get('message', {}).get('content', '')
        text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
        tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
        rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias=alias, model=MODEL_CFG[alias]['model'],
                   purpose=purpose, max_tokens=body.get('max_tokens'), prompt_sha256=sha,
                   usage=dict(input_tokens=tin, output_tokens=tout),
                   accounting_yuan=round(tin * 0.8e-6 + tout * 2.8e-6, 8),
                   latency_s=round(time.monotonic() - t0, 3),
                   stop_reason={'stop': 'end_turn', 'length': 'max_tokens'}.get(
                       ch.get('finish_reason'), ch.get('finish_reason')),
                   text=text)
        self.ledger.add(rec)
        return rec


def score_with_subgroups(contract, sink, ev_map):
    res = Q1.score_task(contract, sink)
    ans = {}
    for a in (sink or {}).get('answers', []) if isinstance(sink, dict) else []:
        if isinstance(a, dict) and a.get('fact_id'):
            ans.setdefault(a['fact_id'], a)
    ev_keys = set(ev_map.keys())

    def sub(rows_sel):
        return round(sum(1 for r in rows_sel if r['status'] == 'TP') / len(rows_sel), 4) if rows_sel else None

    gold_keys = {f.get('bucket') or f['fact_id']: f['fact_id'] for f in contract['required_facts']}
    rows_ev = [r for r in res['rows'] if gold_keys.get(r['fact_id'], r['fact_id']) and
               (contract_map(r['fact_id'], contract) in ev_keys)]
    rows_nonev = [r for r in res['rows'] if contract_map(r['fact_id'], contract) not in ev_keys]
    wrong_assert = sum(1 for r in res['rows'] if r['status'] in ('VALUE_WRONG',)
                       or r['status'].startswith('VALUE') or r['status'] in ('UNSUPPORTED',))
    wrong_cit = sum(1 for r in res['rows'] if r['status'].startswith('C_LOC') or r['status'] == 'UNSUPPORTED')
    abst = sum(1 for r in res['rows'] if r['status'] == 'ABSENT')
    crit = [r for r in res['rows'] if r.get('critical')]
    return dict(q=res['q'], n=res['n_facts'], gate=res['critical_gate'],
                q_evidence=sub(rows_ev), q_noevidence=sub(rows_nonev),
                wrong_assertions=wrong_assert, wrong_citations=wrong_cit,
                abstentions=abst, crit_tp=sum(1 for r in crit if r['status'] == 'TP'),
                crit_n=len(crit), rows=res['rows'])


def contract_map(fid, contract):
    f = next((x for x in contract['required_facts'] if x['fact_id'] == fid), {})
    return f.get('bucket') or fid


def main(mock=False):
    led = load_upstream()
    order = []
    for t in F.TASKS:
        for rep in (1, 2):
            block = [('B1', 1), ('B2', 2)]
            random.Random(SEED + hash(t) % 100).shuffle(block)
            order.extend((t, rep, arm) for arm, _ in block)
    results = []
    if mock:
        for t, rep, arm in order:
            contract, b1, b2, ev = build_pair(led, t, rep)
            # mock sink: gold answers; B2 attaches table evidence
            facts = contract['required_facts']
            ans = [dict(fact_id=f['fact_id'], value=f['value']) for f in facts]
            if arm == 'B2':
                for a in ans:
                    k = contract_map(a['fact_id'], contract)
                    if k in ev:
                        a.update(doc=ev[k].get('doc'), page=ev[k].get('page'),
                                 quote=ev[k].get('quote', ''))
            sink = dict(answers=ans, abstentions=[], complete=True)
            results.append(dict(task=t, rep=rep, arm=arm,
                                **{k: v for k, v in score_with_subgroups(contract, sink, ev).items()
                                   if k != 'rows'}))
        json.dump(results, open(f'{QP}/QP5A_MOCK.json', 'w'), ensure_ascii=False, indent=1)
        import statistics as st
        for arm in ('B1', 'B2'):
            g = [r for r in results if r['arm'] == arm]
            print(f"mock {arm}: Q={st.mean(x['q'] for x in g):.3f}")
        return

    g = Guard(CAPS)
    mean_cost = 0.006
    status = 'COMPLETE'
    for t, rep, arm in order:
        try:
            contract, b1, b2, ev = build_pair(led, t, rep)
            user = b1 if arm == 'B1' else b2
            rec = g.call('glm53flash', P1.P_SYS, user, P1.MAXTOK['p'],
                         purpose=f'qp5a|{t}|{arm}|r{rep}|p', mean_cost=mean_cost)
            sink = extract_any(rec['text'])
            sc = score_with_subgroups(contract, sink, ev)
            results.append(dict(task=t, rep=rep, arm=arm, table_entries=len(ev),
                                **{k: v for k, v in sc.items() if k != 'rows'},
                                rows=sc['rows']))
            print(f"  {t:9s} {arm} r{rep} tbl={len(ev):2d} Q={sc['q']:.3f} "
                  f"evQ={sc['q_evidence']} noevQ={sc['q_noevidence']} gate={sc['gate']}", flush=True)
        except Exception as e:
            results.append(dict(task=t, rep=rep, arm=arm, error=f'{type(e).__name__}: {e}'[:160]))
            status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
            print(f"  {t} {arm} r{rep} ERROR {e}", flush=True)
            break
        json.dump(dict(status=status, used=dict(calls=len(g.ledger.records),
                                                yuan=round(g.ledger.cost, 4)), results=results),
                  open(f'{QP}/QP5A_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{QP}/QP5A_PROGRESS.json.tmp', f'{QP}/QP5A_PROGRESS.json')
    json.dump(dict(batch='QP5A_V2', status=status, caps=CAPS,
                   used=dict(calls=len(g.ledger.records), tokens=g.ledger.tokens,
                             yuan=round(g.ledger.cost, 4)), results=results),
              open(f'{QP}/QP5A_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={len(g.ledger.records)}/{CAPS['calls']} ¥{g.ledger.cost:.4f}/{CAPS['yuan']}")


if __name__ == '__main__':
    main(mock='--mock' in sys.argv)
