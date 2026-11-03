"""QP4: 2x2 factorial (H1 evidence retention x H2 value-expression specialization).

Authorized: 288 real calls (6 tasks x 2 reps x 4 cells x 6 calls), hard stops
295 calls / 1.45M tokens / ¥1.70 (pre-charge guard, 5% reserve).

Cells (single-factor-per-arm, preregistered):
  A = H1 OFF, H2 OFF   (round-1 baseline pipeline, 6 calls)
  B = H1 ON,  H2 OFF   (evidence contract + code-verified table + SINK reuse mandate)
  C = H1 OFF, H2 ON    (amount/text output contract at E and SINK; no table relay)
  D = H1 ON,  H2 ON
Strict terminal abstention is NOT a factor. Scoring: frozen QP1-final (strict).
"""
import json, os, random, sys, hashlib
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp1_prompts as P1
import qp2_amount as AM
import qp2_chain as CH
import scorer_qp1 as Q1
from real_provider_v22 import extract_any

ROOT = '/root/research_outputs/static_pi/stage_d'
QP = f'{ROOT}/quality_phase_v1'
TASKS = ['E06', 'MVR1', 'KANGMEI', 'GUOEN', 'ZIJING', 'ZEDA']
CELLS = ['A', 'B', 'C', 'D']
REPS = (1, 2)
SEED = 20261103
CAPS = dict(calls=295, tokens=1_450_000, yuan=1.70)
RESERVE = 0.05

FACTOR = {'A': dict(h1=False, h2=False), 'B': dict(h1=True, h2=False),
          'C': dict(h1=False, h2=True), 'D': dict(h1=True, h2=True)}

VALUE_FORM_RULES = (
    '数值与文本表达规则（强制执行）：\n'
    '1) value 一律不得添加"亏损：""盈利："等前缀，不得添加"（即…）""（约…）"等括注解释；\n'
    '2) 负数必须用负号表示，不得只用"亏损"字样代替符号；\n'
    '3) 槽位 value_kind 为 number/amount 的：value 只写带符号的纯数字（如 -12500、-639.38、24500），'
    '不带单位、不带千分位逗号；\n'
    '4) 槽位 value_kind 为 text 的金额/比例类：value 写 数字+单位 并去掉千分位逗号'
    '（如 22548513485.42元、60万元、约200.00万元）；\n'
    '5) 日期一律 YYYY-MM-DD；\n'
    '6) 数值精度与原文一致，禁止自行舍入；原文有约数的保留"约"。')


