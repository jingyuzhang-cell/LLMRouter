"""M1 acceptance tests for deadline_reward_v1.stub_engine — zero real calls.

Covers (VERIFICATION_PLAN mapping in brackets): Z1 zero-call sentinel +
stdlib-only import graph [Z1/L5-lite], socket-blocked execution [Z2],
production-mirrored batching order, T3-lite production-reference equivalence
for the NONE arm (first slice of T3a/T3b) [T3], per-task wall semantics
[B7], first-class switch records [B6 precursor], append-only TASK_LEDGER
integrity + torn-line loader [R-F7-lite], determinism [T2-lite], PRIORS
hygiene [V7-lite].

Production modules are imported ONLY by this test file, read-only, to
generate the independent reference trajectory (the sanctioned T3 pattern);
the engine itself imports stdlib only (asserted).

Run: cd /root/r3_own_pool && python3 -m deadline_reward_v1.test_stub_engine
"""
from __future__ import annotations

import ast
import contextlib
import json
import shutil
import socket as _socket_mod
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # repo checkouts anywhere
sys.path.insert(0, str(ROOT))

# Production reference modules (read-only imports, sanctioned by the T3
# pattern): imported HERE, before any socket patching, so their harmless
# stdlib import chains (urllib/ssl) load normally. The engine under test
# never imports them (asserted below).
from collab_scheduler_v1 import fault30_protocol as fp  # noqa: E402
from collab_scheduler_v1 import fault30_run as fr  # noqa: E402
from collab_scheduler_v1.predictor_v3 import V3Executor  # noqa: E402

from deadline_reward_v1.stub_engine import (  # noqa: E402
    InjectedClock, LedgerCorruptionError, StubEngine, StubModelServer,
    load_ledger)

HERE = Path(__file__).resolve().parent
PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
EVIDENCE_DIR = HERE / 'evidence'
RUNS_DIR = EVIDENCE_DIR / 'm1_runs'

BASE_ANSWERS = {
    ('e1', 'plain'): '{"facts": [{"value": 1.5, "evidence": "a"}]}',
    ('e2', 'plain'): '{"facts": [{"value": 2.5, "evidence": "b"}]}',
    ('r', 'plain'): '{"expression": "v0+v1"}',
    ('v', 'plain'): '{"value": 4.0}',
}


def make_tasks():
    def t(i, a, b):
        return dict(uid=f'm1t{i}', question=f'What is {a} + {b}?',
                    derivation=f'{a}+{b}', answer=a + b,
                    ctx_table=f'TABLE: | val | {a} |',
                    ctx_text=f'PASSAGES: value is {b}')
    return [t(0, 1.5, 2.5), t(1, 3.0, 4.0), t(2, 2.0, 6.0)]


@contextlib.contextmanager
def no_socket():
    def _raise(*_a, **_k):
        raise AssertionError('network access attempted (Z2)')
    saved = _socket_mod.socket
    _socket_mod.socket = _raise
    try:
        yield
    finally:
        _socket_mod.socket = saved


def calls_of(events):
    return [e for e in events if e['event'] == 'call']


def run_engine(dirname, tasks, node_models, *, seed='m1',
               profile_key=None, priors=PRIORS):
    server = StubModelServer(BASE_ANSWERS, priors, seed=seed)
    eng = StubEngine(RUNS_DIR / dirname, server, InjectedClock(), seed=seed,
                     profile_key=profile_key)
    summaries = eng.run_panel(tasks, node_models)
    events, torn = load_ledger(RUNS_DIR / dirname / 'TASK_LEDGER.jsonl')
    return server, summaries, events, torn


