"""IDENTIFIABILITY SUPPLEMENT — frozen protocol runner (staged 2026-10-14).
PAID HOLD: launches ONLY on explicit separate authorization. <=22 calls.

Sole question: does expanding R (re-executing t1 with a different model at the
frozen state X) produce REAL, IDENTIFIABLE, worth-the-cost task-level quality?
Action-conditioned task quality = the full chain runs to the deliverable and is
scored by the v2 field rules + evidence chain (NOT grounding proxies alone).

FROZEN STATE X (from f7v2 R2, KDX, zero reconstruction):
  - position: after the t2 truncation fault (~26.6s of that run)
  - t1 cache: glm53 output (saved; 15/22 quotes grounded — measured)
  - t2: glm53 re-executed output (saved, REUSED as-is in every arm)
  - F7 blocked pair: (t1, deepseek)
  - downstream pi frozen = R2's actual: t3=glm53, t4=glm53, t5=deepseek, t6=glm53

PRE-REGISTERED ARMS (no post-hoc selection):
  A  reference  = frozen f7v2 R2 chain (t1-glm53 cache kept)      n=1, 0 calls
  B1 R-expansion: t1 -> glm53flash + full downstream                x2 reps
  B2 R-expansion: t1 -> qwen-plus  + full downstream                x2 reps
  C  stability : t5(deepseek) re-run x2 on R2's frozen t3+t4 inputs
Calls: 0 + 5x2 + 5x2 + 2 = 22 (cap 24). Cash: flash=subscription Y0;
qwen certified Y0.8/M in, Y2/M out; DS off-peak Y0.15/0.6 (schedule-gated).

PRE-REGISTERED DECISION RULE (conclusion classes):
  (i)  joint opportunity: B1 or B2 chain-valid T1 coverage >= A + 2 facts in
       2/2 reps AND extra cash <= Y0.05/chain  -> design S6 v5
  (ii) staged/local dominant: every B arm <= A (no gain or worse) -> closure
       suffices, narrow thesis
  (iii) unidentifiable: 1-fact flips / mixed reps -> STOP route 2 per directive
Latency is EXCLUDED from the criterion (cross-hour incomparability, frozen).
All failures/timeouts/invalid outputs recorded verbatim; no retries; no
artificial gains for larger R.
"""
import argparse
import fcntl
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR
import transport
import scoring_v2
import evidence_packer as ep
from json_compat import parse_layers, node_contract
from e4_controlled_experiment import node_prompt

P = PILOT_DIR
CAP_CALLS, CAP_TOKENS, CAP_CASH = 26, 140_000, 0.20  # amended: +2 verify.v1 arms
PRICING = {'glm53': (0, 0), 'glm53flash': (0, 0),
           'qwen': (0.8, 2.0),                      # CNY/M, certified official
           'deepseek': (0.15, 0.60)}                # CNY/M off-peak, gate-checked
OUT_CAPS = {'glm53': {'extract': 2048, 'mid': 2560, 'report': 2048},
            'glm53flash': {'extract': 2048, 'mid': 2560, 'report': 2048},
            'qwen': {'extract': 2048, 'mid': 2560, 'report': 1536},
            'deepseek': {'extract': 2560, 'mid': 2560, 'report': 2048}}
KIND = {'t1': 'extract', 't2': 'extract', 't3': 'mid', 't4': 'mid',
        't5': 'mid', 't6': 'report'}


def peak_now():
    import datetime
    u = datetime.datetime.now(datetime.timezone.utc)
    return u.weekday() < 5 and (1 <= u.hour < 4 or 6 <= u.hour < 10)


