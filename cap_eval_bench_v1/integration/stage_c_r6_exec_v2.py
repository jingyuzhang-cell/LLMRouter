"""stage_c_r6_v1 REAL execution driver (operator-authorized 32B, 2026-10-30).

Frozen production stack ONLY: six_arm_scheduler.py (cd68ec44), stage_c_r1.py
(eaffda4e), Silver v2 (b375eb33), stage_c_r4_runner.py + fact_ledger.py
(current SHAs recorded at launch into the run dir). The parallel session's
partial batch (stage_c_r6_runs/, 89 calls, demo engine) is QUARANTINED:
separate ledger here, no mixing, no recount.

Design per authorization:
  * shared paid prefix per (task, scenario, rep), arm-agnostic pi0, purposes
    R6B-shared-*; six arms fork from the identical post-fault snapshot;
  * S2 pair (JointRP vs JointZ): base R / pi equality asserted; divergence
    marks the pair NON_ISOLATED (never force-credited to Z);
  * caps simultaneous: global 170 calls / 250K tokens; glm53 140/200K;
    glm53flash 40/55K; failures/timeouts/retries/injected calls all billed;
    any cap -> immediate stop;
  * staged: rep-1 cells first, then rep-2 while budget reservation allows
    (estimate uncertainty acknowledged; caps govern);
  * per-run artifacts: terminal ledger dump (fid/content/status/source),
    report object, rounds, calls, dual makespan; offline operand-aware
    scoring afterwards (zero-call).
"""
import fcntl, hashlib, json, sys, time, traceback
from copy import deepcopy
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import stage_c_r4_runner as R4
import stage_c_r1 as R1
from six_arm_scheduler import (ARMS, ARM_META, ARM_DECIDERS)
from pilot_common import Meter, BudgetExceeded

QUOTAS = {'glm53': (140, 200000), 'glm53flash': (40, 55000)}
MAX_CALLS, MAX_TOKENS = 170, 250000
RUN_BUDGET = 60000
S1_ARMS = ARMS
S2_ARMS = ('Joint(R,pi)', 'Joint(Z,R,pi)')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class QuotaMeter:
    def __init__(self, meter):
        self.meter = meter
        self.calls = {'glm53': 0, 'glm53flash': 0}
        self.tokens = {'glm53': 0, 'glm53flash': 0}

    def call(self, alias, system, user, max_tokens, purpose, timeout_s=60):
        cc, ct = QUOTAS[alias]
        if self.calls[alias] + 1 > cc:
            raise BudgetExceeded(f'per-model call quota {alias}')
        est_in = int(len(user) * 0.63)
        if self.tokens[alias] + est_in + int(max_tokens * 1.5) > ct:
            raise BudgetExceeded(f'per-model token quota {alias}: '
                                 f'{self.tokens[alias]}+{est_in + int(max_tokens * 1.5)}>{ct}')
        rec, txt = self.meter.call(alias, system, user, max_tokens,
                                    purpose=purpose, timeout_s=timeout_s)
        self.calls[alias] += 1
        self.tokens[alias] += rec['usage']['input_tokens'] + rec['usage']['output_tokens']
        return rec, txt


class BoundMeterAdapter(R4.MeterFactAdapter):
    """Binds the shared meter + a mutable run_id to the R4 adapter seam."""
    meter_ref = None
    run_id = None

    def __init__(self, anomalies=None, inject_fake_fact=False):
        super().__init__(self.meter_ref, self.run_id)


def resp_node(data):
    dag = data['task']['dag']
    tl = next((n['id'] for n in dag['nodes'] if n['kind'] == 'timeline'), None)
    chk = next(n['id'] for n in dag['nodes'] if n['kind'] == 'verification')
    return tl or chk, chk


def merged_ledger(state, ledgers, nid):
    m = R4.FactLedger()
    for p in state.parents(nid):
        if p in ledgers:
            m.merge(ledgers[p], via_node=p, via_version=state.nodes[p].version)
    return m


