"""NET-BENEFIT formal executor: 8 arms x 4 states x 50 frozen tasks.

Implements NET_BENEFIT_FREEZE.json exactly. Two fault protocols:
  mechanism    node faults map onto the single call for A/A' (controlled
               comparison of the recovery MECHANISM)
  competitive  faults keyed (task, interaction_kind, reference_model); a
               strategy is affected only when it actually calls that triple
               (deployment-like exposure; inherently asymmetric, reported)

Six attribution arms are FIXED; V2 candidate arms never substitute into them.
Clean state is protocol-shared (identical by construction): executed once,
referenced by both families.

Cost semantics (dual track, never mixed):
  logical  every planned call's source-record tokens (cache hits included)
  physical only new requests this validation actually issues

Gating: default is a zero-request structural dry-run with a stub backend.
Real execution requires --execute AND env P1B_NETBENEFIT_EXECUTE=1 AND the
freeze-file SHA256 bound in an admission record. Failed integrity checks stop
all model calls (rule 8 of the master task book).

Resume: completed (protocol, arm, state) cells are skipped; the prompt cache
is re-seeded from every prior run's TRAJECTORY.jsonl so a restart never
re-pays for calls a crashed attempt already made.

Run:  python3 -m collab_scheduler_v1.joint_search_v1.netbenefit_runner           # stub
      P1B_NETBENEFIT_EXECUTE=1 python3 -m ...netbenefit_runner --execute       # real
"""
import argparse
import copy
import hashlib
import json
import os
import sys
import time
import types
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

from collab_scheduler_v1 import fault30_run as fr
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import (
    Budget, StopRun, append)
from collab_scheduler_v1.joint_search_v1.evaluator import (
    MeteredExecutor, _evaluate, detected_failure)
from collab_scheduler_v1.joint_search_v1.scoring_contract_final import score_v21
from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (
    contract_v2_gold, load_native_answers)

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'
RUNROOT = OUT / 'netbenefit_runs'
FREEZE_PATH = OUT / 'NET_BENEFIT_FREEZE.json'

CACHE_SCOPE = 'netbenefit'          # validation-wide cache scope (frozen)
DE_ARMS = ('D_dynamic_local', 'E_dynamic_full')
DAG_ARMS = ('B_same_model_dag', 'C_static_hetero', 'D_dynamic_local',
            'E_dynamic_full', 'V2_static', 'V2_dynamic')
PROTOCOLS = ('mechanism', 'competitive')
STATES = ('clean', 'fault10', 'fault20', 'fault30')

# Cell order: clean cache first, D/E before remaining fault cells so the D/E
# reservation can never be starved, V2 candidates last (never displace the
# six attribution arms).
CELL_ORDER = (
    [('mechanism', a, 'clean') for a in
     ('A_single', 'A_single_cross_fallback', 'B_same_model_dag', 'C_static_hetero')]
    + [('mechanism', a, s) for s in ('clean', 'fault10', 'fault20', 'fault30')
       for a in DE_ARMS]
    + [('mechanism', a, s) for s in ('fault10', 'fault20', 'fault30')
       for a in ('B_same_model_dag', 'C_static_hetero')]
    + [('mechanism', a, s) for s in ('fault10', 'fault20', 'fault30')
       for a in ('A_single', 'A_single_cross_fallback')]
    + [('mechanism', a, s) for a in ('V2_static', 'V2_dynamic')
       for s in ('clean', 'fault10', 'fault20', 'fault30')]
    + [('competitive', a, s) for a in
       ('A_single', 'A_single_cross_fallback', 'B_same_model_dag', 'C_static_hetero')
       for s in ('fault10', 'fault20', 'fault30')]
    + [('competitive', a, s) for a in DE_ARMS
       for s in ('fault10', 'fault20', 'fault30')]
    + [('competitive', a, s) for a in ('V2_static', 'V2_dynamic')
       for s in ('fault10', 'fault20', 'fault30')]
)


def stub_dispatch(model, prompt):
    """Zero-request structural backend; keyword-routed canned answers."""
    low = prompt.lower()
    if 'arithmetic reasoning' in low:
        return dict(status='delivered', answer='{"expression": "v0+v1"}',
                    usage=dict(prompt_tokens=60, completion_tokens=40,
                               total_tokens=100))
    if 'verifying' in low:
        return dict(status='delivered', answer='{"value": 4.0}',
                    usage=dict(prompt_tokens=60, completion_tokens=40,
                               total_tokens=100))
    if 'answer the financial question' in low:
        return dict(status='delivered', answer='{"answer": 4.0}',
                    usage=dict(prompt_tokens=80, completion_tokens=20,
                               total_tokens=100))
    return dict(status='delivered',
                answer='{"facts": [{"value": 1.5, "evidence": "a"},'
                       ' {"value": 2.5, "evidence": "b"}]}',
                usage=dict(prompt_tokens=60, completion_tokens=40,
                           total_tokens=100))


