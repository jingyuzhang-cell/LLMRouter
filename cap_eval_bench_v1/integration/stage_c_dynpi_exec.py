"""stage_c_dynpi_v1 REAL execution driver — DYNAMIC_PI_FINAL_EXPERIMENT_PLAN.md.

Config-only variant of the R9B of-record driver (stage_c_r9_exec.py): same frozen
chain (delta contract 34e563a8), same executor semantics (stage_c_r1 eaffda4e),
same shared-prefix fork + Meter dedup + QuotaMeter replay fix. Deltas ONLY:
ARMS = ('R-only' [A=Static-π], 'pi-only' [B=Dynamic-π]), TASKS = (SC-E2, SC-E4),
caps 100 calls / 150K tokens / glm53 80-120K / flash 20-30K, batch name, auth gate.
R/Z fixed per plan; one-shot batch; stop rules per plan §10; no quota additions.
"""
import fcntl, hashlib, json, sys, time, traceback
from pathlib import Path
B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import stage_c_r9_chain as R9
import stage_c_r1 as R1
from pilot_common import Meter, BudgetExceeded

QUOTAS = {'glm53': (80, 120000), 'glm53flash': (20, 30000)}
MAX_CALLS, MAX_TOKENS = 100, 150000
RUN_BUDGET = 60000
ARMS = ('R-only', 'pi-only')          # A=Static-π | B=Dynamic-π (frozen deciders)
TASKS = ('SC-E2', 'SC-E4')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class QuotaMeter:
    def __init__(self, meter):
        self.meter = meter
        self.calls = {'glm53': 0, 'glm53flash': 0}
        self.tokens = {'glm53': 0, 'glm53flash': 0}

    def call(self, alias, system, user, max_tokens, purpose, timeout_s=60):
        # AMENDMENT-2 (seam-test finding): model-suffix the purpose so the
        # faulted node's retry does NOT dedup-replay the other arm's
        # differently-modelled response (treatment nullification). Prefix
        # (same pi0 models) still replays free; downstream prompts differ
        # by content sha anyway.
        purpose = f'{purpose}:{alias}'
        cc, ct = QUOTAS[alias]
        h = hashlib.sha256((system + '\x00' + user).encode()).hexdigest()
        if any(c['purpose'] == purpose and c['prompt_sha256'] == h
               for c in self.meter.calls):
            return self.meter.call(alias, system, user, max_tokens,
                                   purpose=purpose, timeout_s=timeout_s)
        if self.calls[alias] + 1 > cc:
            raise BudgetExceeded(f'per-model call quota {alias}')
        est_in = int(len(user) * 0.63)
        if self.tokens[alias] + est_in + int(max_tokens * 1.5) > ct:
            raise BudgetExceeded(f'per-model token quota {alias}')
        rec, txt = self.meter.call(alias, system, user, max_tokens,
                                    purpose=purpose, timeout_s=timeout_s)
        self.calls[alias] += 1
        self.tokens[alias] += (rec['usage']['input_tokens']
                               + rec['usage']['output_tokens'])
        return rec, txt


class AdapterFactory:
    def __init__(self, qm):
        self.qm = qm
        self.run_id = 'UNSET'

    def __call__(self, anomalies=None, corrupt=False):
        return R9.MeterR9Adapter(self.qm, self.run_id)


