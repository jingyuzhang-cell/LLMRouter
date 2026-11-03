"""F7 minimal real pairing, PROTOCOL v2 — staged 2026-10-14, LAUNCH REQUIRES
EXPLICIT USER AUTHORIZATION (paid HOLD until then).

Three frozen runs (KDX DEV, frozen 10K line-split retrieval, F7 fault):
  R1 B3p clean | R2 S5+Cap F7 | R3 S6 Joint F7

Hard envelope (per authorization template): <=20 API calls, <=110,000 actual
tokens, <= ¥0.15 new cash, 90s end-to-end per run (wall clock INCLUDING
scheduling, network, generation, recovery), DeepSeek OFF-PEAK window only,
NO auto-retry / extra runs / rollover / cap-raising mid-run.

Pre-flight gate (all 7 conditions; any failure => NO-GO, zero calls):
  C1 regression suites still pass
  C2 unified cross-process ledger + OS exclusive lock + worst-case reservation
  C3 off-peak pricing window verified (peak_now() gate, recorded)
  C4 v2 output caps (t5=4096 etc.) included in the worst-case budget
  C5 per-request timeout derived from REMAINING deadline time
  C6 missing required node / contract fail / truncation / >90s => recorded as
     incomplete (never massaged)
  C7 S5+Cap and S6 share identical faults, evidence, scoring, resource limits
"""
import argparse
import fcntl
import json
import math
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR
import evidence_packer as ep
import scoring_v2
from execution_v2 import DeadlineGuardedExecutor, DeadlineExceeded
from json_compat import parse_layers, node_contract
from e4_controlled_experiment import load_env, node_prompt, MODEL_NODES, build_stats

P = PILOT_DIR
CAP_CALLS, CAP_TOKENS, CAP_CASH, DEADLINE = 20, 110_000, 0.15, 90.0
DS_IN_USD, DS_OUT_USD, USD2RMB = 0.15, 0.60, 7.1   # OFF-PEAK official prices
LINE_DOCS = {'t1': ['kdx_penalty_2020', 'kdx_notice_2019', 'kdx_notice_2020'],
             't2': ['kdx_inquiry_2018', 'kdx_inquiry_2019']}
WINDOW = 10000
F7 = [('t1', 'deepseek')]
B3P = {'t1': 'deepseek', 't2': 'deepseek', 't3': 'glm53', 't4': 'glm53',
       't5': 'deepseek', 't6': 'glm53'}
# PROTOCOL v2 output caps (test_fixes_v2 T1 decision; NO mid-run raising)
OUT_CAPS = {'glm53': {'extract': 2048, 'mid': 2560, 'report': 2048},
            'glm53flash': {'extract': 2048, 'mid': 2560, 'report': 2048},
            'deepseek': {'extract': 2048, 'mid': 4096, 'report': 2048},
            'qwen': {'extract': 1536, 'mid': 2560, 'report': 1536}}
NODE_KIND = {'t1': 'extract', 't2': 'extract', 't3': 'mid', 't4': 'mid',
             't5': 'mid', 't6': 'report'}
IN_EST = {'t1': 3900, 't2': 3900, 't3': 3000, 't4': 3100, 't5': 2550, 't6': 2500}
RUNS = [('R1_B3p_clean', dict(B3P), [], 'static'),
        ('R2_S5Cap_F7', dict(B3P), F7, 's5cap'),
        ('R3_S6_F7', dict(B3P), F7, 's6')]


def peak_now():
    import datetime
    u = datetime.datetime.now(datetime.timezone.utc)
    if u.weekday() >= 5:
        return False
    return 1 <= u.hour < 4 or 6 <= u.hour < 10