class NBExecutor(MeteredExecutor):
    """Validation-wide cache scope; cells labeled via cid for ledgers."""

    def seed_from_trajectories(self, run_dirs):
        """Durable cache across restarts. TRAJECTORY records are the clean
        source responses (answer replacement only ever touched WORKFLOW and
        by_key views), so seeding from them never persists a corrupted view."""
        n = 0
        for d in run_dirs:
            traj = Path(d) / 'TRAJECTORY.jsonl'
            if not traj.exists():
                continue
            for line in traj.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                ident = tuple(rec['cache_identity'])
                if ident not in self.cache and rec.get('response', {}).get('status') == 'delivered':
                    self.cache[ident] = dict(event_id=rec['event_id'],
                                             response=rec['response'])
                    n += 1
        return n


def load_freeze():
    freeze = json.loads(FREEZE_PATH.read_text())
    from static_dag_v0.multidag_dynamic import hybrid_pool, ctx_table, ctx_text
    pool = {t['uid']: t for t in hybrid_pool()}
    tasks = []
    for entry in freeze['tasks']:
        raw = pool.get(entry['uid'])
        if raw is None:
            raise ValueError('Frozen task not in hybrid_pool: ' + entry['uid'])
        t = dict(raw)
        t['ctx_table'] = ctx_table(raw['para'])
        t['ctx_text'] = ctx_text(raw['para'])
        payload = {k: t.get(k) for k in
                   ('uid', 'question', 'ctx_table', 'ctx_text', 'derivation', 'answer')}
        digest = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if digest != entry['content_sha256']:
            raise ValueError('Content hash mismatch: ' + entry['uid'])
        tasks.append(t)
    return freeze, tasks


def v21_gold_map(tasks):
    nat = load_native_answers()
    out = {}
    for t in tasks:
        n = nat.get(t['uid'], {})
        g = contract_v2_gold(n.get('native_answer'), n.get('native_scale'),
                             n.get('raw_derivation', t.get('derivation', '')))
        out[t['uid']] = dict(gold=g.get('gold', t.get('answer')),
                             source=g.get('gold_source', 'v1_fallback'))
    return out


def mechanism_registry(freeze, arm_cfg, state, tasks):
    """uid -> (node_for_registry, failing). For DAG arms the faulted node uses
    the arm's own binding; for single arms every drawn node maps to the single
    call (mechanism protocol: fault ALWAYS exposes in A/A')."""
    faults = freeze['states'][state]['mechanism']['faults']
    out = {}
    for uid, (node, failing) in faults.items():
        model = (arm_cfg['model'] if arm_cfg['kind'] == 'single'
                 else arm_cfg['X'][node])
        out[uid] = (node, model, failing)
    return out


def competitive_registry(freeze, arm_cfg, state, tasks):
    """uid -> (kind, reference_model, failing); exposes only on strategies
    whose execution actually contains that (task, kind, model) triple.
    DAG-interaction faults (e1/e2/r/v) never touch the single call: A/A' call
    with node='single', so only kind='single' faults (targeting large on the
    router prompt) can expose them."""
    faults = freeze['states'][state]['competitive']['faults']
    refs = freeze['states'][state]['competitive']['reference_models']
    out = {}
    for uid, (kind, failing) in faults.items():
        if arm_cfg['kind'] == 'single':
            if kind == 'single':
                out[uid] = ('single', arm_cfg['model'], failing)
        else:
            out[uid] = (kind, refs[kind], failing)
    return out


def eval_single_arm(arm, arm_cfg, ex, tasks, registry, golds):
    from static_dag_v0.frozen200_run import ROUTER_PROMPT, parse_router
    rows = []
    fb_model = arm_cfg.get('fallback')
    for t in tasks:
        uid = t['uid']
        reg = registry.get(uid)
        node = reg[0] if reg else 'single'
        prompt = ROUTER_PROMPT.format(q=t['question'], ctx_table=t['ctx_table'],
                                      ctx_text=t['ctx_text'])
        key = f'nb:{arm}:single:{uid}'
        ex.call(key, arm_cfg['model'], prompt, uid=uid if reg else None, node=node)
        keys = [key]
        value = parse_router(ex.by_key[key]['response']['answer'])
        if value is None and fb_model:
            fb_key = f'nb:{arm}:fb:{uid}'
            ex.call(fb_key, fb_model, prompt, uid=uid if reg else None, node=node)
            keys.append(fb_key)
            value = parse_router(ex.by_key[fb_key]['response']['answer'])
        recs = [ex.by_key[k] for k in keys]
        gold = golds[uid]['gold']
        rows.append(dict(
            uid=uid,
            Q=int(score_v21(value, gold)) if value is not None else 0,
            final_value=value, v21_gold=gold, v21_gold_source=golds[uid]['source'],
            faulted=reg is not None,
            replaced_calls=sum(1 for r in recs if r['response'].get('injected_fault')),
            C_tokens=sum(r['response']['usage']['total_tokens'] for r in recs),
            L_serial_service_reconstructed_s=sum(r['response'].get('latency_s', 0) for r in recs),
            logical_calls=len(recs)))
    return rows