class Meter:
    def __init__(self, dry_run):
        self.dry = dry_run
        self.lock = threading.Lock()
        self.calls = self.tokens = 0
        self.cash = 0.0
        self.ledger = P / ('ident_ledger_dryrun.jsonl' if dry_run else 'ident_ledger.jsonl')
        self.resp = P / ('ident_resp_dryrun.jsonl' if dry_run else 'ident_resp.jsonl')
        if not dry_run:
            from e4_controlled_experiment import load_env
            load_env()

    def _check(self, extra=0):
        assert self.calls < CAP_CALLS, f'CALL CAP {CAP_CALLS}'
        assert self.tokens + extra <= CAP_TOKENS, f'TOKEN CAP {CAP_TOKENS}'
        assert self.cash <= CAP_CASH, f'CASH CAP {CAP_CASH}'

    def _account_dry(self, run_id, node, model, raw, cap):
        ci, co = PRICING[model]
        with self.lock:
            self.calls += 1
            self.tokens += raw['in'] + raw['out']
            self.cash += (raw['in'] * ci + raw['out'] * co) / 1e6
            self._check()

    def call(self, run_id, node, model, system, user, timeout_s=120):
        cap = OUT_CAPS[model][KIND[node]]
        est = int((len(system) + len(user)) * 0.7) + cap
        with self.lock:
            self._check(est)
        if self.dry:
            if run_id.startswith('D_verify'):
                raw = {'text': '{"fact_verdicts":[{"idx":0,"grounded":true,"note":"ok"},'
                       '{"idx":1,"grounded":false,"note":"not_found"}]}',
                       'in': 500, 'out': 200, 'stop': 'end_turn', 'lat': 1.0}
                ci, co = PRICING[model]
                # (fall through to accounting below with this raw)
                self._account_dry(run_id, node, model, raw, cap)
                return raw
            canned = {'t1': '{"facts":[{"fact_key":"k","value":"60万元罚款","doc_id":"kdx_penalty_2020","quote":"60万元罚款"}]}',
                      't3': '{"timeline":[{"date":"2019-01-01","event":"e","doc_id":"kdx_penalty_2020"}]}',
                      't4': '{"entity_facts":[{"fact_key":"k","value":"2015年至2018年年度报告存在虚假记载","doc_id":"kdx_penalty_2020"}]}',
                      't5': '{"verdicts":[{"fact":"f","verdict":"SUPPORTED","doc_id":"kdx_penalty_2020"}]}',
                      't6': '{"report":"康得新2015年至2018年年度报告存在虚假记载，证监会对康得新处以60万元罚款，北京银行西单支行现金管理业务合作协议事项经问询核实。dry-run管线验证文本，长度超过一百字以满足t6契约的最小长度校验要求，不构成真实结论。"}'}
            raw = {'text': canned.get(node, '{}'), 'in': 500, 'out': 300,
                   'stop': 'end_turn', 'lat': 1.0}
        else:
            raw = transport.call_model(model, system, user, cap, timeout_s)
        ci, co = PRICING[model]
        cash = (raw['in'] * ci + raw['out'] * co) / 1e6
        if not self.dry:
            with self.lock:
                with open(self.resp, 'a') as f:
                    f.write(json.dumps({'call_id': self.calls + 1, 'run_id': run_id,
                                        'node': node, 'model': model, 'text': raw['text']},
                                       ensure_ascii=False) + '\n')
        rec = {'call_id': self.calls + 1, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'run_id': run_id, 'node': node, 'model': model, 'max_tokens': cap,
               'in': raw['in'], 'out': raw['out'], 'stop': raw['stop'],
               'truncated': raw['stop'] in ('length', 'max_tokens'), 'lat': raw['lat'],
               'cash_rmb': round(cash, 6)}
        with self.lock:
            self.calls += 1
            self.tokens += raw['in'] + raw['out']
            self.cash += cash
            self._check()
            if not self.dry:
                with open(self.ledger, 'a') as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return raw


def fd_flagged_indices(facts, pack_text):
    from pilot_common import norm as _n
    hay = _n(pack_text)
    out = []
    for i, f in enumerate(facts):
        if not isinstance(f, dict):
            out.append(i); continue
        q = _n(str(f.get('quote', '') or ''))
        if not (q and len(q) >= 6 and q in hay):
            out.append(i)
    return out


def flagged_indices_sample(idx, k=8):
    return idx[:k] if idx else []


