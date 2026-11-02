"""stage_c_r1_v1 REAL execution driver (operator-authorized 2026-10-30).

Imports the FROZEN production engine (stage_c_r1.py, six_arm_scheduler.py)
WITHOUT modifying it; startup safety per operator item III:
  S1  verify frozen SHA256 of runner + scheduler + freeze config against
      STAGE_C_R1_FINAL_FREEZE.json — mismatch refuses to start;
  S2  exclusive run directory (exist_ok=False) + flock; any concurrent
      writer or pre-existing lock refuses to start;
  S3  auth gate 'stage_c_r1_v1' (seven-field record, FAIL-CLOSED).
Budget enforcement: Meter global 550/600K + per-model quota wrapper
(glm53 160/266K, glm53flash 30/50K) — all limits simultaneous; failures,
timeouts and retries billed; fail-stop on contract violation.
Matrix: frozen 48 runs (SC-E1/SC-E3 x S1/S2 x 6 arms x 2 reps) with shared
paid prefixes; dual makespan accounting (suffix measured, end-to-end
reconstructed). No historical results touched.
"""
import fcntl, hashlib, json, os, sys, time, traceback
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import stage_c_r1 as R1
from six_arm_scheduler import ARMS
from pilot_common import Meter, BudgetExceeded

RUNNER = B / 'integration' / 'stage_c_r1.py'
SCHED = B / 'integration' / 'six_arm_scheduler.py'
FREEZE = B / 'stage_c_r1_runs' / 'STAGE_C_R1_FINAL_FREEZE.json'