def execute(state, assignments, ledgers, anomalies, data, calls):
    t_end = state.t_now
    trunc_events = []
    for nid, model in assignments:
        merged = merged_ledger(state, ledgers, nid)
        prompt, kept_fids = R4.build_prompt_r4(state, nid, merged, data['texts'])
        trunc_events += [dict(node=nid, **t) for t in merged.truncation_log]
        adapter = BoundMeterAdapter()   # class-bound meter + run_id
        r = adapter.call(nid, state.kinds[nid], model, prompt, merged,
                         data['texts'], visible_fids=kept_fids)
        r = R1.inject_result(anomalies, nid, r)
        n = state.nodes[nid]
        n.attempts += 1
        n.version += 1
        n.model, n.latency_s = model, r['latency_s']
        n.usage = r['usage']
        t_end += r['latency_s']
        if r['success']:
            n.status, n.output = 'done', r['output']
            ledgers[nid] = r['ledger']
        else:
            n.status, n.output, n.failure_type = 'failed', None, r['failure']
        calls.append(dict(node=nid, model=model, attempt=n.attempts,
                          success=r['success'], failure=r['failure'],
                          usage=r['usage'], latency_s=r['latency_s']))
    state.t_now = t_end
    return trunc_events


def run_from(state, ledgers, arm, anomalies, data, meta_budget=(RUN_BUDGET, 0.0),
             spent0=0.0, calls0=None, recovery_rounds0=0):
    """Decision loop for one arm from the given (possibly forked) state."""
    calls = list(calls0 or [])
    spent = spent0
    state.budget_remaining = meta_budget[0] - spent
    rounds, recovery_rounds = [], recovery_rounds0
    status = 'RUNNING'
    terminal = state.terminal()
    trunc = []
    while status == 'RUNNING':
        if state.failed_nodes():
            recovery_rounds += 1
        dec = ARM_DECIDERS[arm](state)
        rounds.append(dict(round=len(rounds) + 1, action=dec.action_type,
                           z_op=dec.z_op, z_detail=dec.z_detail,
                           recovery_set=sorted(dec.recovery_set),
                           reoptimize=dec.reoptimize,
                           rationale=dec.rationale[:200]))
        if dec.action_type == 'terminate' or not dec.assignments:
            status = ('COMPLETE' if state.nodes[terminal].status == 'done' else
                      'INCOMPLETE_NO_RECOVERY'
                      if (state.failed_nodes() and not ARM_META[arm]['recovers'])
                      else 'INCOMPLETE_RECOVERY_EXHAUSTED'
                      if state.failed_nodes() else 'STALLED')
            break
        if dec.z_op != 'KEEP':
            R1.apply_z(state, dec.z_op, dec.z_detail)
        for nid, model in dec.reoptimize:
            if nid in state.nodes:
                state.nodes[nid].model = model
        if not ARM_META[arm]['recovers']:
            dec.assignments = [(n, m) for n, m in dec.assignments
                               if state.nodes[n].status != 'failed']
        trunc += execute(state, dec.assignments, ledgers, anomalies, data, calls)
        for nid in state.blocked_nodes():
            state.nodes[nid].status = 'blocked'
        for nid, n in state.nodes.items():
            if n.status == 'blocked' and all(
                    state.nodes[p].status == 'done' for p in state.parents(nid)):
                n.status = 'pending'
        if state.nodes[terminal].status == 'done':
            status = 'COMPLETE'
        elif state.budget_remaining <= 0:
            status = 'BUDGET_STOP'
        elif (state.failed_nodes() and ARM_META[arm]['recovers']
              and recovery_rounds >= R1.MAX_RECOVERY_ROUNDS):
            status = 'INCOMPLETE_RECOVERY_EXHAUSTED'
    spent = sum(c['usage']['in'] + c['usage']['out'] for c in calls)
    term = ledgers.get(terminal)
    rep = state.nodes[terminal].output if term else None
    return dict(status=status, rounds=rounds, calls=calls, trunc=trunc,
                terminal_facts=[dict(fid=f.fid, content=f.content, kind=f.kind,
                                     status=f.status, source=f.source_doc)
                                for f in (term.facts.values() if term else [])],
                terminal_stats=term.stats() if term else None,
                report=rep, makespan=round(state.t_now, 2),
                tokens=int(spent))


def snapshot(state, ledgers, spent, calls):
    return dict(state=deepcopy(state),
                ledgers={k: deepcopy(v) for k, v in ledgers.items()},
                spent=spent, calls=list(calls), t_now=state.t_now)