def frozen_state():
    """Load the frozen f7v2 R2 pieces (t1 cache, t2 output) + packs + A-arm result."""
    rows = [json.loads(l) for l in open(P / 'f7v2_resp.jsonl') if l.strip()]

    def last(node, model=None):
        c = [r for r in rows if r['run_id'] == 'R2_S5Cap_F7' and r['node'] == node
             and (model is None or r['model'] == model)]
        return c[-1]['text'] if c else None

    ranked = ep.rank_chunks(ep.build_index())
    packs = ep.pack_lines(10000, {'t1': ['kdx_penalty_2020', 'kdx_notice_2019', 'kdx_notice_2020'],
                                  't2': ['kdx_inquiry_2018', 'kdx_inquiry_2019']}, ranked=ranked)
    import v3_kdx_qcl_ab
    return {'t1_cache': last('t1', 'glm53'), 't2_out': last('t2', 'glm53'),
            't3_in_A': last('t3'), 't4_in_A': last('t4'),   # for stability arm C
            'packs': packs,
            'event': {'task': v3_kdx_qcl_ab.TASK,
                      'lines': {k: packs[k]['text'] for k in ('t1', 't2')}}}


def parse_ok(node, text):
    pl = parse_layers(text)
    s, c, v, layer = node_contract(node, pl)
    return c, v, layer


def run_chain(meter, run_id, t1_model, state):
    """One R-expansion chain: t1(new model) -> m -> t3..t6 with frozen pi."""
    outputs, log = {}, []
    raw = meter.call(run_id, 't1', t1_model, *prompt_for('t1', state, outputs))
    ok, v, layer = parse_ok('t1', raw['text'])
    log.append({'node': 't1', 'model': t1_model, 'ok': ok, 'layer': layer,
                'in': raw['in'], 'out': raw['out'],
                    'truncated': raw['stop'] in ('length', 'max_tokens')})
    if not ok:
        return None, log, outputs
    outputs['t1'] = v
    from merge_facts import merge_facts
    pl2 = parse_ok('t2', state['t2_out'])
    outputs['t2'] = pl2[1] if pl2[0] else []
    outputs['m'] = merge_facts([outputs['t1'], outputs['t2']], ['t1', 't2'])
    for node, model in (('t3', 'glm53'), ('t4', 'glm53'), ('t5', 'deepseek'), ('t6', 'glm53')):
        raw = meter.call(run_id, node, model, *prompt_for(node, state, outputs))
        ok, v, layer = parse_ok(node, raw['text'])
        log.append({'node': node, 'model': model, 'ok': ok, 'layer': layer,
                    'in': raw['in'], 'out': raw['out'],
                    'truncated': raw['stop'] in ('length', 'max_tokens')})
        if not ok:
            return None, log, outputs
        outputs[node] = v
    return True, log, outputs


def prompt_for(node, state, outputs):
    import json as _j
    merged = _j.dumps(outputs.get('m', {}), ensure_ascii=False)
    return node_prompt(state['event'], node, merged, outputs)


def score_arm(state, outputs):
    pack_text = state['packs']['t1']['text'] + '\n' + state['packs']['t2']['text']
    text = ''
    if outputs.get('t6'):
        text += str(outputs['t6'])
    if outputs.get('t5'):
        text += _j2(outputs['t5'])
    s = scoring_v2.score_report(text)
    chain = scoring_v2.chain_filter(s['covered'], pack_text)
    return {'full': s['score'], 'covered': s['covered'],
            'chain_valid': chain, 'chain_n': len(chain)}


def _j2(v):
    import json as _j
    return _j.dumps(v, ensure_ascii=False)


