"""F7 minimal discrimination experiment — AUTHORIZED 2026-10-14 (four frozen runs).

Runs (KDX DEV event, v2 pairing freeze, 10000c global evidence window = 5000c/line):
  R1 B3p clean        : static optimum mixed, no fault
  R2 B3p F7 no-recover: (t1,deepseek) blocked, static policy, honest degradation
  R3 S5+Cap F7        : fixed LOCAL recovery scope + per-node Q/C/L table lookup
  R4 S6 F7            : joint (Z,R,pi) re-decision via JS.choose

Authorization envelope (fresh; prior incidents' spend is NOT available quota):
  <=30 new real calls | <=160,000 actual tokens | <= ¥0.12 new cash (off-peak
  DeepSeek pricing $0.15/M in-miss, $0.60/M out; RMB = USD x 7.1) | 90s/run
  deadline | NO auto-retry, NO added conditions.

Execution requirements implemented here:
  1. GO/NO-GO pre-flight: worst-case reservation (est_in + max_tokens per planned
     call; worst-case cash at off-peak rates) must fit ALL envelopes, else exit
     with zero calls.
  2. Fresh persistent ledger f7min_ledger.jsonl (unified, crash-safe append).
  3. Per-run record: pre-fault state (pi0/spent/elapsed), cache/completed nodes at
     fault, fault kind, recovery Z/R/pi, executed nodes+models.
  4. S5+Cap and S6 share identical info (capability_table_v3), budget guard,
     deadline and model availability (same blocked set).
  5. REAL parallel executor (ThreadPoolExecutor t1||t2, t3||t4); wall clock is
     measured, never predicted-from-fake.
  6. Raw response persisted BEFORE parse/score/account; resume reuses persisted
     (run_id,node,model) responses — an abnormal exit never re-pays a call.
  7. F7 = service-unavailability fault on the (node,model) binding: the call is
     never issued (zero cost/latency); identical semantics for R2/R3/R4.
  8. T1 = KDX 4-fact v1 set on the deliverable; RF4 reported separately (the
     frozen 10000c official retrieval does not reach its anchor chunk).
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR, fenced_json, norm
from legacy.scheduler_v4_20261022.src import joint_scheduler as JS  # historical reproduction only
from merge_facts import merge_facts
from e4_controlled_experiment import (ParallelDAGExecutor, Fault, MODEL_NODES,
                                      parse_node, build_stats, deliverable)
import evidence_packer as ep

P = PILOT_DIR
CAP_CALLS, CAP_TOKENS, CAP_CASH = 30, 160_000, 0.12
DEADLINE_S = 90.0
RUN_BUDGET_TOKENS = 40_000
USD_TO_RMB = 7.1
# OFF-PEAK DeepSeek official prices (USD/1M): in-miss 0.15, out 0.60.
# The run is scheduled inside the off-peak UTC window; the gate REFUSES to
# start inside a peak window (worst-case cash would exceed the authorization).
DS_IN_USD, DS_OUT_USD = 0.15, 0.60
QW_IN_USD, QW_OUT_USD = 0.8, 2.0
GLM_ENDPOINT = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
GLM_MODELS = {'glm53': 'GLM-5.3', 'glm53flash': 'GLM-5.3-Flash'}
OPENAI_MODELS = {'deepseek': ('deepseek-flash', 'https://api.deepseek.com', 'DEEPSEEK_API_KEY'),
                 'qwen': ('qwen-plus', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'DASHSCOPE_API_KEY')}
OUT_CAPS = {'glm53': {'extract': 2048, 'mid': 1536, 'report': 1792},
            'glm53flash': {'extract': 2048, 'mid': 1536, 'report': 1792},
            'deepseek': {'extract': 2048, 'mid': 1536, 'report': 1792},
            'qwen': {'extract': 1536, 'mid': 1024, 'report': 1536}}
LINE_DOCS = {'t1': ['kdx_penalty_2020', 'kdx_notice_2019', 'kdx_notice_2020'],
             't2': ['kdx_inquiry_2018', 'kdx_inquiry_2019']}
WINDOW = 10000
F7 = [('t1', 'deepseek')]
B3P = {'t1': 'deepseek', 't2': 'deepseek', 't3': 'glm53', 't4': 'glm53',
       't5': 'deepseek', 't6': 'glm53'}
POOL_ORDER = ['glm53', 'glm53flash', 'deepseek', 'qwen']


def peak_now():
    """DeepSeek peak windows (weekdays): 01:00-04:00 and 06:00-10:00 UTC."""
    import datetime
    u = datetime.datetime.now(datetime.timezone.utc)
    if u.weekday() >= 5:
        return False
    return 1 <= u.hour < 4 or 6 <= u.hour < 10


# ---------------- fresh meter: persist-first, resume, off-peak cash ----------------

class F7Meter:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.lock = threading.Lock()
        self.calls = 0
        self.tokens = 0
        self.cash = 0.0
        self.ledger_path = P / ('f7min_ledger_dryrun.jsonl' if dry_run else 'f7min_ledger.jsonl')
        self.resp_path = P / ('f7min_resp_dryrun.jsonl' if dry_run else 'f7min_resp.jsonl')
        # resume: reload persisted responses (never re-pay a completed call)
        self.persisted = {}
        if not dry_run and self.resp_path.exists():
            for line in self.resp_path.read_text().splitlines():
                if line.strip():
                    d = json.loads(line)
                    self.persisted[(d['run_id'], d['node'], d['model'])] = d['text']
        if not dry_run:
            from e4_controlled_experiment import load_env
            load_env()

    def _check(self, extra_tokens=0):
        assert self.calls < CAP_CALLS, f'CALL CAP {CAP_CALLS}'
        assert self.tokens + extra_tokens <= CAP_TOKENS, f'TOKEN CAP {CAP_TOKENS}'
        assert self.cash <= CAP_CASH, f'CASH CAP {CAP_CASH}'

    def _glm(self, alias, system, user, max_tokens):
        import urllib.request
        from e4_controlled_experiment import _glm_key
        body = {'model': GLM_MODELS[alias], 'max_tokens': max_tokens,
                'thinking': {'type': 'disabled'},
                'system': system, 'messages': [{'role': 'user', 'content': user}]}
        req = urllib.request.Request(GLM_ENDPOINT, data=json.dumps(body).encode(), method='POST')
        key = _glm_key()
        req.add_header('content-type', 'application/json')
        req.add_header('x-api-key', key)
        req.add_header('authorization', 'Bearer ' + key)
        req.add_header('anthropic-version', '2023-06-01')
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode())
        return {'text': ''.join(b.get('text', '') for b in d.get('content', []) if b.get('type') == 'text'),
                'in': d['usage']['input_tokens'], 'out': d['usage']['output_tokens'],
                'stop': d.get('stop_reason'), 'lat': round(time.monotonic() - t0, 2)}

    def _openai(self, alias, system, user, max_tokens):
        import os
        import urllib.request
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
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode())
        content = d['choices'][0]['message'].get('content', '')
        if isinstance(content, list):
            content = ''.join(c.get('text', '') for c in content if isinstance(c, dict))
        u = d['usage']
        return {'text': content, 'in': u.get('prompt_tokens', u.get('input_tokens', 0)),
                'out': u.get('completion_tokens', u.get('output_tokens', 0)),
                'stop': d['choices'][0].get('finish_reason', ''), 'lat': round(time.monotonic() - t0, 2)}

    def call(self, run_id, node, alias, system, user, attempt=1):
        from e4_controlled_experiment import NODE_KIND
        kind = NODE_KIND[node]
        max_tokens = OUT_CAPS[alias][kind]
        cached = self.persisted.get((run_id, node, alias))
        if cached is not None:
            # resume path: completed call already paid & persisted — reuse, zero cost
            ok, value = parse_node(node, cached)
            return {'text': cached, 'in': 0, 'out': 0, 'stop': 'reused', 'lat': 0.0,
                    'cached': True, 'ok': ok, 'value': value, 'max_tokens': max_tokens}
        est = int((len(system) + len(user)) * 0.7) + max_tokens
        with self.lock:
            self._check(est)
        if self.dry_run:
            canned = {'t1': '{"facts":[{"fact_key":"a","value":"60万元罚款","doc_id":"kdx_penalty_2020","quote":"60万元罚款"}]}',
                      't2': '{"facts":[{"fact_key":"b","value":"2015年至2018年年度报告存在虚假记载","doc_id":"kdx_penalty_2020","quote":"虚假记载"}]}',
                      't3': '{"timeline":[{"date":"2019-01-01","event":"e","doc_id":"kdx_penalty_2020"}]}',
                      't4': '{"entity_facts":[{"fact_key":"c","value":"v","doc_id":"kdx_penalty_2020"}]}',
                      't5': '{"verdicts":[{"fact":"f","verdict":"SUPPORTED","doc_id":"kdx_penalty_2020"}]}',
                      't6': '{"report":"康得新2015年至2018年年度报告存在虚假记载，证监会处以60万元罚款并采取10年证券市场禁入措施。本报告为dry-run虚构文本，仅用于管线验证，长度超过一百字以满足t6契约最小长度校验要求，避免契约失败影响流程验证。"}'}
            raw = {'text': canned[node], 'in': int((len(system) + len(user)) * 0.7) // 2,
                   'out': 300, 'stop': 'end_turn', 'lat': 0.5}
        elif alias in GLM_MODELS:
            raw = self._glm(alias, system, user, max_tokens)
        else:
            raw = self._openai(alias, system, user, max_tokens)
        if alias == 'deepseek':
            cash = (raw['in'] * DS_IN_USD + raw['out'] * DS_OUT_USD) / 1e6 * USD_TO_RMB
        elif alias == 'qwen':
            cash = (raw['in'] * QW_IN_USD + raw['out'] * QW_OUT_USD) / 1e6 * USD_TO_RMB
        else:
            cash = 0.0
        # requirement 6: PERSIST RAW RESPONSE FIRST, then account
        if not self.dry_run:
            with self.lock:
                with open(self.resp_path, 'a') as f:
                    f.write(json.dumps({'call_id': self.calls + 1, 'run_id': run_id,
                                        'node': node, 'model': alias, 'text': raw['text']},
                                       ensure_ascii=False) + '\n')
        rec = {'call_id': self.calls + 1, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'run_id': run_id, 'node': node, 'model': alias, 'max_tokens': max_tokens,
               'prompt_chars': len(system) + len(user),
               'in': raw['in'], 'out': raw['out'], 'stop': raw['stop'],
               'truncated': raw['stop'] in ('length', 'max_tokens'),
               'lat': raw['lat'], 'cash_rmb': round(cash, 6)}
        with self.lock:
            self.calls += 1
            self.tokens += raw['in'] + raw['out']
            self.cash += cash
            self._check()
            if not self.dry_run:
                with open(self.ledger_path, 'a') as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return {**raw, 'cash': cash, 'cached': False, 'max_tokens': max_tokens}

    def summary(self):
        return {'calls': self.calls, 'tokens': self.tokens, 'cash_rmb': round(self.cash, 4),
                'caps': {'calls': CAP_CALLS, 'tokens': CAP_TOKENS, 'cash_rmb': CAP_CASH}}


# ---------------- executor subclass: no-retry, richer records, policies ----------------

class F7Executor(ParallelDAGExecutor):
    def __init__(self, meter, event, run_id, pi0, blocked, policy, stats):
        super().__init__(meter, event, run_id, pi0, blocked, dynamic=False, stats=stats)
        self.policy = policy  # 'static' | 's5cap' | 's6'
        self.fault_records = []
        self.prefault_snapshot = None

    def _run_node(self, node):
        alias = self.pi.get(node, 'glm53')
        try:
            ok, value = self._attempt(node, alias)
            if ok:
                self.outputs[node] = value
                self.done.add(node)
                return None
            reason = 'contract_fail'
        except Fault as f:
            reason = str(f)  # service_unavailable on the (node,model) binding
        except Exception as e:
            reason = f'transport_error:{type(e).__name__}'  # NO auto-retry (authorized terms)
        return (node, alias, reason)

    def _quality_proxy(self, node, alias):
        cell = self.stats.get((node, alias))
        return cell[2] if cell else 0.0

    def _recover(self, fault_node, failed_alias):
        # requirement 3: record pre-fault state
        self.prefault_snapshot = {'fault': (fault_node, failed_alias),
                                  'fault_kind': 'service_unavailable_injected',
                                  'spent_tokens': sum(l['in'] + l['out'] for l in self.node_log),
                                  'elapsed_s': round(self.elapsed(), 2),
                                  'completed_nodes': sorted(self.done),
                                  'pi_at_fault': dict(self.pi)}
        spent = self.prefault_snapshot['spent_tokens']
        if self.policy == 's6':
            action, audit = JS.choose(fault_node, MODEL_NODES + ['m'],
                                      {'t1': ['m'], 't2': ['m'], 'm': ['t3', 't4'],
                                       't3': ['t5'], 't4': ['t5'], 't5': ['t6']},
                                      tuple(POOL_ORDER), self.stats, spent,
                                      RUN_BUDGET_TOKENS, self.elapsed(), DEADLINE_S,
                                      q_min=0.05, blocked=self.blocked | {(fault_node, failed_alias)})
            Z, R, pi = action
            self.decisions.append({'policy': 's6', 'fault': (fault_node, failed_alias),
                                   'Z': Z, 'R': sorted(n for n in R if n in MODEL_NODES),
                                   'pi_changes': {k: pi[k] for k in sorted(pi)
                                                  if k in MODEL_NODES and pi[k] != self.pi.get(k)},
                                   'n_feasible': sum(1 for a in audit if a['feasible']),
                                   'n_candidates': len(audit)})
            if Z == 'NONE':
                return
            self.pi.update({k: v for k, v in pi.items() if k in MODEL_NODES})
        else:  # s5cap: fixed LOCAL scope + per-node table lookup (same info as S6)
            R = ({fault_node} | JS.descendants(fault_node,
                  {'t1': ['m'], 't2': ['m'], 'm': ['t3', 't4'], 't3': ['t5'],
                   't4': ['t5'], 't5': ['t6']})) & set(MODEL_NODES)
            pi_changes = {}
            for n in sorted(R):
                cands = [m for m in POOL_ORDER if (n, m) not in self.blocked]
                best = max(cands, key=lambda m: (self._quality_proxy(n, m),
                                                 -POOL_ORDER.index(m)))
                if best != self.pi.get(n):
                    pi_changes[n] = best
            self.pi.update(pi_changes)
            self.decisions.append({'policy': 's5cap', 'fault': (fault_node, failed_alias),
                                   'Z': 'LOCAL_fixed', 'R': sorted(R), 'pi_changes': pi_changes})
        # re-execute the fault node itself NOW (completed nodes untouched: cache legality)
        alias2 = self.pi.get(fault_node, 'glm53')
        ok, value = self._attempt(fault_node, alias2)
        if ok:
            self.outputs[fault_node] = value
            self.done.add(fault_node)

    def run(self):
        failures = []
        for layer in [['t1', 't2'], ['m'], ['t3', 't4'], ['t5'], ['t6']]:
            if layer == ['m']:
                f1, f2 = self.outputs.get('t1') or [], self.outputs.get('t2') or []
                if f1 or f2:
                    self.outputs['m'] = merge_facts([f1, f2], ['t1', 't2'])
                self.done.add('m')
                continue
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as ex:
                futs = [ex.submit(self._run_node, n) for n in layer]
                failures += [f.result() for f in futs if f.result() is not None]
            for tup in list(failures):
                node, alias, reason = tup
                if node in layer:
                    failures.remove(tup)
                    if self.policy != 'static':
                        self.fault_records.append({'node': node, 'model': alias,
                                                   'reason': reason,
                                                   'at_s': round(self.elapsed(), 2)})
                        self._recover(node, alias)
                    else:
                        self.fault_records.append({'node': node, 'model': alias,
                                                   'reason': reason,
                                                   'policy': 'static_no_recovery'})
        return {'complete': all(n in self.outputs for n in MODEL_NODES),
                'wall_s': round(self.elapsed(), 2),
                'outputs': {k: self.outputs.get(k) for k in MODEL_NODES},
                'node_log': self.node_log, 'decisions': self.decisions,
                'fault_records': self.fault_records,
                'prefault_snapshot': self.prefault_snapshot}


# ---------------- GO/NO-GO pre-flight (worst-case reservation) ----------------

def planned_calls(packs):
    """Planned (run, node, model, est_in, max_tokens) with the frozen assignments."""
    from e4_controlled_experiment import NODE_KIND
    extract_in = {n: int(len(packs[n]['text']) * 0.7) + 120 for n in ('t1', 't2')}
    mid_in, rep_in = 3000, 1300
    runs = [
        ('R1_B3p_clean', B3P, []),
        ('R2_B3p_F7', B3P, F7),
        ('R3_S5Cap_F7', dict(B3P, t1='glm53'), F7),   # S5+Cap lookup under F7 -> glm53
        ('R4_S6_F7', dict(B3P, t1='glm53'), F7),      # S6 joint (E3 replay) -> glm53
    ]
    plan = []
    for run_id, pi, blocked in runs:
        for n in MODEL_NODES:
            if (n, pi[n]) in blocked:
                continue
            est_in = extract_in[n] if n in ('t1', 't2') else (rep_in if n == 't6' else mid_in)
            plan.append((run_id, n, pi[n], est_in, OUT_CAPS[pi[n]][NODE_KIND[n]]))
    return plan


def preflight(packs):
    plan = planned_calls(packs)
    n_calls = len(plan)
    worst_tokens = sum(est + cap for _, _, _, est, cap in plan)
    worst_cash = 0.0
    for _, node, m, est, cap in plan:
        if m == 'deepseek':
            worst_cash += (est * DS_IN_USD + cap * DS_OUT_USD) / 1e6 * USD_TO_RMB
        elif m == 'qwen':
            worst_cash += (est * QW_IN_USD + cap * QW_OUT_USD) / 1e6 * USD_TO_RMB
    ok_calls = n_calls <= CAP_CALLS
    ok_tok = worst_tokens <= CAP_TOKENS
    ok_cash = worst_cash <= CAP_CASH
    ok_window = not peak_now() or '--force-peak' in sys.argv
    verdict = 'GO' if (ok_calls and ok_tok and ok_cash and ok_window) else 'NO-GO'
    report = {'planned_calls': n_calls, 'worst_case_tokens': worst_tokens,
              'worst_case_cash_rmb': round(worst_cash, 4),
              'calls_ok': ok_calls, 'tokens_ok': ok_tok, 'cash_ok': ok_cash,
              'offpeak_window_ok': ok_window, 'peak_now': peak_now(), 'verdict': verdict}
    return report, plan


# ---------------- scoring ----------------

def score_t1(deliverable_text):
    refs = json.loads((P / 'kdx_st_reference_facts.json').read_text())['facts']
    kdx = [f for f in refs if f['event_id'].startswith('kdx')]
    hay = norm(deliverable_text)
    hits = [f['fact_id'] for f in kdx if norm(f['anchor_quote']) in hay
            or norm(str(f.get('normalized_value', ''))) in hay]
    return hits, [f['fact_id'] for f in kdx if f['fact_id'] not in hits]


def retrieval_reachable():
    """Which T1 facts the frozen 10000c official pack can physically reach."""
    ranked = ep.rank_chunks(ep.build_index())
    pack = ep.pack_global(WINDOW // 2, doc_ids=LINE_DOCS['t1'], ranked=ranked)
    pack2 = ep.pack_global(WINDOW // 2, doc_ids=LINE_DOCS['t2'], ranked=ranked)
    refs = json.loads((P / 'kdx_st_reference_facts.json').read_text())['facts']
    hay = norm(pack['text'] + pack2['text'])
    return [f['fact_id'] for f in refs if f['event_id'].startswith('kdx')
            and norm(f['anchor_quote']) in hay]


# ---------------- main ----------------

def main(dry_run=False):
    # OS-level exclusive lock (post-incident rule): never two meters on one envelope
    import fcntl
    lock_fh = open(P / ('f7min_dryrun.lock' if dry_run else 'f7min.lock'), 'w')
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('REFUSING TO START: another f7_min instance holds the lock.')
    out_path = P / ('f7min_results_dryrun.json' if dry_run else 'f7min_results.json')
    packs = ep.pack_lines(WINDOW, LINE_DOCS)
    reachable = retrieval_reachable()
    event = {'task': __import__('v3_kdx_qcl_ab').TASK,
             'lines': {k: packs[k]['text'] for k in ('t1', 't2')}}
    pre, plan = preflight(packs)
    print('PRE-FLIGHT:', json.dumps(pre, ensure_ascii=False))
    print('retrieval-reachable T1 facts at 10000c:', reachable)
    if dry_run:
        pre['verdict'] = 'GO(dry-run)'  # dry run makes no real calls
    if pre['verdict'] != 'GO' and not pre['verdict'].startswith('GO'):
        print('NO-GO: refusing to make real calls. Envelope or time-window check failed.')
        out_path.write_text(json.dumps({'preflight': pre, 'runs': {}}, ensure_ascii=False, indent=1))
        return

    meter = F7Meter(dry_run)
    stats = build_stats()
    results = json.loads(out_path.read_text()) if out_path.exists() else {'runs': {}}
    runs = [
        ('R1_B3p_clean', B3P, [], 'static'),
        ('R2_B3p_F7', B3P, F7, 'static'),
        ('R3_S5Cap_F7', dict(B3P, t1='deepseek'), F7, 's5cap'),  # starts from B3'; recovery fires
        ('R4_S6_F7', dict(B3P, t1='deepseek'), F7, 's6'),
    ]
    for run_id, pi0, blocked, policy in runs:
        if run_id in results['runs']:
            print(f'  [skip] {run_id} already recorded')
            continue
        print(f'  [run ] {run_id} policy={policy} blocked={blocked}', flush=True)
        ex = F7Executor(meter, event, run_id, pi0, blocked, policy, stats)
        try:
            res = ex.run()
        except AssertionError as e:
            print(f'  CAP HIT during {run_id}: {e} — stopping, HOLD')
            break
        hits, missing = score_t1(deliverable(res))
        run_tokens = sum(l['in'] + l['out'] for l in res['node_log'])
        rec = {'policy': policy, 'pi0': pi0, 'blocked': blocked,
               'complete': res['complete'], 'wall_s': res['wall_s'],
               'deadline_met': res['wall_s'] <= DEADLINE_S,
               't1_covered': hits, 't1_score': len(hits), 't1_missing': missing,
               'tokens': run_tokens,
               'cash_rmb': round(sum((l['in'] * DS_IN_USD + l['out'] * DS_OUT_USD) / 1e6 * USD_TO_RMB
                                     for l in res['node_log'] if l['model'] == 'deepseek'), 4),
               'node_log': res['node_log'], 'decisions': res['decisions'],
               'fault_records': res['fault_records'],
               'prefault_snapshot': res['prefault_snapshot'],
               'facts': {'t1': len(res['outputs'].get('t1') or []),
                         't2': len(res['outputs'].get('t2') or []),
                         't5': len(res['outputs'].get('t5') or [])}}
        results['runs'][run_id] = rec
        results['preflight'] = pre
        results['meter'] = meter.summary()
        results['retrieval_reachable_t1'] = reachable
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        print(f"    wall={res['wall_s']}s T1={len(hits)}/4 tokens={run_tokens} "
              f"complete={res['complete']}", flush=True)
    print('\nMETER:', json.dumps(meter.summary(), ensure_ascii=False))
    print('saved:', out_path)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    main(dry_run=args.dry_run)