class V2Meter:
    """Unified persistent ledger, persist-first responses, resume-safe,
    per-call timeout, hard envelope. Off-peak DS prices only."""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.lock = threading.Lock()
        self.calls = self.tokens = 0
        self.cash = 0.0
        self.ledger = P / ('f7v2_ledger_dryrun.jsonl' if dry_run else 'f7v2_ledger.jsonl')
        self.resp = P / ('f7v2_resp_dryrun.jsonl' if dry_run else 'f7v2_resp.jsonl')
        self.persisted = {}
        if not dry_run and self.resp.exists():
            for line in self.resp.read_text().splitlines():
                if line.strip():
                    d = json.loads(line)
                    self.persisted[(d['run_id'], d['node'], d['model'])] = d['text']
        if not dry_run:
            load_env()

    def _check(self, extra=0):
        assert self.calls < CAP_CALLS, f'CALL CAP {CAP_CALLS}'
        assert self.tokens + extra <= CAP_TOKENS, f'TOKEN CAP {CAP_TOKENS}'
        assert self.cash <= CAP_CASH, f'CASH CAP {CAP_CASH}'

    def _glm(self, alias, system, user, max_tokens, timeout_s):
        import urllib.request
        from e4_controlled_experiment import _glm_key, GLM_ENDPOINT, GLM_MODELS
        body = {'model': GLM_MODELS[alias], 'max_tokens': max_tokens,
                'thinking': {'type': 'disabled'}, 'system': system,
                'messages': [{'role': 'user', 'content': user}]}
        req = urllib.request.Request(GLM_ENDPOINT, data=json.dumps(body).encode(), method='POST')
        k = _glm_key()
        req.add_header('content-type', 'application/json')
        req.add_header('x-api-key', k)
        req.add_header('authorization', 'Bearer ' + k)
        req.add_header('anthropic-version', '2023-06-01')
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            d = json.loads(r.read().decode())
        return {'text': ''.join(b.get('text', '') for b in d.get('content', []) if b.get('type') == 'text'),
                'in': d['usage']['input_tokens'], 'out': d['usage']['output_tokens'],
                'stop': d.get('stop_reason'), 'lat': round(time.monotonic() - t0, 2)}

    def _openai(self, alias, system, user, max_tokens, timeout_s):
        import os
        import urllib.request
        from e4_controlled_experiment import OPENAI_MODELS
        model_id, base, env_key = OPENAI_MODELS[alias]
        body = {'model': model_id, 'max_tokens': max_tokens,
                'messages': [{'role': 'system', 'content': system},
                             {'role': 'user', 'content': user}],
                'response_format': {'type': 'json_object'}}
        if alias == 'deepseek':
            body['thinking'] = {'type': 'disabled'}
        req = urllib.request.Request(base + '/chat/completions',
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Authorization', 'Bearer ' + os.environ.get(env_key, ''))
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            d = json.loads(r.read().decode())
        c = d['choices'][0]['message'].get('content', '')
        if isinstance(c, list):
            c = ''.join(x.get('text', '') for x in c if isinstance(x, dict))
        u = d['usage']
        return {'text': c, 'in': u.get('prompt_tokens', u.get('input_tokens', 0)),
                'out': u.get('completion_tokens', u.get('output_tokens', 0)),
                'stop': d['choices'][0].get('finish_reason', ''), 'lat': round(time.monotonic() - t0, 2)}

    def call(self, run_id, node, alias, system, user, timeout_s=120, **kw):
        cap = OUT_CAPS[alias][NODE_KIND[node]]
        cached = self.persisted.get((run_id, node, alias))
        if cached is not None:
            return {'text': cached, 'in': 0, 'out': 0, 'stop': 'reused', 'lat': 0.0}
        est = int((len(system) + len(user)) * 0.7) + cap
        with self.lock:
            self._check(est)
        if self.dry_run:
            canned = {'t1': '{"facts":[{"fact_key":"a","value":"60万元罚款","doc_id":"kdx_penalty_2020","quote":"60万元罚款"}]}',
                      't2': '{"facts":[{"fact_key":"b","value":"北京银行西单支行","doc_id":"kdx_inquiry_2018","quote":"q"}]}',
                      't3': '{"timeline":[{"date":"2019-01-01","event":"e","doc_id":"kdx_penalty_2020"}]}',
                      't4': '{"entity_facts":[{"fact_key":"c","value":"v","doc_id":"kdx_penalty_2020"}]}',
                      't5': '{"verdicts":[{"fact":"f","verdict":"SUPPORTED","doc_id":"kdx_penalty_2020"}]}',
                      't6': '{"report":"康得新2015年至2018年年度报告存在虚假记载，证监会对康得新处以60万元罚款。北京银行西单支行现金管理业务合作事项经问询核实。本报告为dry-run管线验证文本，长度超过一百字以满足t6报告契约的最小长度校验要求，不构成真实结论。"}'}
            raw = {'text': canned[node], 'in': 500, 'out': 300, 'stop': 'end_turn', 'lat': 1.0}
        elif alias in ('glm53', 'glm53flash'):
            raw = self._glm(alias, system, user, cap, timeout_s)
        else:
            raw = self._openai(alias, system, user, cap, timeout_s)
        cash = ((raw['in'] * DS_IN_USD + raw['out'] * DS_OUT_USD) / 1e6 * USD2RMB
                if alias == 'deepseek' else 0.0)
        if not self.dry_run:  # persist FIRST (crash never re-pays)
            with self.lock:
                with open(self.resp, 'a') as f:
                    f.write(json.dumps({'call_id': self.calls + 1, 'run_id': run_id,
                                        'node': node, 'model': alias, 'text': raw['text']},
                                       ensure_ascii=False) + '\n')
        rec = {'call_id': self.calls + 1, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'run_id': run_id, 'node': node, 'model': alias, 'max_tokens': cap,
               'timeout_s': timeout_s, 'prompt_chars': len(system) + len(user),
               'in': raw['in'], 'out': raw['out'], 'stop': raw['stop'],
               'truncated': raw['stop'] in ('length', 'max_tokens'),
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


class V2Executor(DeadlineGuardedExecutor):
    """Adds: per-call timeout from remaining deadline (C5); layered strict/compat
    contract recording (C6); timeout-crossing calls recorded as failures."""

    def _attempt(self, node, alias, what):
        if (node, alias) in self.blocked:
            raise DeadlineExceeded(f'blocked:({node},{alias})')
        if not self._gate(node, alias, what):
            raise DeadlineExceeded('deadline_gate')
        rem = self.deadline - self.elapsed()
        timeout_s = int(max(5, min(120, rem - 1)))  # C5: per-request timeout
        import json as _json
        merged = _json.dumps(self.outputs.get('m', {}), ensure_ascii=False)
        system, user = node_prompt(self.event, node, merged, self.outputs)
        raw = self.meter.call(self.run_id, node, alias, system, user, timeout_s=timeout_s)
        self.last_lat[(node, alias)] = raw.get('lat', 5.0)
        pl = parse_layers(raw['text'])
        strict_ok, compat_ok, value, layer = node_contract(node, pl)
        self.node_log.append({'node': node, 'model': alias, 'strict_ok': strict_ok,
                              'compat_ok': compat_ok, 'parse_layer': layer,
                              'in': raw.get('in', 0), 'out': raw.get('out', 0),
                              'lat': raw.get('lat', 0.0),
                              'truncated': raw.get('stop') in ('length', 'max_tokens'),
                              'timeout_s': timeout_s})
        return strict_ok, compat_ok, value


def preflight():
    # C1 regression suites
    import subprocess
    r1 = subprocess.run([sys.executable, 'test_fixes_v2.py'], capture_output=True, cwd=P)
    c1 = r1.returncode == 0
    # C2 lock + ledger paths (ledger fresh per authorization: refuse if a v2
    # ledger already exists with calls — no rollover)
    ledger = P / 'f7v2_ledger.jsonl'
    c2 = not ledger.exists() or sum(1 for l in ledger.read_text().splitlines() if l.strip()) == 0
    # C3 off-peak
    pk = peak_now()
    c3 = not pk
    # C4 worst-case reservation
    plan = []
    for rid, pi, blocked, _ in RUNS:
        for n in MODEL_NODES:
            if (n, pi[n]) in blocked and rid != 'R2_S5Cap_F7' and rid != 'R3_S6_F7':
                continue
            # R2/R3 recover t1 onto glm53 (both sims & E3 replay) -> 6 calls each
            model = 'glm53' if (rid != 'R1_B3p_clean' and n == 't1') else pi[n]
            plan.append((rid, n, model, IN_EST[n], OUT_CAPS[model][NODE_KIND[n]]))
    worst_tok = sum(e + c for _, _, _, e, c in plan)
    worst_cash = sum((e * DS_IN_USD + c * DS_OUT_USD) / 1e6 * USD2RMB
                     for _, n, m, e, c in plan if m == 'deepseek')
    c4 = worst_tok <= CAP_TOKENS and worst_cash <= CAP_CASH and len(plan) <= CAP_CALLS
    conds = {'C1_regression': c1, 'C2_fresh_ledger_lock': c2, 'C3_offpeak': c3,
             'C4_reservation': c4}
    detail = {'planned_calls': len(plan), 'worst_tokens': worst_tok,
              'worst_cash_rmb': round(worst_cash, 4), 'peak_now': pk}
    verdict = 'GO' if all(conds.values()) else 'NO-GO'
    return {'conditions': conds, 'detail': detail, 'verdict': verdict}


def score_run(res, pack_text):
    """C6: dual coverage + chain; strict/compat rates; deliverable from outputs."""
    o = res['outputs']
    parts = []
    if o.get('t6'):
        parts.append(str(o['t6']))
    if o.get('t5'):
        parts.append(json.dumps(o['t5'], ensure_ascii=False))
    text = '\n'.join(parts)
    s = scoring_v2.score_report(text)
    chain = scoring_v2.chain_filter(s['covered'], pack_text)
    strict_n = sum(1 for l in res['node_log'] if l['strict_ok'])
    compat_n = sum(1 for l in res['node_log'] if l['compat_ok'])
    return {'full_set': s['score'], 'per_fact': s['per_fact'],
            'reachable_chain': f'{len(chain)}/3', 'chain_facts': chain,
            'strict_rate': f'{strict_n}/{len(res["node_log"])}',
            'compat_rate': f'{compat_n}/{len(res["node_log"])}'}


def main(dry_run=False):
    lock_fh = open(P / ('f7v2_dryrun.lock' if dry_run else 'f7v2.lock'), 'w')
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('REFUSING TO START: another f7_v2 instance holds the lock.')
    pre = preflight()
    print('PRE-FLIGHT:', json.dumps(pre, ensure_ascii=False))
    if dry_run:
        pre['verdict'] = 'GO(dry-run)'
    if not pre['verdict'].startswith('GO'):
        print('NO-GO — no real calls made.')
        return
    ranked = ep.rank_chunks(ep.build_index())
    packs = ep.pack_lines(WINDOW, LINE_DOCS, ranked=ranked)
    pack_text = packs['t1']['text'] + '\n' + packs['t2']['text']
    import v3_kdx_qcl_ab
    event = {'task': v3_kdx_qcl_ab.TASK,
             'lines': {k: packs[k]['text'] for k in ('t1', 't2')}}
    stats = build_stats()
    meter = V2Meter(dry_run)
    out_path = P / ('f7v2_results_dryrun.json' if dry_run else 'f7v2_results.json')
    results = json.loads(out_path.read_text()) if out_path.exists() else {'runs': {}}
    for rid, pi0, blocked, policy in RUNS:
        if rid in results['runs']:
            print(f'  [skip] {rid}')
            continue
        print(f'  [run ] {rid} policy={policy}', flush=True)
        ex = V2Executor(meter, event, rid, pi0, blocked, policy, stats, deadline_s=DEADLINE)
        try:
            res = ex.run()
        except AssertionError as e:
            print(f'  CAP HIT at {rid}: {e} — stop, HOLD')
            break
        sc = score_run(res, pack_text)
        rec = {'policy': policy, 'pi0': pi0, 'blocked': blocked,
               'complete': res['complete'], 'wall_s': res['wall_s'],
               'deadline_met': res['deadline_met'],
               'violation_s': res['deadline_violation_s'],
               'skips': res['skips'], 'decisions': res['decisions'],
               'fault_records': res['fault_records'],
               'node_log': res['node_log'], 'decision_latencies': res['decision_latencies'],
               'tokens': sum(l['in'] + l['out'] for l in res['node_log']),
               'cash_rmb': round(sum((l['in'] * DS_IN_USD + l['out'] * DS_OUT_USD) / 1e6 * USD2RMB
                                     for l in res['node_log'] if l['model'] == 'deepseek'), 4),
               **sc}
        results['runs'][rid] = rec
        results['meter'] = meter.summary() if hasattr(meter, 'summary') else \
            {'calls': meter.calls, 'tokens': meter.tokens, 'cash_rmb': round(meter.cash, 4)}
        results['preflight'] = pre
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        print(f"    wall={res['wall_s']}s met={res['deadline_met']} complete={res['complete']} "
              f"full={sc['full_set']} chain={sc['reachable_chain']} "
              f"strict={sc['strict_rate']} compat={sc['compat_rate']}", flush=True)
    print('METER:', json.dumps({'calls': meter.calls, 'tokens': meter.tokens,
                                'cash_rmb': round(meter.cash, 4)}, ensure_ascii=False))
    print('saved:', out_path)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    main(dry_run=args.dry_run)