def main():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    checks = {}
    detail = {}

    tasks = make_tasks()

    # --- T3-lite: independent production reference, NONE arm -------------
    cid = 'DYNAMICDAG__HETEROGENEOUS__NONE__FRESH'
    topo, fam, z, nodes = fp.planned_models(cid)
    ref_ex = V3Executor(set(), BASE_ANSWERS)
    led = fp.Ledger()
    fr.eval_config(cid, ref_ex, led, tasks, {},
                   {t['uid']: t for t in tasks})
    ref_seq = [(c['node'], c['kind'], c['model'], c['key'].split(':')[-1])
               for c in ref_ex.call_log]

    server, summaries, events, torn = run_engine(
        't3ref', tasks, nodes, seed='t3ref', profile_key='v3_compat')
    m1_seq = [(c['node'], c['kind'], c['model'], c['task'])
              for c in calls_of(events)]
    checks['t3ref_global_order'] = m1_seq == ref_seq
    per_task_ok = True
    for t in tasks:
        uid = t['uid']
        ref_p = [s for s in ref_seq if s[3] == uid]
        m1_p = [s for s in m1_seq if s[3] == uid]
        per_task_ok = per_task_ok and ref_p == m1_p
    checks['t3ref_per_task_order'] = per_task_ok
    checks['t3ref_no_torn'] = not torn
    detail['t3ref'] = dict(n_ref=len(ref_seq), n_m1=len(m1_seq),
                           models=nodes)

    # --- batching order mirror (per-task models force real regrouping,
    # the shape M5's pi will produce) --------------------------------------
    t2 = tasks[:2]
    per_task_model = {'m1t0': {'e1': 'medium', 'e2': 'medium'},
                      'm1t1': {'e1': 'large', 'e2': 'medium'}}
    server2 = StubModelServer(BASE_ANSWERS, PRIORS, seed='batch')
    eng2 = StubEngine(RUNS_DIR / 'batching', server2, InjectedClock(),
                      seed='batch', profile_key='v3_compat')
    stage_jobs = [dict(task=t, node=nd, kind='plain',
                       model=per_task_model[t['uid']][nd])
                  for t in t2 for nd in ('e1', 'e2')]
    eng2._run_stage('A', stage_jobs)
    ev2, _ = load_ledger(RUNS_DIR / 'batching' / 'TASK_LEDGER.jsonl')
    got_order = [(c['node'], c['task']) for c in calls_of(ev2)]
    # sorted models {'large','medium'}: large group first -> t1.e1 jumps
    # ahead of the medium jobs that were listed before it.
    expected_order = [('e1', 'm1t1'), ('e1', 'm1t0'),
                      ('e2', 'm1t0'), ('e2', 'm1t1')]
    checks['batching_sorted_model_groups'] = got_order == expected_order

    # --- wall semantics (B7): single task, zero interleaving -------------
    single = tasks[:1]
    server3 = StubModelServer(BASE_ANSWERS, PRIORS, seed='wall')
    eng3 = StubEngine(RUNS_DIR / 'wall_single', server3, InjectedClock(),
                      seed='wall', profile_key='v3_compat')
    eng3.run_panel(single, nodes)
    ev3, _ = load_ledger(RUNS_DIR / 'wall_single' / 'TASK_LEDGER.jsonl')
    s3 = [e for e in ev3 if e['event'] == 'task_summary'][0]
    switches3 = [e for e in ev3 if e['event'] == 'switch']
    checks['wall_equals_service_plus_switch'] = (
        abs(s3['wall_inclusive_s']
            - s3['service_sum_s'] - s3['switch_sum_s']) < 1e-9)
    # cold start (None->large, start cost only) + large->medium + medium->coder
    sw_pairs = [(e['from'], e['to']) for e in switches3]
    checks['switch_count_and_pairs'] = (
        len(switches3) == 3 and sw_pairs == [(None, 'large'),
                                             ('large', 'medium'),
                                             ('medium', 'coder')]
        and s3['switch_count'] == len(switches3)
        and abs(s3['switch_sum_s'] - 3.0 - (0.5 + 2.0) - (0.5 + 2.5)) < 1e-9)
    first_call = calls_of(ev3)[0]
    checks['cold_start_charged_once'] = (
        first_call['switch_before'] == 1
        and switches3[0]['t_end'] == first_call['t_start'])

    # --- wall inequality under interleaving (B7 direction) ---------------
    s_t3 = {e['task']: e for e in events
            if e['event'] == 'task_summary'}
    checks['wall_ge_service_interleaved'] = all(
        s['wall_inclusive_s'] >= s['service_sum_s'] - 1e-9
        for s in s_t3.values())

    # --- ledger integrity + replay ---------------------------------------
    required = {'event', 'key', 'stage', 'node', 'kind', 'model', 'task',
                'attempt', 'answer_sha256', 'answer', 'usage', 'latency_s',
                't_start', 't_end', 'switch_before'}
    checks['ledger_call_fields_complete'] = all(
        required <= set(c.keys()) for c in calls_of(events))
    checks['ledger_meta_first'] = events[0]['event'] == 'meta' and \
        events[0]['zero_real_calls'] is True
    replay_ok = True
    for c in calls_of(events):
        if abs((c['t_end'] - c['t_start']) - c['latency_s']) > 1e-9:
            replay_ok = False
    checks['ledger_replay_latency'] = replay_ok

    # --- determinism (T2-lite) -------------------------------------------
    run_engine('det_a', tasks, nodes, seed='det', profile_key='v3_compat')
    run_engine('det_b', tasks, nodes, seed='det', profile_key='v3_compat')
    a = (RUNS_DIR / 'det_a' / 'TASK_LEDGER.jsonl').read_bytes()
    b = (RUNS_DIR / 'det_b' / 'TASK_LEDGER.jsonl').read_bytes()
    checks['determinism_bitwise'] = a == b
    checks['seed_changes_stream'] = (
        a != (RUNS_DIR / 't3ref' / 'TASK_LEDGER.jsonl').read_bytes())

    # --- torn-line loader (R-F7-lite) + M2 hardening regression ---------
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'T.jsonl'
        p.write_text('{"event": "meta"}\n{"event": "call"}\n'
                     '{"event": "call", "key": "tor')
        evs, torn_flag = load_ledger(p)
        checks['torn_line_flagged'] = (
            torn_flag is True and len(evs) == 2)
        # operator ruling: a corrupted MIDDLE line must REJECT the ledger
        p2 = Path(td) / 'T2.jsonl'
        p2.write_text('{"event": "meta"}\n{"event": "call" "corrupt}\n'
                      '{"event": "call"}\n')
        try:
            load_ledger(p2)
            checks['mid_corruption_rejected'] = False
        except LedgerCorruptionError:
            checks['mid_corruption_rejected'] = True
        # corrupt LAST line WITH trailing newline is not a torn write
        p3 = Path(td) / 'T3.jsonl'
        p3.write_text('{"event": "meta"}\n{"bad": }\n')
        try:
            load_ledger(p3)
            checks['corrupt_tail_with_newline_rejected'] = False
        except LedgerCorruptionError:
            checks['corrupt_tail_with_newline_rejected'] = True

    # --- Z1 sentinel + stdlib-only import graph --------------------------
    total_calls = len(calls_of(events)) + len(calls_of(ev2)) + \
        len(calls_of(ev3))
    invocations = server.invocations + server2.invocations + server3.invocations
    checks['z1_sentinel_engine_only'] = invocations == total_calls
    allowed = {'__future__', 'json', 'random', 'hashlib', 'dataclasses',
               'pathlib', 'typing', 'os'}
    tree = ast.parse((HERE / 'stub_engine.py').read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split('.')[0])
    checks['engine_stdlib_only'] = imported <= allowed
    detail['engine_imports'] = sorted(imported)

    # --- PRIORS hygiene (V7-lite) ----------------------------------------
    entries = list(PRIORS['profiles'].values()) + [PRIORS['switch'],
                                                    PRIORS['v3_compat']]
    checks['priors_all_synthetic'] = all(
        e.get('synthetic') is True for e in entries)
    checks['priors_versioned_sourced'] = bool(
        PRIORS.get('version') and PRIORS.get('source')
        and PRIORS.get('class') == 'stub_test_only')

    # --- existing-ledger refusal (no silent resume) ----------------------
    try:
        StubEngine(RUNS_DIR / 't3ref', StubModelServer(BASE_ANSWERS,
                                                       PRIORS),
                   InjectedClock())
        checks['ledger_refuses_resume'] = False
    except ValueError:
        checks['ledger_refuses_resume'] = True

    all_pass = all(checks.values())
    evidence = dict(
        milestone='M1', checks=checks, all_pass=all_pass,
        zero_model_calls=True, detail=detail,
        priors_sha256=__import__('hashlib').sha256(
            (HERE / 'PRIORS_STUB_V1.json').read_bytes()).hexdigest(),
        production_reference=dict(
            source='collab_scheduler_v1.fault30_run.eval_config + '
                   'predictor_v3.V3Executor (read-only imports)',
            config=cid, arm='Z=NONE planned stages only',
            n_calls=len(ref_seq)))
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / 'M1_EVIDENCE.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'\n{sum(checks.values())}/{len(checks)} checks; '
          f'zero_model_calls=true; '
          f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')
    return 0 if all_pass else 2


if __name__ == '__main__':
    with no_socket():
        raise SystemExit(main())