def run_cell(qm, out, data, scen, rep, writer):
    resp, chk = resp_node(data)
    node = resp if scen == 'S1' else chk
    anom = ({node: dict(type='transport', left=1)} if scen == 'S1'
            else {node: dict(type='contract')})
    arms = S1_ARMS if scen == 'S1' else S2_ARMS
    # ---- shared paid prefix (arm-agnostic pi0) ----
    BoundMeterAdapter.run_id = f'R6B-shared-{data["task"]["task_id"]}-{scen}-r{rep}'
    state = R4.build_state_r4(data, RUN_BUDGET)
    ledgers, calls = {}, []
    spent = 0.0
    while True:
        ready = state.ready_nodes()
        if not ready:
            break
        execute(state, [(n, state.nodes[n].model) for n in ready],
                ledgers, anom, data, calls)
        for nid in state.blocked_nodes():
            state.nodes[nid].status = 'blocked'
        if state.failed_nodes():
            break
    spent = sum(c['usage']['in'] + c['usage']['out'] for c in calls)
    fork = snapshot(state, ledgers, spent, calls)
    fork_anom = anom
    print(f'[{BoundMeterAdapter.run_id}] prefix {len(calls)} calls, '
          f'{int(spent)} tok, fault_fired={bool(state.failed_nodes())}', flush=True)
    # ---- S2 isolation record ----
    isolation = None
    if scen == 'S2':
        st_a = deepcopy(fork['state'])
        dRP = ARM_DECIDERS['Joint(R,pi)'](st_a)
        rp = dict(R=sorted(dRP.recovery_set), pi=dict(dRP.reoptimize),
                  z=dRP.z_op)
        st_b = deepcopy(fork['state'])
        dZ = ARM_DECIDERS['Joint(Z,R,pi)'](st_b)
        # base R = recovery set before the Z rewrite strips the target:
        zb = sorted(set(dZ.recovery_set) - {dZ.z_detail.split(' -> ')[0]
                                            + suf for suf in ('_a', '_b')}) \
            if dZ.z_op == 'SPLIT_VERIFY' else sorted(dZ.recovery_set)
        zj = dict(R=zb, pi={k: v for k, v in dict(dZ.reoptimize).items()
                            if not k.endswith(('_a', '_b'))}, z=dZ.z_op)
        isolation = dict(jointRP=rp, jointZ=zj,
                         base_R_equal=rp['R'] == zj['R'],
                         pi_equal=rp['pi'] == zj['pi'],
                         verdict='ISOLATED' if (rp['R'] == zj['R'])
                         else 'NON_ISOLATED')
        print(f'  isolation: {isolation["verdict"]} (baseR RP={rp["R"]} '
              f'Z={zj["R"]}; z={zj["z"]})', flush=True)
    # ---- fork arms ----
    results = {}
    for arm in arms:
        BoundMeterAdapter.run_id = f'R6B-{arm}-{data["task"]["task_id"]}-{scen}-r{rep}'
        st = deepcopy(fork['state'])
        led = {k: deepcopy(v) for k, v in fork['ledgers'].items()}
        r = run_from(st, led, arm, fork_anom, data,
                     calls0=fork['calls'], spent0=fork['spent'],
                     recovery_rounds0=1 if st.failed_nodes() else 0)
        r['arm'] = arm
        r['suffix_makespan'] = round(r['makespan'] - fork['t_now'], 2)
        r['tokens'] = int(sum(c['usage']['in'] + c['usage']['out']
                              for c in r['calls']))
        results[arm] = r
        rec = dict(arm=arm, scenario=scen, rep=rep,
                   task=data['task']['task_id'], status=r['status'],
                   tokens=r['tokens'], n_calls=len(r['calls']),
                   suffix_mk=r['suffix_makespan'], e2e_mk=r['makespan'],
                   terminal_stats=r['terminal_stats'],
                   z_ops=[rd['z_op'] for rd in r['rounds']
                          if rd['z_op'] != 'KEEP'])
        writer(rec, r)
        print(f'  {arm:16s} {r["status"]:12s} tok={r["tokens"]:6d} '
              f'calls={len(r["calls"])} suf={r["suffix_makespan"]:5.1f}s '
              f'z={rec["z_ops"] or "KEEP"} '
              f'ledger={r["terminal_stats"]["n"] if r["terminal_stats"] else 0}',
              flush=True)
    return results, isolation