def eval_dag_arm(arm, arm_cfg, ex, led, tasks, registry, golds, state):
    faults = {uid: (node, failing) for uid, (node, _m, failing) in registry.items()}
    config = dict(id=f'nb:{arm}:{state}', X=arm_cfg['X'])
    rows = _evaluate(config, ex, led, tasks, faults, label=arm,
                     recovery=arm_cfg['Z'] == 'LOCAL')
    if arm_cfg['Z'] == 'FULL':
        retry = [t for t in tasks if detected_failure(rows[t['uid']], ex, led)]
        if retry:
            retry_config = copy.deepcopy(config)
            retry_config['X'] = {n: ('coder' if m == 'large' else 'large')
                                 for n, m in arm_cfg['X'].items()}
            rerun = _evaluate(retry_config, ex, led, retry, faults, label=arm + ':replay')
            for uid, row in rerun.items():
                rows[uid] = dict(row, keys=rows[uid]['keys'] + row['keys'])
    out = []
    for t in tasks:
        uid = t['uid']
        row = rows[uid]
        recs = [ex.by_key[k] for k in row['keys']]
        gold = golds[uid]['gold']
        final_val = row.get('final_value')
        out.append(dict(
            uid=uid,
            Q=int(score_v21(final_val, gold)) if final_val is not None else row['ok'],
            Q_v1=row['ok'], final_value=final_val, v21_gold=gold,
            v21_gold_source=golds[uid]['source'],
            faulted=uid in faults,
            replaced_calls=sum(1 for r in recs if r['response'].get('injected_fault')),
            C_tokens=sum(r['response']['usage']['total_tokens'] for r in recs),
            L_serial_service_reconstructed_s=sum(r['response'].get('latency_s', 0) for r in recs),
            logical_calls=len(recs)))
    return out


def prior_spend(run_dirs):
    """Authoritative physical reconciliation from DISPATCH ledgers."""
    requests = tokens = 0
    for d in run_dirs:
        disp = Path(d) / 'DISPATCH.jsonl'
        if not disp.exists():
            continue
        for line in disp.read_text().splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get('event') == 'reserved':
                requests += 1
            elif ev.get('event') == 'response':
                tokens += (ev.get('response', {}).get('usage', {}) or {}).get(
                    'total_tokens', 0) or 0
    return requests, tokens


def _dir_is_real(d):
    """A run dir counts toward the REAL budget only if it bound the freeze
    with execute=true. Stub spend never inflates or blocks real execution."""
    fb = Path(d) / 'FREEZE_BINDING.jsonl'
    if not fb.exists():
        return False
    first = fb.read_text().splitlines()
    return bool(first) and json.loads(first[0]).get('execute') is True


def completed_cells(execute):
    """Checkpoint isolation: real runs resume only from real records; stub
    runs only from stub records. Neither is ever upgraded into the other."""
    path = RUNROOT / ('NB_ROWS.jsonl' if execute else 'NB_ROWS_STUB.jsonl')
    done = set()
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                # legacy stub records predate the execute field; they are stub
                if r.get('status') == 'COMPLETE' and r.get('execute', False) is execute:
                    done.add((r['protocol'], r['arm'], r['state']))
    return done