def main(dry_run=False):
    lock_fh = open(P / ('ident_dryrun.lock' if dry_run else 'ident.lock'), 'w')
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('REFUSING: another ident run holds the lock.')
    if not dry_run and peak_now():
        print('NO-GO: DeepSeek peak window (DS budget certified at off-peak only).')
        return
    state = frozen_state()
    meter = Meter(dry_run)
    out_path = P / ('ident_results_dryrun.json' if dry_run else 'ident_results.json')
    results = {'config': __doc__.splitlines()[1], 'arms': {}}

    # A-arm: frozen R2 deliverable, rescored under the same v2 rules
    rows = [json.loads(l) for l in open(P / 'f7v2_resp.jsonl') if l.strip()]
    a_t6 = [r for r in rows if r['run_id'] == 'R2_S5Cap_F7' and r['node'] == 't6'][-1]['text']
    a_t5 = [r for r in rows if r['run_id'] == 'R2_S5Cap_F7' and r['node'] == 't5'][-1]['text']
    a_out = {'t6': parse_ok('t6', a_t6)[1], 't5': parse_ok('t5', a_t5)[1]}
    results['arms']['A_frozen'] = {**score_arm(state, a_out), 'calls': 0, 'source': 'f7v2 R2'}

    # B1/B2 arms x2 reps
    for tag, model in (('B1_flash', 'glm53flash'), ('B2_qwen', 'qwen')):
        for rep in (1, 2):
            rid = f'{tag}_r{rep}'
            print(f'  [chain] {rid}', flush=True)
            ok, log, outputs = run_chain(meter, rid, model, state)
            rec = {'ok': ok, 'node_log': log,
                   'tokens': sum(l['in'] + l['out'] for l in log),
                   'cash': round(sum(PRICING[l['model']][0] * l['in'] / 1e6
                                     + PRICING[l['model']][1] * l['out'] / 1e6 for l in log), 4)}
            if ok:
                rec.update(score_arm(state, outputs))
            else:
                rec.update({'full': 'FAILED', 'chain_valid': [], 'chain_n': 0,
                            'fail_node': next((l['node'] for l in log if not l['ok']), None)})
            results['arms'][rid] = rec
            print(f"    ok={ok} chain_n={rec['chain_n']} tok={rec['tokens']}")

    # C-arm: t5 stability x2 on frozen t3+t4 inputs
    import json as _j
    t3v = parse_ok('t3', state['t3_in_A'])[1]
    t4v = parse_ok('t4', state['t4_in_A'])[1]
    outs_c = {'t3': t3v, 't4': t4v}
    for rep in (1, 2):
        rid = f'C_t5_stability_r{rep}'
        sys_p, usr_p = prompt_for('t5', state, outs_c)
        raw = meter.call(rid, 't5', 'deepseek', sys_p, usr_p)
        ok, v, layer = parse_ok('t5', raw['text'])
        results['arms'][rid] = {'ok': ok, 'n_verdicts': len(v) if ok else 0,
                                'unresolved': sum(1 for x in (v or [])
                                                  if isinstance(x, dict)
                                                  and str(x.get('verdict', '')).upper() == 'UNRESOLVED') if ok else None}
        print(f"    {rid}: ok={ok} verdicts={results['arms'][rid]['n_verdicts']} "
              f"UNRESOLVED={results['arms'][rid]['unresolved']}")

    # Amended arms: verify.v1 x2 on state-X's t1 cache, TARGETING the
    # detector-flagged facts (v5 implementation requirement), measuring the
    # verify node's own decision-flip potential. Response parse uses
    # fact_verdicts; prompts from the v5 loop design.
    from v5_loop_simulation import build_verify_prompt, parse_verify
    from json_compat import parse_layers as _pl
    t1_facts = (_pl(state['t1_cache'])['value'] or {}).get('facts', [])
    flagged_idx = fd_flagged_indices(t1_facts, state['packs']['t1']['text'])
    targets = [t1_facts[i] for i in flagged_indices_sample(flagged_idx, 8)] or t1_facts[:8]
    for rep in (1, 2):
        rid = f'D_verify_v1_r{rep}'
        sys_p, usr_p = build_verify_prompt('t1', targets, state['packs']['t1']['text'])
        raw = meter.call(rid, 't1', 'glm53flash', sys_p, usr_p)  # cheap subscription model
        vs = parse_verify(raw['text'])
        results['arms'][rid] = {
            'ok': vs is not None,
            'n_targets': len(targets),
            'n_flagged': sum(1 for v in (vs or []) if not v.get('grounded', True)) if vs else None,
            'in': raw['in'], 'out': raw['out'],
            'note': 'verify.v1 annotation: measures the verify node decision-flip channel'}
        print(f"    {rid}: ok={vs is not None} flagged={results['arms'][rid]['n_flagged']}/{len(targets)}")

    results['meter'] = {'calls': meter.calls, 'tokens': meter.tokens,
                        'cash_rmb': round(meter.cash, 4),
                        'caps': {'calls': CAP_CALLS, 'tokens': CAP_TOKENS, 'cash': CAP_CASH}}
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print('METER:', json.dumps(results['meter'], ensure_ascii=False))
    print('saved:', out_path)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    main(dry_run=a.dry_run)