def main():
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location('ag', '/root/r3_own_pool/'
                                   'deadline_reward_v1/auth_gate.py')
    ag = module_from_spec(spec)
    sys.modules['ag'] = ag
    spec.loader.exec_module(ag)
    ag.require('stage_c_dynpi_v1')

    for name, path, want in (
            ('six_arm_scheduler', B / 'integration' / 'six_arm_scheduler.py', 'cd68ec44'),
            ('stage_c_r1', B / 'integration' / 'stage_c_r1.py', 'eaffda4e'),
            ('stage_c_r9_chain', B / 'integration' / 'stage_c_r9_chain.py', '34e563a8')):
        got = sha(path)[:8]
        if got != want:
            raise PermissionError(f'frozen SHA mismatch {name}: {got} != {want}')

    (B / 'stage_c_dynpi_runs').mkdir(parents=True, exist_ok=True)
    out = B / 'stage_c_dynpi_runs' / f'EXEC_{time.strftime("%H%M%S")}'
    out.mkdir(parents=False, exist_ok=False)
    lock = open(out / '.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    meter = Meter(ledger_path=out / 'LEDGER.jsonl',
                  max_calls=MAX_CALLS, max_guaranteed_actual=MAX_TOKENS)
    qm = QuotaMeter(meter)
    factory = AdapterFactory(qm)
    tasks = R1.load_tasks()
    results, t0 = [], time.time()

    def writer(rec, full):
        results.append(rec)
        (out / f'{rec["task"]}-{rec["arm"]}-r{rec["rep"]}.json').write_text(
            json.dumps(full, ensure_ascii=False, indent=1, default=str))
        (out / 'PARTIAL.json').write_text(json.dumps(
            dict(results=results, quota=qm.__dict__), ensure_ascii=False,
            indent=1, default=str))

    try:
        for rep in (1, 2, 3):
            for tid in TASKS:
                data = tasks[tid]
                # AMENDMENT (pre-launch validation finding): S2 persistent
                # contract@verification is unwinnable for BOTH arms with Z
                # fixed out (synthetic 4/4 INCOMPLETE, model-independent
                # stamp) -> guaranteed null batch. Validated amendment: T1
                # transient transport x1 at the pi0-flash reasoning node;
                # A keeps original model on retry, B reassigns to glm53
                # (synthetic 4/4 COMPLETE with clean differentiation).
                tgt = next(n['id'] for n in data['task']['dag']['nodes']
                           if n['kind'] == 'reasoning')

                def fresh_anom():
                    return {tgt: dict(type='transport', left=1)}

                # shared paid prefix under one run_id per cell: both arms
                # dedup-replay it free (frozen fork protocol, plan §6);
                # each run_r9 needs a FRESH fault dict (left is consumed)
                factory.run_id = f'DYNPI-shared-{tid}-r{rep}'
                pre = R9.run_r9('Static-Parallel', data, fresh_anom(),
                                budget_tokens=RUN_BUDGET,
                                adapter_factory=factory)
                print(f'[shared-{tid}-r{rep}] prefix {len(pre["calls"])} calls '
                      f'{pre["tokens"]} tok fault_fired={pre["status"] != "COMPLETE"} '
                      f'target={tgt}', flush=True)
                for arm in ARMS:
                    r = R9.run_r9(arm, data, fresh_anom(),
                                  budget_tokens=RUN_BUDGET,
                                  adapter_factory=factory)
                    rec = dict(task=tid, arm=arm, rep=rep, status=r['status'],
                               tokens=r['tokens'], n_calls=len(r['calls']),
                               makespan=r['makespan'],
                               terminal_stats=r['terminal_stats'],
                               models_used=sorted({c['model'] for c in r['calls']}),
                               z_ops=[rd['z_op'] for rd in r['rounds']
                                      if rd['z_op'] != 'KEEP'])
                    writer(rec, r)
                    print(f'  {arm:10s} {tid} r{rep} {r["status"]:32s} '
                          f'tok={r["tokens"]:6d} calls={len(r["calls"])} '
                          f'facts={(r["terminal_stats"] or {}).get("n", 0)}',
                          flush=True)
        final = dict(batch='stage_c_dynpi_v1', status='COMPLETE', results=results,
                     budget=dict(meter=meter.summary(), quota=qm.__dict__,
                                 caps=dict(calls=MAX_CALLS, tokens=MAX_TOKENS,
                                           per_model={k: dict(calls=v[0], tokens=v[1])
                                                      for k, v in QUOTAS.items()})),
                     wall_s=round(time.time() - t0, 1))
        (out / 'RESULTS.json').write_text(json.dumps(final, ensure_ascii=False,
                                                     indent=1, default=str))
        print(f'\nDONE: {len(results)} runs -> {out}', flush=True)
    except BudgetExceeded as exc:
        (out / 'BUDGET_STOP.json').write_text(json.dumps(
            dict(reason=repr(exc), results=results, quota=qm.__dict__,
                 meter=meter.summary()), ensure_ascii=False, indent=1,
            default=str))
        print(f'BUDGET STOP after {len(results)} runs: {exc!r}', flush=True)
    except BaseException as exc:
        (out / 'INCOMPLETE.json').write_text(json.dumps(
            dict(reason=repr(exc), results=results, quota=qm.__dict__,
                 traceback=traceback.format_exc()), ensure_ascii=False,
            indent=1, default=str))
        print(f'INCOMPLETE: {exc!r}', flush=True)
        raise


if __name__ == '__main__':
    main()
