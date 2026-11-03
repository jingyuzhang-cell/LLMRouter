"""ST multi-run repetition pairing — PROTOCOL v2.1, staged 2026-10-14.
PAID HOLD: launches ONLY on explicit numeric authorization.

Design (option A default): clean x1 + S5+Cap x{reps} + S6 x{reps}, reps=3 ->
7 runs / 42 planned calls. Same F7 fault, same frozen ST 10K line-split
retrieval, same executor/deadline/ledger discipline as f7_v2_experiment.
v2.1 delta: deepseek extract cap 2048->2560 (R2's t2 hit 2048 once); glm
extract stays 2048 (observed max 1793). Caps recomputed in pre-flight.

Scoring: st_scoring_v2 field rules (RF5/RF6/RF7; all three v2-reachable in the
ST 10K pack -> reachable ceiling 3/3). Variance hypothesis measured per run:
t1/t4 content-preservation flags recorded for every call.
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
import evidence_packer as ep
import st_scoring_v2
import st_window_validation as swv
from execution_v2 import DeadlineGuardedExecutor, DeadlineExceeded
from json_compat import parse_layers, node_contract
from e4_controlled_experiment import (load_env, node_prompt, MODEL_NODES,
                                      build_stats, TASK_ST)

P = PILOT_DIR
DEADLINE = 90.0
USD2RMB = 7.1
PRICING = {'in': 0.15, 'out': 0.60}  # off-peak default; peak-authorized run overrides
F7 = [('t1', 'deepseek')]
B3P = {'t1': 'deepseek', 't2': 'deepseek', 't3': 'glm53', 't4': 'glm53',
       't5': 'deepseek', 't6': 'glm53'}
OUT_CAPS = {'glm53': {'extract': 2048, 'mid': 2560, 'report': 2048},
            'glm53flash': {'extract': 2048, 'mid': 2560, 'report': 2048},
            'deepseek': {'extract': 2560, 'mid': 4096, 'report': 2048},  # v2.1
            'qwen': {'extract': 2048, 'mid': 2560, 'report': 1536}}
NODE_KIND = {'t1': 'extract', 't2': 'extract', 't3': 'mid', 't4': 'mid',
             't5': 'mid', 't6': 'report'}
IN_EST = {'t1': 3900, 't2': 3900, 't3': 3000, 't4': 3100, 't5': 2550, 't6': 2500}

index = swv.build_st_index()
ST_RANKED = swv.rank_st(index)


def st_packs():
    return {line: ep.pack_global(5000, doc_ids=docs, index=index, ranked=ST_RANKED)
            for line, docs in swv.LINE_DOCS.items()}


def peak_now():
    import datetime
    u = datetime.datetime.now(datetime.timezone.utc)
    if u.weekday() >= 5:
        return False
    return 1 <= u.hour < 4 or 6 <= u.hour < 10


class STMeter:
    """Same discipline as V2Meter: persist-first, resume, hard caps, off-peak."""

    def __init__(self, dry_run, cap_calls, cap_tokens, cap_cash):
        self.dry_run, self.cap_calls, self.cap_tokens, self.cap_cash = \
            dry_run, cap_calls, cap_tokens, cap_cash
        self.lock = threading.Lock()
        self.calls = self.tokens = 0
        self.cash = 0.0
        self.ledger = P / ('stv2_ledger_dryrun.jsonl' if dry_run else 'stv2_ledger.jsonl')
        self.resp = P / ('stv2_resp_dryrun.jsonl' if dry_run else 'stv2_resp.jsonl')
        self.persisted = {}
        if not dry_run and self.resp.exists():
            for line in self.resp.read_text().splitlines():
                if line.strip():
                    d = json.loads(line)
                    self.persisted[(d['run_id'], d['node'], d['model'])] = d['text']
        if not dry_run:
            load_env()

    def _check(self, extra=0):
        assert self.calls < self.cap_calls, f'CALL CAP {self.cap_calls}'
        assert self.tokens + extra <= self.cap_tokens, f'TOKEN CAP {self.cap_tokens}'
        assert self.cash <= self.cap_cash, f'CASH CAP {self.cap_cash}'

    def call(self, run_id, node, alias, system, user, timeout_s=120, **kw):
        cap = OUT_CAPS[alias][NODE_KIND[node]]
        cached = self.persisted.get((run_id, node, alias))
        if cached is not None:
            return {'text': cached, 'in': 0, 'out': 0, 'stop': 'reused', 'lat': 0.0}
        est = int((len(system) + len(user)) * 0.7) + cap
        with self.lock:
            self._check(est)
        if self.dry_run:
            canned = {'t1': '{"facts":[{"fact_key":"a","value":"1,000万元罚款","doc_id":"csrc_penalty_2024_41","quote":"1,000万元罚款"}]}',
                      't2': '{"facts":[{"fact_key":"b","value":"v","doc_id":"st_announce_2024_020","quote":"q"}]}',
                      't3': '{"timeline":[{"date":"2023-10-17","event":"e","doc_id":"csrc_penalty_2024_41"}]}',
                      't4': '{"entity_facts":[{"fact_key":"c","value":"虚假自循环业务","doc_id":"csrc_penalty_2024_41"}]}',
                      't5': '{"verdicts":[{"fact":"f","verdict":"SUPPORTED","doc_id":"csrc_penalty_2024_41"}]}',
                      't6': '{"report":"江苏舜天2009至2021年专网通信业务为虚假自循环业务，证监会处以1,000万元罚款，虚增金额85,340,644.67元。本报告为dry-run管线验证文本，长度超过一百字以满足t6报告契约的最小长度校验要求，不构成真实结论，仅验证ST管线。"}'}
            raw = {'text': canned[node], 'in': 500, 'out': 300, 'stop': 'end_turn', 'lat': 1.0}
        elif alias in ('glm53', 'glm53flash', 'deepseek', 'qwen'):
            import transport
            raw = transport.call_model(alias, system, user, cap, timeout_s)
        cash = ((raw['in'] * PRICING['in'] + raw['out'] * PRICING['out']) / 1e6 * USD2RMB
                if alias == 'deepseek' else 0.0)
        if not self.dry_run:
            with self.lock:
                with open(self.resp, 'a') as f:
                    f.write(json.dumps({'call_id': self.calls + 1, 'run_id': run_id,
                                        'node': node, 'model': alias, 'text': raw['text']},
                                       ensure_ascii=False) + '\n')
        rec = {'call_id': self.calls + 1, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'run_id': run_id, 'node': node, 'model': alias, 'max_tokens': cap,
               'timeout_s': timeout_s, 'in': raw['in'], 'out': raw['out'],
               'stop': raw['stop'], 'truncated': raw['stop'] in ('length', 'max_tokens'),
               'lat': raw['lat'], 'cash_rmb': round(cash, 6)}
        with self.lock:
            self.calls += 1
            self.tokens += raw['in'] + raw['out']
            self.cash += cash
            self._check()
            if not self.dry_run:
                with open(self.ledger, 'a') as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return raw


class STExecutor(DeadlineGuardedExecutor):
    def _attempt(self, node, alias, what):
        if (node, alias) in self.blocked:
            raise DeadlineExceeded(f'blocked:({node},{alias})')
        if not self._gate(node, alias, what):
            raise DeadlineExceeded('deadline_gate')
        rem = self.deadline - self.elapsed()
        timeout_s = int(max(5, min(120, rem - 1)))
        merged = json.dumps(self.outputs.get('m', {}), ensure_ascii=False)
        system, user = node_prompt(self.event, node, merged, self.outputs)
        raw = self.meter.call(self.run_id, node, alias, system, user, timeout_s=timeout_s)
        self.last_lat[(node, alias)] = raw.get('lat', 5.0)
        pl = parse_layers(raw['text'])
        strict_ok, compat_ok, value, layer = node_contract(node, pl)
        self.node_log.append({'node': node, 'model': alias, 'strict_ok': strict_ok,
                              'compat_ok': compat_ok, 'parse_layer': layer,
                              'in': raw.get('in', 0), 'out': raw.get('out', 0),
                              'lat': raw.get('lat', 0.0),
                              'truncated': raw.get('stop') in ('length', 'max_tokens')})
        return strict_ok, compat_ok, value


def run_specs(reps):
    specs = [('ST_clean_r1', dict(B3P), [], 'static')]
    for i in range(1, reps + 1):
        specs.append((f'ST_S5Cap_F7_r{i}', dict(B3P), F7, 's5cap'))
    for i in range(1, reps + 1):
        specs.append((f'ST_S6_F7_r{i}', dict(B3P), F7, 's6'))
    return specs


def preflight(reps, peak_ok=False):
    import subprocess
    c1 = subprocess.run([sys.executable, 'test_fixes_v2.py'], capture_output=True, cwd=P).returncode == 0
    ledger = P / 'stv2_ledger.jsonl'
    c2 = not ledger.exists() or not any(ledger.read_text().splitlines())
    c3 = (not peak_now()) or peak_ok
    plan = []
    for rid, pi, blocked, _ in run_specs(reps):
        for n in MODEL_NODES:
            model = ('glm53' if (n == 't1' and blocked) else pi[n])
            plan.append((rid, n, model, IN_EST[n], OUT_CAPS[model][NODE_KIND[n]]))
    worst_tok = sum(e + c for _, _, _, e, c in plan)
    worst_cash = sum((e * PRICING['in'] + c * PRICING['out']) / 1e6 * USD2RMB
                     for _, n, m, e, c in plan if m == 'deepseek')
    cap_calls, cap_tokens, cap_cash = len(plan) + 2, int(worst_tok * 1.05), round(worst_cash * 1.1, 2)
    c4 = len(plan) <= cap_calls and worst_tok <= cap_tokens and worst_cash <= cap_cash
    conds = {'C1_regression': c1, 'C2_fresh_ledger': c2,
             'C3_offpeak_or_authorized': c3, 'C4_reservation': c4}
    return {'conditions': conds, 'pricing': dict(PRICING),
            'peak_authorized': peak_ok and peak_now(),
            'verdict': 'GO' if all(conds.values()) else 'NO-GO',
            'detail': {'planned_calls': len(plan), 'worst_tokens': worst_tok,
                       'worst_cash_rmb': round(worst_cash, 4),
                       'requested_caps': {'calls': cap_calls, 'tokens': cap_tokens,
                                          'cash_rmb': cap_cash}}}


def score_st_run(res, pack_text):
    o = res['outputs']
    parts = [str(o['t6']) if o.get('t6') else '',
             json.dumps(o['t5'], ensure_ascii=False) if o.get('t5') else '']
    text = '\n'.join(parts)
    s = st_scoring_v2.score_report_st(text)
    chain = st_scoring_v2.chain_filter_st(s['covered'], pack_text)
    strict_n = sum(1 for l in res['node_log'] if l['strict_ok'])
    compat_n = sum(1 for l in res['node_log'] if l['compat_ok'])
    return {'full_set': s['score'], 'per_fact': s['per_fact'],
            'chain_facts': chain, 'reachable_chain': f'{len(chain)}/3',
            'strict_rate': f'{strict_n}/{len(res["node_log"])}',
            'compat_rate': f'{compat_n}/{len(res["node_log"])}'}


def main(dry_run=False, reps=3, peak_ok=False):
    if peak_ok:
        PRICING['in'], PRICING['out'] = 0.30, 1.20  # authorized peak pricing
    lock_fh = open(P / ('stv2_dryrun.lock' if dry_run else 'stv2.lock'), 'w')
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('REFUSING TO START: another st_pairing instance holds the lock.')
    pre = preflight(reps, peak_ok=peak_ok)
    print('PRE-FLIGHT:', json.dumps(pre, ensure_ascii=False))
    if dry_run:
        pre['verdict'] = 'GO(dry-run)'
    if not pre['verdict'].startswith('GO'):
        print('NO-GO — no real calls.')
        return
    packs = st_packs()
    pack_text = packs['t1']['text'] + '\n' + packs['t2']['text']
    event = {'task': TASK_ST, 'lines': {k: packs[k]['text'] for k in ('t1', 't2')}}
    stats = build_stats()
    d = pre['detail']['requested_caps']
    meter = STMeter(dry_run, d['calls'], d['tokens'], d['cash_rmb'])
    out_path = P / ('stv2_results_dryrun.json' if dry_run else 'stv2_results.json')
    results = json.loads(out_path.read_text()) if out_path.exists() else {'runs': {}}
    for rid, pi0, blocked, policy in run_specs(reps):
        if rid in results['runs']:
            print(f'  [skip] {rid}')
            continue
        print(f'  [run ] {rid} policy={policy}', flush=True)
        ex = STExecutor(meter, event, rid, pi0, blocked, policy, stats, deadline_s=DEADLINE)
        try:
            res = ex.run()
        except AssertionError as e:
            print(f'  CAP HIT at {rid}: {e} — stop, HOLD')
            break
        sc = score_st_run(res, pack_text)
        rec = {'policy': policy, 'pi0': pi0, 'blocked': blocked,
               'complete': res['complete'], 'wall_s': res['wall_s'],
               'deadline_met': res['deadline_met'], 'violation_s': res['deadline_violation_s'],
               'skips': res['skips'], 'decisions': res['decisions'],
               'node_log': res['node_log'],
               'tokens': sum(l['in'] + l['out'] for l in res['node_log']),
               'cash_rmb': round(sum((l['in'] * PRICING['in'] + l['out'] * PRICING['out']) / 1e6 * USD2RMB
                                     for l in res['node_log'] if l['model'] == 'deepseek'), 4),
               **sc}
        results['runs'][rid] = rec
        results['meter'] = {'calls': meter.calls, 'tokens': meter.tokens,
                            'cash_rmb': round(meter.cash, 4)}
        results['preflight'] = pre
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        print(f"    wall={res['wall_s']}s complete={res['complete']} full={sc['full_set']} "
              f"chain={sc['reachable_chain']} strict={sc['strict_rate']}", flush=True)
    print('METER:', json.dumps({'calls': meter.calls, 'tokens': meter.tokens,
                                'cash_rmb': round(meter.cash, 4)}))
    print('saved:', out_path)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--peak-ok', action='store_true',
                    help='authorized peak pricing (cash cap recomputed at $0.30/$1.20)')
    args = ap.parse_args()
    main(dry_run=args.dry_run, reps=args.reps, peak_ok=args.peak_ok)