def load_contract(ev):
    p = [t for t in json.load(open(f'{ROOT}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if t['event_key'] == ev][0]['contract']
    if not os.path.isabs(p):
        p = f'{ROOT}/v23a/{p}'
    return json.load(open(p))


def e_user(contract, doc_ids, cell):
    f = FACTOR[cell]
    u = P1.e_user(contract, doc_ids, 'E1' if f['h1'] else 'Baseline')
    if f['h2']:
        u += '\n\n' + AM.AMOUNT_PROMPT_BLOCK + '\n' + VALUE_FORM_RULES
    return u


def sink_user(contract, merged, relations, verified, cell):
    f = FACTOR[cell]
    base_arm = 'E1' if f['h1'] else 'Baseline'
    u = P1.p_user(contract, merged, relations, verified, base_arm)
    if f['h1']:
        u += '\n\n' + CH.build_sink_instruction(verified)
    if f['h2']:
        u += '\n\n' + VALUE_FORM_RULES
    return u


def run_cell(cell, ev, rep, contract, call):
    docs = sorted(contract['source_pages'].keys())
    half = (len(docs) + 1) // 2
    e0_docs, e1_docs = docs[:half], docs[half:] or docs[:1]
    f = FACTOR[cell]
    e0 = extract_any(call('e0', P1.E_SYS, e_user(contract, e0_docs, cell), P1.MAXTOK['E']))
    e1 = extract_any(call('e1', P1.E_SYS, e_user(contract, e1_docs, cell), P1.MAXTOK['E']))
    t = extract_any(call('t', P1.M_SYS, P1.t_user(contract, e0), P1.MAXTOK['t']))
    m = extract_any(call('m', P1.M_SYS, P1.m_user(contract, {'e0': e0, 'e1': e1}), P1.MAXTOK['m']))
    r = extract_any(call('r', P1.R_SYS, P1.r_user(contract, m), P1.MAXTOK['r']))

    if f['h1']:
        table = CH.build_evidence_table({'e0': e0, 'e1': e1})
        verified, rejected = CH.verify_evidence(table, contract)
        merged = {'facts': [dict(x) for x in verified]}
    else:
        verified = [x for x in (m.get('facts') or []) if isinstance(x, dict)]
        merged = {'facts': verified}

    p = extract_any(call('p', P1.P_SYS, sink_user(contract, merged, r, verified, cell),
                         P1.MAXTOK['p']))
    res = Q1.score_task(contract, p)
    reuse = CH.check_reuse(p, verified) if f['h1'] else None
    return dict(task=ev, cell=cell, rep=rep, n=res['n_facts'], q=res['q'],
                value=res['fact_value_correct_rate'], loc=res['evidence_localization_rate'],
                sup=res['evidence_support_rate'], unk=res['unknown_accuracy'],
                gate=res['critical_gate'],
                n_verified=len(verified) if f['h1'] else None,
                reuse_rate=None if reuse is None else 1 - (reuse['violation_rate'] or 0))


def build_order():
    cells = []
    for ev in TASKS:
        for rep in REPS:
            block = [(ev, rep, c) for c in CELLS]
            random.Random(SEED + hash(ev) % 100).shuffle(block)
            cells.extend(block)
    return cells


class GuardedTransport:
    def __init__(self, caps, mean_call_cost):
        from stage_d_v2_transport import Ledger, build_request
        self.Ledger = Ledger
        self.ledger = Ledger(f'{QP}/QP4_LEDGER.jsonl')
        self.index = dict(self.ledger.index)
        for path in (f'{QP}/QP1_LEDGER.jsonl', f'{QP}/QP2_LEDGER.jsonl'):
            if os.path.exists(path):
                for line in open(path):
                    rec = json.loads(line)
                    self.index.setdefault((rec['purpose'], rec['prompt_sha256']), rec)
        self.caps = caps
        self.mean = mean_call_cost
        self.stopped = None

    def call(self, alias, system, user, max_tokens, purpose):
        from stage_d_v2_transport import build_request
        body = build_request(alias, system, user, max_tokens)
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hit = self.index.get((purpose, sha))
        if hit is not None:
            return hit
        if len(self.ledger.records) + 1 > self.caps['calls']:
            self.stopped = 'calls cap'; raise RuntimeError('calls cap')
        if self.ledger.tokens > self.caps['tokens']:
            self.stopped = 'token cap'; raise RuntimeError('token cap')
        if self.ledger.cost + self.mean > self.caps['yuan'] * (1 - RESERVE):
            self.stopped = 'cost cap (pre-charge)'; raise RuntimeError('cost cap')
        rec = self._real(alias, body, purpose, sha)
        self.index[(purpose, sha)] = rec
        return rec

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
        ch = d['choices'][0]; u = d.get('usage', {})
        c = ch.get('message', {}).get('content', '')
        text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
        tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
        rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias=alias, model=MODEL_CFG[alias]['model'],
                   thinking_mode=MODEL_CFG[alias]['thinking'], reasoning_effort=MODEL_CFG[alias]['effort'],
                   purpose=purpose, max_tokens=body.get('max_tokens'), prompt_sha256=sha,
                   prompt_chars=sum(len(m['content']) for m in body['messages']),
                   usage=dict(input_tokens=tin, output_tokens=tout),
                   accounting_yuan=round(tin * 0.8e-6 + tout * 2.8e-6, 8),
                   latency_s=round(time.monotonic() - t0, 3),
                   stop_reason={'stop': 'end_turn', 'length': 'max_tokens'}.get(
                       ch.get('finish_reason'), ch.get('finish_reason')),
                   text=text)
        self.ledger.add(rec)
        return rec


def main(mock=False):
    if mock:
        from qp4_dryrun import mock_provider
        out = []
        for ev, rep, cell in build_order():
            out.append(run_cell(cell, ev, rep, load_contract(ev), mock_provider(load_contract(ev), cell)))
        return out
    from qp4_dryrun import mean_call_cost
    tr = GuardedTransport(CAPS, mean_call_cost())
    results, status = [], 'COMPLETE'
    for ev, rep, cell in build_order():
        contract = load_contract(ev)

        def call(node, system, user, mt, _ev=ev, _c=cell, _r=rep):
            return tr.call('glm53flash', system, user, mt,
                           purpose=f'qp4|{_ev}|{_c}|r{_r}|{node}')['text']
        before = len(tr.ledger.records)
        try:
            results.append(run_cell(cell, ev, rep, contract, call))
            r = results[-1]
            print(f"  {ev:9s} {cell} r{rep} +{len(tr.ledger.records)-before:2d} "
                  f"Q={r['q']:.3f} val={r['value']:.2f} loc={r['loc']:.2f} "
                  f"sup={r['sup']:.2f} reuse={r['reuse_rate']}", flush=True)
        except Exception as e:
            results.append(dict(task=ev, cell=cell, rep=rep, error=f'{type(e).__name__}: {e}'[:160]))
            if 'no JSON value' in str(e) or 'parse_fail' in str(e):
                # real model failure mode: record the failed cell and continue
                results.append(dict(task=ev, cell=cell, rep=rep, parse_error=True, q=None))
                print(f"  {ev} {cell} r{rep} PARSE_FAIL (recorded, continuing)", flush=True)
            else:
                status = 'ERROR_AUTH' if '401' in str(e) else ('INCOMPLETE' if 'cap' in str(e) else 'ERROR')
                print(f"  {ev} {cell} r{rep} ERROR {e}", flush=True)
                break
        json.dump(dict(status=status, used=dict(calls=len(tr.ledger.records), tokens=tr.ledger.tokens,
                                                yuan=round(tr.ledger.cost, 4)), results=results),
                  open(f'{QP}/QP4_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{QP}/QP4_PROGRESS.json.tmp', f'{QP}/QP4_PROGRESS.json')
    json.dump(dict(batch='QP4_FACTORIAL', status=status, caps=CAPS, seed=SEED,
                   used=dict(calls=len(tr.ledger.records), tokens=tr.ledger.tokens,
                             yuan=round(tr.ledger.cost, 4)), results=results),
              open(f'{QP}/QP4_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={len(tr.ledger.records)}/{CAPS['calls']} "
          f"tokens={tr.ledger.tokens}/{CAPS['tokens']} ¥{tr.ledger.cost:.3f}/{CAPS['yuan']}")


if __name__ == '__main__':
    main(mock='--mock' in sys.argv)