QUOTAS = {'glm53': (160, 266000), 'glm53flash': (30, 50000)}
MAX_CALLS, MAX_TOKENS = 550, 600000
RUN_BUDGET = 20000          # per-run decision budget (tokens); real caps
                             # enforced by Meter + quota wrapper


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def startup_safety(resume_dir=None):
    fz = json.load(open(FREEZE))
    s = fz['shas']
    for name, path in (('runner_stage_c_r1', RUNNER),
                       ('scheduler_six_arm', SCHED)):
        if sha(path) != s[name]:
            raise PermissionError(f'frozen SHA mismatch for {name}: '
                                  f'{sha(path)[:12]} != {s[name][:12]}')
    if resume_dir:
        out = Path(resume_dir)
        assert out.exists() and (out / 'LEDGER.jsonl').exists()
    else:
        out = B / 'stage_c_r1_runs' / f'stage_c_r1_v1_EXEC_{time.strftime("%H%M%S")}'
        out.mkdir(parents=False, exist_ok=False)  # exclusive run dir
    lock = open(out / '.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # dead process lock released
    print(f'[safety] frozen SHAs verified; dir {out}'
          f'{" (RESUME)" if resume_dir else ""}')
    return out, lock


class QuotaMeter:
    """Wraps the pilot Meter with simultaneous per-model caps."""

    def __init__(self, meter):
        self.meter = meter
        self.calls = {'glm53': 0, 'glm53flash': 0}
        self.tokens = {'glm53': 0, 'glm53flash': 0}

    def call(self, alias, system, user, max_tokens, purpose, timeout_s=60):
        cc, ct = QUOTAS[alias]
        if self.calls[alias] + 1 > cc:
            raise BudgetExceeded(f'per-model call quota {alias}: '
                                 f'{self.calls[alias]}/{cc}')
        # conservative token guard: this call's max output + est input
        est_in = int(len(user) * 0.63)
        if self.tokens[alias] + est_in + int(max_tokens * 1.5) > ct:
            raise BudgetExceeded(f'per-model token quota {alias}: '
                                 f'{self.tokens[alias]}+{est_in + int(max_tokens*1.5)} > {ct}')
        rec, txt = self.meter.call(alias, system, user, max_tokens,
                                   purpose=purpose, timeout_s=timeout_s)
        self.calls[alias] += 1
        self.tokens[alias] += (rec['usage']['input_tokens']
                               + rec['usage']['output_tokens'])
        return rec, txt


def main():
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location('ag', '/root/r3_own_pool/'
                                   'deadline_reward_v1/auth_gate.py')
    ag = module_from_spec(spec)
    sys.modules['ag'] = ag
    spec.loader.exec_module(ag)
    ag.require('stage_c_r1_v1')

    resume = sys.argv[1] if len(sys.argv) > 1 else None
    out, lock = startup_safety(resume)
    meter = Meter(ledger_path=out / 'LEDGER.jsonl',
                  max_calls=MAX_CALLS, max_guaranteed_actual=MAX_TOKENS)
    qm = QuotaMeter(meter)
    tasks = R1.load_tasks()
    results, t0 = [], time.time()

    try:
        for tid in ('SC-E1', 'SC-E3'):
            data = tasks[tid]
            dag = data['task']['dag']
            tl = next(n['id'] for n in dag['nodes'] if n['kind'] == 'timeline')
            chk = next(n['id'] for n in dag['nodes']
                       if n['kind'] == 'verification')
            for scen, node in (('S1_transport', tl), ('S2_contract', chk)):
                for rep in (1, 2):
                    anom = ({node: dict(type='transport', left=1)}
                            if scen.startswith('S1')
                            else {node: dict(type='contract')})
                    pre_id = f'SCR1-shared-{tid}-{scen}-r{rep}'
                    t_pre = time.time()
                    pre = R1.run_prefix(
                        data, anom, budget_tokens=RUN_BUDGET,
                        adapter=R1.MeterAdapter(qm, run_id=pre_id))
                    fork_t = pre['state'].t_now
                    print(f'[{pre_id}] prefix: {len(pre["calls"])} calls, '
                          f'fork_t={fork_t:.1f}s virtual, '
                          f'{time.time()-t_pre:.0f}s wall', flush=True)
                    for arm in ARMS:
                        rid = f'SCR1-{arm}-{tid}-{scen}-r{rep}'
                        t_r = time.time()
                        r = R1.run_arm(
                            arm, data, fork=pre, budget_tokens=RUN_BUDGET,
                            adapter=R1.MeterAdapter(qm, run_id=rid))
                        suffix_mk = round(r['makespan'] - fork_t, 2)
                        rec = dict(
                            run_id=rid, arm=arm, task=tid, scenario=scen,
                            rep=rep, status=r['status'], Q=r['Q'],
                            covered=r['covered'], n_silver=r['n_silver'],
                            tokens=r['tokens'], n_calls=len(r['calls']),
                            suffix_makespan_s=suffix_mk,
                            reconstructed_e2e_makespan_s=r['makespan'],
                            deadline_met=r['deadline_met'],
                            z_ops_applied=r['z_ops_applied'],
                            baseline_type=r['baseline_type'],
                            attribution_note=r['attribution_note'],
                            wait_total=r['wait_total'],
                            wall_s=round(time.time() - t_r, 1),
                            rounds=r['rounds'], calls=r['calls'])
                        results.append(rec)
                        (out / f'{rid}.json').write_text(json.dumps(
                            rec, ensure_ascii=False, indent=1, default=str))
                        print(f'  {arm:16s} {r["status"]:30s} Q={r["Q"]:.3f} '
                              f'tok={r["tokens"]:6d} suf_mk={suffix_mk:5.1f}s '
                              f'z={r["z_ops_applied"] or "KEEP"} '
                              f'({rec["wall_s"]}s wall)', flush=True)
                        (out / 'PARTIAL.json').write_text(json.dumps(
                            dict(results=results, quota=qm.__dict__),
                            ensure_ascii=False, indent=1, default=str))
        final = dict(
            batch='stage_c_r1_v1', status='COMPLETE', runs=results,
            budget=dict(meter=meter.summary(), quota_meter=qm.__dict__,
                        caps=dict(calls=MAX_CALLS, tokens=MAX_TOKENS,
                                  per_model={k: dict(calls=v[0], tokens=v[1])
                                             for k, v in QUOTAS.items()})),
            wall_s=round(time.time() - t0, 1))
        (out / 'RESULTS.json').write_text(json.dumps(
            final, ensure_ascii=False, indent=1, default=str))
        print(f'\nDONE: {len(results)} runs, wall={final["wall_s"]}s -> {out}')
    except BaseException as exc:
        (out / 'INCOMPLETE.json').write_text(json.dumps(
            dict(reason=repr(exc), results=results, quota=qm.__dict__,
                 traceback=traceback.format_exc()),
            ensure_ascii=False, indent=1, default=str))
        print(f'INCOMPLETE: {exc!r}')
        raise


if __name__ == '__main__':
    main()