def run(execute=False, run_id=None):
    from collab_scheduler_v1 import fault30_protocol as fp
    freeze, tasks = load_freeze()
    RUNROOT.mkdir(exist_ok=True)
    golds = v21_gold_map(tasks)
    led = fp.Ledger()
    done = completed_cells(execute)
    rows_path = RUNROOT / ('NB_ROWS.jsonl' if execute else 'NB_ROWS_STUB.jsonl')
    ledger_path = RUNROOT / ('NB_CELL_LEDGER.jsonl' if execute
                             else 'NB_CELL_LEDGER_STUB.jsonl')
    prior_dirs = sorted(d for d in RUNROOT.iterdir()
                        if d.is_dir() and (d / 'DISPATCH.jsonl').exists()
                        and _dir_is_real(d) == execute)
    prior_req, prior_tok = prior_spend(prior_dirs)
    caps = freeze['budgets']

    if execute:
        if os.environ.get('P1B_NETBENEFIT_EXECUTE') != '1':
            raise PermissionError('Real execution requires P1B_NETBENEFIT_EXECUTE=1')
        from static_dag_v0 import run as engine
        dispatch, prepare = engine.call_model, None  # prepared below
        run_id = run_id or time.strftime('real_%Y%m%d_%H%M%S')
        budget_caps = dict(new_request_attempts=min(
            caps['global_max_physical_requests'] - prior_req, 4000),
            new_total_tokens=caps['global_max_physical_tokens'] - prior_tok,
            request_token_reservation=8192, max_output_tokens=2048,
            wall_seconds=max(60, caps['global_max_wall_seconds'] - 0),
            logical_calls_per_task_config_state=24)
    else:
        dispatch = stub_dispatch
        run_id = run_id or 'stub_validation'
        budget_caps = dict(new_request_attempts=6000, new_total_tokens=50_000_000,
                           request_token_reservation=8192, max_output_tokens=2048,
                           wall_seconds=3600, logical_calls_per_task_config_state=24)

    directory = RUNROOT / run_id
    pending = [c for c in CELL_ORDER
               if c not in done and not (c[0] == 'competitive' and c[2] == 'clean')]
    if not pending:
        total_req, total_tok = prior_spend(prior_dirs)
        summary = dict(run_id=run_id, execute=execute, status='COMPLETE',
                       reason='nothing to do (all cells already complete '
                               'in this mode)', cells_this_run=0,
                       cumulative_spend=dict(requests=total_req, tokens=total_tok))
        print(json.dumps(summary, indent=1))
        return summary
    directory.mkdir(exist_ok=False)
    freeze_digest = hashlib.sha256(FREEZE_PATH.read_bytes()).hexdigest()
    append(directory / 'FREEZE_BINDING.jsonl',
           dict(freeze_sha256=freeze_digest, execute=execute, n_tasks=len(tasks),
                prior_spend=dict(requests=prior_req, tokens=prior_tok)))
    budget = Budget(directory, budget_caps)

    state_models = {}
    if execute:
        proc = log = None
        current = None

        def start_with_retry(model, attempts=3, wait_s=150):
            """Shared-host GPU: an external workload may hold memory; retry
            with backoff instead of failing the whole validation."""
            nonlocal proc, log, current
            import subprocess as _sp
            last = None
            for i in range(attempts):
                mem = _sp.run(['nvidia-smi', '--query-gpu=memory.used',
                               '--format=csv,noheader'], capture_output=True, text=True)
                used = int(mem.stdout.strip().rstrip(' MiB')) if mem.returncode == 0 else 99999
                if used > 4000:
                    print(f'[wait] GPU busy ({used} MiB used), '
                          f'attempt {i + 1}/{attempts}, sleeping {wait_s}s')
                    time.sleep(wait_s)
                try:
                    budget.check()
                    if proc is not None:
                        engine.stop_model(proc, log)
                        proc = log = None
                        current = None
                    p, lg, _ = engine.start_model(model)
                    return p, lg
                except Exception as e:  # noqa: BLE001 - retry any startup failure
                    last = e
                    print(f'[retry] start_model({model}) failed: {e!r}')
                    time.sleep(wait_s)
            raise last

        def prepare(model):
            nonlocal proc, log, current
            budget.check()
            if model == current:
                return
            begin = time.monotonic()
            proc, log = start_with_retry(model)
            current = model
            append(directory / 'MODEL_SWITCH.jsonl',
                   dict(model=model, wall_s=time.monotonic() - begin))
            budget.check()
    else:
        def prepare(model):
            budget.check()

    ex = NBExecutor(directory, budget, dispatch, prepare,
                    dict(medium='medium', large='large', coder='coder'))
    seeded = ex.seed_from_trajectories(prior_dirs)

    cell_spend = {}
    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get('status') == 'COMPLETE' and r.get('execute', False) is execute:
                    k = (r['protocol'], r['arm'], r['state'])
                    p = r['physical']
                    cell_spend[k] = cell_spend.get(k, 0) + p.get('new_requests', 0)

    results = []
    status = 'COMPLETE'
    reason = 'all cells done'
    try:
        for protocol, arm, state in CELL_ORDER:
            cell = (protocol, arm, state)
            if state == 'clean' and protocol == 'competitive':
                continue  # clean is shared; mechanism clean is authoritative
            if cell in done:
                continue
            # D/E reservation: non-D/E cells cannot consume the reserve while
            # D/E fault cells are incomplete.
            de_left = [c for c in CELL_ORDER if c[0] == 'mechanism' and
                       c[1] in DE_ARMS and c[2] != 'clean' and c not in done]
            spent_req, _ = prior_spend(prior_dirs + [directory])
            if de_left and arm not in DE_ARMS and \
                    caps['global_max_physical_requests'] - spent_req < caps['de_reserved_physical_requests']:
                raise StopRun('budget reserve for D/E would be violated')
            per_cell = cell_spend.get(cell, 0)
            if per_cell >= caps['per_strategy_per_state_physical_max']:
                append(rows_path,
                       dict(protocol=protocol, arm=arm, state=state,
                            execute=execute,
                            status='INCOMPLETE',
                            reason='per-strategy-state physical cap'))
                continue

            arm_cfg = freeze['arms'][arm]
            label = f'{protocol}:{arm}:{state}'
            if state == 'clean':
                registry = {}
            elif protocol == 'mechanism':
                registry = mechanism_registry(freeze, arm_cfg, state, tasks)
            else:
                registry = competitive_registry(freeze, arm_cfg, state, tasks)
            before = (budget.attempts, budget.actual_tokens)
            started = time.monotonic()
            ex.begin_cell(CACHE_SCOPE, label)
            for uid, (node, model, failing) in registry.items():
                ex.set_fault(uid, node, model, failing, {}, 0)
            if arm_cfg['kind'] == 'single':
                rows = eval_single_arm(arm, arm_cfg, ex, tasks, registry, golds)
            else:
                rows = eval_dag_arm(arm, arm_cfg, ex, led, tasks, registry,
                                    golds, state)
            ex.clear_faults()
            physical = fr.physical_accounting(ex.events)
            if physical['new_requests'] != budget.attempts - before[0] or \
                    physical['new_tokens'] != budget.actual_tokens - before[1]:
                raise StopRun(f'physical ledger mismatch in {label}')
            n = len(rows)
            record = dict(
                protocol=protocol, arm=arm, state=state, status='COMPLETE',
                execute=execute,
                freeze_sha256=freeze_digest,
                objectives=dict(
                    Q=sum(r['Q'] for r in rows) / n,
                    C=sum(r['C_tokens'] for r in rows) / n,
                    L=sum(r['L_serial_service_reconstructed_s'] for r in rows) / n),
                physical=dict(**{k: physical[k] for k in (
                    'logical_calls', 'cache_hits', 'new_requests', 'new_tokens',
                    'new_latency_s', 'answer_replaced_calls', 'injected_calls')},
                    wall_s=time.monotonic() - started),
                exposure=dict(
                    faulted_tasks=len(registry),
                    tasks_with_replaced_answer=sum(1 for r in rows if r['replaced_calls'] > 0)),
                tasks=rows)
            append(rows_path, record)
            append(ledger_path, dict(protocol=protocol, arm=arm, state=state,
                                     status='COMPLETE', execute=execute,
                                     physical=record['physical']))
            cell_spend[cell] = cell_spend.get(cell, 0) + physical['new_requests']
            results.append(record)
            print(f'[ok] {label}: Q={record["objectives"]["Q"]:.3f} '
                  f'C={record["objectives"]["C"]:.0f} '
                  f'new_req={physical["new_requests"]} '
                  f'replaced={physical["answer_replaced_calls"]}')
    except BaseException as exc:
        status = 'INCOMPLETE'
        reason = repr(exc)
        print(f'[stop] {reason}')
    finally:
        if execute and proc is not None:
            try:
                engine.stop_model(proc, log)
            except Exception as e:  # noqa: BLE001 - cleanup best effort
                print(f'[warn] model cleanup failed: {e!r}')

    total_req, total_tok = prior_spend(prior_dirs + [directory])
    summary = dict(run_id=run_id, execute=execute, status=status, reason=reason,
                   cache_seeded=seeded, cells_this_run=len(results),
                   cumulative_spend=dict(requests=total_req, tokens=total_tok,
                                         request_cap=caps['global_max_physical_requests'],
                                         token_cap=caps['global_max_physical_tokens']))
    append(directory / 'RUN_SUMMARY.jsonl', summary)
    print(json.dumps(summary, indent=1))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true',
                    help='real model execution (also needs env gate)')
    ap.add_argument('--run-id', default=None)
    args = ap.parse_args()
    run(execute=args.execute, run_id=args.run_id)


if __name__ == '__main__':
    main()
