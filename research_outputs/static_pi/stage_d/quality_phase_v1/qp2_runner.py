"""QP2 four-arm runner (offline-testable; real mode requires authorization).

Arms A/B/C/D per qp2_prompts.arm_factor. Evidence relay (B/C/D): the verified
table is built in CODE from E outputs, checked against pages, and passed to
SINK with a verbatim-reuse mandate; check_reuse() audits the result.

Budget guard (fixes the round-1 0.8% overrun): every call is PRE-CHARGED with
the task's measured mean cost; the run stops before the cap can be crossed.
Arm A reuses round-1 purpose keys so completed cells are pure cache hits.
"""
import json, os, random, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp1_prompts as P1
import qp2_prompts as P2
import qp2_chain as CH
import qp2_scorer as SC
from real_provider_v22 import extract_any
from stage_d_v2_transport import Transport, Ledger

ROOT = '/root/research_outputs/static_pi/stage_d'
QP = f'{ROOT}/quality_phase_v1'
TASKS = ['E06', 'MVR1', 'KANGMEI', 'GUOEN']
ARMS = ['A', 'B', 'C', 'D']
REPS = (1, 2)
SEED = 20261103
RESERVE = 0.05


def load_contract(ev):
    c = [t for t in json.load(open(f'{ROOT}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if t['event_key'] == ev][0]['contract']
    if not os.path.isabs(c):
        c = f'{ROOT}/v23a/{c}'
    return json.load(open(c))


def purpose_for(ev, arm, rep, node):
    if arm == 'A':
        return f'qp1|{ev}|Baseline|r{rep}|{node}'     # round-1 cache keys
    return f'qp2|{ev}|{arm}|r{rep}|{node}'


def run_cell(arm, ev, rep, contract, call):
    docs = sorted(contract['source_pages'].keys())
    half = (len(docs) + 1) // 2
    e0_docs, e1_docs = docs[:half], docs[half:] or docs[:1]
    f = P2.arm_factor(arm)

    e0 = extract_any(call('e0', P2.e_system(arm), P2.e_user(contract, e0_docs, arm), P2.MAXTOK['E']))
    e1 = extract_any(call('e1', P2.e_system(arm), P2.e_user(contract, e1_docs, arm), P2.MAXTOK['E']))
    t = extract_any(call('t', P1.M_SYS, P1.t_user(contract, e0), P2.MAXTOK['t']))
    m = extract_any(call('m', P1.M_SYS, P1.m_user(contract, {'e0': e0, 'e1': e1}), P2.MAXTOK['m']))
    r = extract_any(call('r', P1.R_SYS, P1.r_user(contract, m), P2.MAXTOK['r']))

    if arm == 'A':
        v = extract_any(call('v', P1.V_SYS, P1.v_user(contract, m, r), P2.MAXTOK['v']))
        merged = {'facts': [x for x in (m.get('facts') or []) if isinstance(x, dict)]}
        verified = merged['facts']
        reuse = None
    else:
        table = CH.build_evidence_table({'e0': e0, 'e1': e1})
        verified, rejected = CH.verify_evidence(table, contract)
        merged = {'facts': [dict(x) for x in verified]}
        verified = [dict(x) for x in verified]

    p = extract_any(call('p', P2.sink_system(arm),
                         P2.sink_user(contract, merged, r, verified, arm), P2.MAXTOK['p']))
    res = SC.score_task(contract, p)
    reuse = CH.check_reuse(p, verified) if arm != 'A' else reuse
    return dict(task=ev, arm=arm, rep=rep, n=res['n_facts'], q=res['q'],
                value=res['fact_value_correct_rate'], tol=res['tolerant_value_matches'],
                loc=res['evidence_localization_rate'], sup=res['evidence_support_rate'],
                unk=res['unknown_accuracy'], gate=res['critical_gate'],
                reuse_violations=None if reuse is None else reuse['n_violations'],
                reuse_rate=None if reuse is None else 1 - (reuse['violation_rate'] or 0),
                n_verified_evidence=len(verified) if arm != 'A' else None)


class GuardedTransport:
    """Cache over round-1 + round-2 ledgers; pre-charge cost guard; writes to QP2 only."""

    def __init__(self, caps, mean_call_cost):
        self.ledger = Ledger(f'{QP}/QP2_LEDGER.jsonl')
        self.index = dict(self.ledger.index)
        for line in open(f'{QP}/QP1_LEDGER.jsonl'):
            rec = json.loads(line)
            self.index.setdefault((rec['purpose'], rec['prompt_sha256']), rec)
        self.caps = caps
        self.mean = mean_call_cost
        self.stopped = None

    def call(self, alias, system, user, max_tokens, purpose):
        from stage_d_v2_transport import build_request
        body = build_request(alias, system, user, max_tokens)
        sha = __import__('hashlib').sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hit = self.index.get((purpose, sha))
        if hit is not None:
            return hit
        projected = self.ledger.cost + self.mean
        if len(self.ledger.records) + 1 > self.caps['calls']:
            self.stopped = 'calls cap'; raise RuntimeError('calls cap')
        if self.ledger.tokens > self.caps['tokens']:
            self.stopped = 'token cap'; raise RuntimeError('token cap')
        if projected > self.caps['yuan'] * (1 - RESERVE):
            self.stopped = 'cost cap (pre-charge)'
            raise RuntimeError('cost cap')
        rec = self._real_call(alias, body, purpose, sha)
        self.index[(purpose, sha)] = rec
        return rec

    def _real_call(self, alias, body, purpose, sha):
        import urllib.request, time
        from stage_d_v2_transport import glm_key, MODEL_CFG
        req = urllib.request.Request(MODEL_CFG[alias]['url'],
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        req.add_header('authorization', 'Bearer ' + glm_key())
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=180) as resp:
            d = json.loads(resp.read().decode())
        ch = d['choices'][0]; u = d.get('usage', {})
        c = ch.get('message', {}).get('content', '')
        text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
        tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
        rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias=alias, model=MODEL_CFG[alias]['model'],
                   thinking_mode=MODEL_CFG[alias]['thinking'], reasoning_effort=MODEL_CFG[alias]['effort'],
                   purpose=purpose, max_tokens=max_tokens, prompt_sha256=sha,
                   prompt_chars=len(system) + len(user), response_chars=len(text),
                   usage=dict(input_tokens=tin, output_tokens=tout),
                   accounting_yuan=round(tin * 0.8e-6 + tout * 2.8e-6, 8),
                   latency_s=round(time.monotonic() - t0, 3),
                   stop_reason={'stop': 'end_turn', 'length': 'max_tokens'}.get(
                       ch.get('finish_reason'), ch.get('finish_reason')),
                   text=text)
        self.ledger.add(rec)
        return rec


def build_order():
    cells = []
    for ev in TASKS:
        for rep in REPS:
            block = [(ev, rep, a) for a in ARMS]
            random.Random(SEED + hash(ev) % 100).shuffle(block)
            cells.extend(block)
    return cells


def main(mock=False):
    if mock:
        from qp2_dryrun import mock_provider
        results = []
        for ev, rep, arm in build_order():
            contract = load_contract(ev)
            results.append(run_cell(arm, ev, rep, contract, mock_provider(contract, arm)))
        return results

    from qp2_dryrun import measured_mean_call_cost
    caps = json.load(open(f'{QP}/QP2_BUDGET.json'))['hard_stop']
    tr = GuardedTransport(caps, measured_mean_call_cost())
    results, status = [], 'COMPLETE'
    for ev, rep, arm in build_order():
        contract = load_contract(ev)

        def call(node, system, user, mt, _ev=ev, _arm=arm, _rep=rep):
            return tr.call('glm53flash', system, user, mt,
                           purpose=purpose_for(_ev, _arm, _rep, node))
        before = len(tr.ledger.records)
        try:
            results.append(run_cell(arm, ev, rep, contract, call))
            r = results[-1]
            print(f"  {ev:9s} {arm} r{rep} +{len(tr.ledger.records)-before:2d} "
                  f"Q={r['q']:.3f} loc={r['loc']:.2f} sup={r['sup']:.2f} "
                  f"reuse={r['reuse_rate']}", flush=True)
        except Exception as e:
            results.append(dict(task=ev, arm=arm, rep=rep, error=f'{type(e).__name__}: {e}'[:160]))
            status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
            print(f"  {ev} {arm} r{rep} ERROR {e}", flush=True)
            break
        json.dump(dict(status=status, used=dict(calls=len(tr.ledger.records),
                                                tokens=tr.ledger.tokens,
                                                yuan=round(tr.ledger.cost, 4)), results=results),
                  open(f'{QP}/QP2_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{QP}/QP2_PROGRESS.json.tmp', f'{QP}/QP2_PROGRESS.json')
    json.dump(dict(batch='QP2_DEV_R2', status=status, caps=caps,
                   used=dict(calls=len(tr.ledger.records), tokens=tr.ledger.tokens,
                             yuan=round(tr.ledger.cost, 4)), results=results),
              open(f'{QP}/QP2_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={len(tr.ledger.records)}/{caps['calls']} "
          f"tokens={tr.ledger.tokens}/{caps['tokens']} ¥{tr.ledger.cost:.4f}/{caps['yuan']}")


if __name__ == '__main__':
    main(mock='--mock' in sys.argv)