def main():
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location('ag', '/root/r3_own_pool/'
                                   'deadline_reward_v1/auth_gate.py')
    ag = module_from_spec(spec)
    sys.modules['ag'] = ag
    spec.loader.exec_module(ag)
    ag.require('stage_c_r6_v1')

    for name, path, want in (
            ('scheduler', B / 'integration' / 'six_arm_scheduler.py', 'cd68ec44'),
            ('engine_r1', B / 'integration' / 'stage_c_r1.py', 'eaffda4e'),
            ('silver_v2', B / 'stage_c_evidence' / 'silver_v2.json', 'b375eb33')):
        got = sha(path)[:8]
        if got != want:
            raise PermissionError(f'frozen SHA mismatch {name}: {got} != {want}')
    resume = sys.argv[1] if len(sys.argv) > 1 else None
    if resume:
        out = Path(resume)
        assert out.exists() and (out / 'LEDGER.jsonl').exists()
    else:
        (B / 'stage_c_r6_runs_v2').mkdir(parents=True, exist_ok=True)
        out = B / 'stage_c_r6_runs_v2' / f'EXEC_{time.strftime("%H%M%S")}'
        out.mkdir(parents=False, exist_ok=False)
    lock = open(out / '.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (out / 'LAUNCH_SHAS.json').write_text(json.dumps({
        'six_arm_scheduler': sha(B / 'integration' / 'six_arm_scheduler.py'),
        'stage_c_r1': sha(B / 'integration' / 'stage_c_r1.py'),
        'stage_c_r4_runner': sha(B / 'integration' / 'stage_c_r4_runner.py'),
        'fact_ledger': sha(B / 'integration' / 'fact_ledger.py'),
        'silver_v2': sha(B / 'stage_c_evidence' / 'silver_v2.json')}, indent=1))

    meter = Meter(ledger_path=out / 'LEDGER.jsonl',
                  max_calls=MAX_CALLS, max_guaranteed_actual=MAX_TOKENS)
    qm = QuotaMeter(meter)
    BoundMeterAdapter.meter_ref = qm

    tasks = R1.load_tasks()
    all_results, isolations = [], {}
    if resume and (out / 'PARTIAL.json').exists():
        all_results = json.load(open(out / 'PARTIAL.json'))['results']
        print(f'[resume] seeding {len(all_results)} completed runs', flush=True)
    t0 = time.time()

    def writer(rec, full):
        all_results.append(rec)
        (out / f'{rec["task"]}-{rec["scenario"]}-{rec["arm"]}-r{rec["rep"]}.json') \
            .write_text(json.dumps(full, ensure_ascii=False, indent=1, default=str))
        (out / 'PARTIAL.json').write_text(json.dumps(
            dict(results=all_results, quota=qm.__dict__), ensure_ascii=False,
            indent=1, default=str))

    try:
        done_keys = {(r['task'], r['scenario'], r['arm'], r['rep'])
                     for r in all_results}
        for rep in (1, 2):                      # staged: rep-1 fully first
            for tid in ('SC-E1', 'SC-E3'):
                for scen in ('S1', 'S2'):
                    arms = S1_ARMS if scen == 'S1' else S2_ARMS
                    if all((tid, scen, a, rep) in done_keys for a in arms):
                        print(f'[skip] {tid}-{scen}-r{rep} already complete',
                              flush=True)
                        continue
                    res, iso = run_cell(qm, out, tasks[tid], scen, rep, writer)
                    if iso:
                        isolations[f'{tid}-S2-r{rep}'] = iso
        final = dict(batch='stage_c_r6_v1', status='COMPLETE',
                     results=all_results, isolations=isolations,
                     budget=dict(meter=meter.summary(), quota=qm.__dict__,
                                 caps=dict(calls=MAX_CALLS, tokens=MAX_TOKENS,
                                           per_model={k: dict(calls=v[0], tokens=v[1])
                                                      for k, v in QUOTAS.items()})),
                     wall_s=round(time.time() - t0, 1))
        (out / 'RESULTS.json').write_text(json.dumps(
            final, ensure_ascii=False, indent=1, default=str))
        print(f'\nDONE: {len(all_results)} runs -> {out}')
    except BudgetExceeded as exc:
        (out / 'BUDGET_STOP.json').write_text(json.dumps(
            dict(reason=repr(exc), results=all_results,
                 quota=qm.__dict__, meter=meter.summary()),
            ensure_ascii=False, indent=1, default=str))
        print(f'BUDGET STOP after {len(all_results)} runs: {exc!r}')
    except BaseException as exc:
        (out / 'INCOMPLETE.json').write_text(json.dumps(
            dict(reason=repr(exc), results=all_results, quota=qm.__dict__,
                 traceback=traceback.format_exc()),
            ensure_ascii=False, indent=1, default=str))
        print(f'INCOMPLETE: {exc!r}')
        raise


if __name__ == '__main__':
    main()
