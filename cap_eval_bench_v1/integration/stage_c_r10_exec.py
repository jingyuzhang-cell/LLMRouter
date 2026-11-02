"""stage_c_r9b_v1 REAL execution driver (operator-admitted 8-run; delta
contract chain c74c9cb9; authorization gate on stage_c_r9b_v1).

Matrix: SC-E1+SC-E3 x S2_contract@verification x {A_plain=Joint(R,pi),
B_split=Joint(Z,R,pi)} x 2 reps = 8 runs. Shared paid prefix per cell; both
arms fork from the identical post-fault snapshot; Z the ONLY differing
dimension (divergence marks NON_ISOLATED). Caps simultaneous: 80/150K
global, glm53 65/120K, flash 20/30K; ¥0. Startup safety: frozen SHAs +
exclusive dir + flock. SSL: verify settlement, dedup resume.
"""
import fcntl, hashlib, json, sys, time, traceback
from copy import deepcopy
from pathlib import Path
B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import stage_c_r10_chain as R9
import stage_c_r1 as R1
from pilot_common import Meter, BudgetExceeded

QUOTAS = {'glm53': (32, 56000), 'glm53flash': (8, 14000)}  # R10
MAX_CALLS, MAX_TOKENS = 40, 70000  # R10
RUN_BUDGET = 60000
ARMS = ('Joint(Z,R,pi)',)  # R10: comparison-compliance only, B_split


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class QuotaMeter:
    def __init__(self, meter):
        self.meter = meter
        self.calls = {'glm53': 0, 'glm53flash': 0}
        self.tokens = {'glm53': 0, 'glm53flash': 0}

    def call(self, alias, system, user, max_tokens, purpose, timeout_s=60):
        cc, ct = QUOTAS[alias]
        # ERRATUM r9-2: dedup replays never hit the wire; they must not
        # consume per-model quota (phantom calls tripped nothing yet but
        # would exhaust glm53 65 mid-batch on prefix replays).
        sha = hashlib.sha256((system + '\x00' + user).encode()).hexdigest()
        replay = any(c['purpose'] == purpose and c['prompt_sha256'] == sha
                     for c in self.meter.calls)
        if replay:
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
    ag.require('stage_c_r10_v1')

    for name, path, want in (
            ('six_arm_scheduler', B / 'integration' / 'six_arm_scheduler.py', 'cd68ec44'),
            ('stage_c_r1', B / 'integration' / 'stage_c_r1.py', 'eaffda4e'),
            ('silver_v2', B / 'stage_c_evidence' / 'silver_v2.json', 'b375eb33'),
            ('stage_c_r9_chain', B / 'integration' / 'stage_c_r9_chain.py', '34e563a8')):
        got = sha(path)[:8]
        if got != want:
            raise PermissionError(f'frozen SHA mismatch {name}: {got} != {want}')
    resume = sys.argv[1] if len(sys.argv) > 1 else None
    if resume:
        out = Path(resume)
        assert out.exists() and (out / 'LEDGER.jsonl').exists()
    else:
        (B / 'stage_c_r10_runs').mkdir(parents=True, exist_ok=True)
        out = B / 'stage_c_r10_runs' / f'EXEC_{time.strftime("%H%M%S")}'
        out.mkdir(parents=False, exist_ok=False)
    lock = open(out / '.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    meter = Meter(ledger_path=out / 'LEDGER.jsonl',
                  max_calls=MAX_CALLS, max_guaranteed_actual=MAX_TOKENS)
    qm = QuotaMeter(meter)
    factory = AdapterFactory(qm)
    tasks = R1.load_tasks()
    results, isolations, t0 = [], {}, time.time()

    def writer(rec, full):
        results.append(rec)
        (out / f'{rec["task"]}-S2-{rec["arm"]}-r{rec["rep"]}.json').write_text(
            json.dumps(full, ensure_ascii=False, indent=1, default=str))
        (out / 'PARTIAL.json').write_text(json.dumps(
            dict(results=results, isolations=isolations, quota=qm.__dict__),
            ensure_ascii=False, indent=1, default=str))

    try:
        done = {(r['task'], r['arm'], r['rep']) for r in results}
        for rep in (1, 2, 3):
            for tid in ('SC-E3',):
                if all((tid, a, rep) in done for a in ARMS):
                    print(f'[skip] {tid}-r{rep}', flush=True)
                    continue
                data = tasks[tid]
                chk = next(n['id'] for n in data['task']['dag']['nodes']
                           if n['kind'] == 'verification')
                anom = {chk: dict(type='contract')}
                # shared paid prefix (arm-agnostic pi0, executed ONCE;
                # arms fork from the snapshot — no per-arm re-payment)
                factory.run_id = f'R10B-shared-{tid}-r{rep}'
                from stage_c_r9_chain import FactLedger as _FL
                pre_state = R9.R4.build_state_r4(data, RUN_BUDGET)
                pre_ledgers, pre_calls, pre_t = {}, [], 0.0
                import stage_c_r9_chain as _C
                while True:
                    ready = [n for n in pre_state.nodes
                             if pre_state.nodes[n].status == 'pending'
                             and all(pre_state.nodes[p].status == 'done'
                                     for p in pre_state.parents(n))]
                    if not ready:
                        break
                    for nid in ready:
                        merged = _FL()
                        for p in pre_state.parents(nid):
                            if p in pre_ledgers:
                                merged.merge(pre_ledgers[p], via_node=p,
                                             via_version=pre_state.nodes[p].version)
                        prompt, kept = _C.build_prompt_r9(
                            pre_state, nid, merged, data['texts'])
                        ad = factory()
                        r = ad.call(nid, pre_state.kinds[nid],
                                    pre_state.nodes[nid].model, prompt,
                                    merged, data['texts'], visible_fids=kept)
                        r = R1.inject_result(anom, nid, r)
                        n = pre_state.nodes[nid]
                        n.attempts += 1; n.version += 1
                        pre_t += r['latency_s']
                        pre_calls.append(dict(node=nid, model=n.model,
                                              success=r['success'],
                                              usage=r['usage']))
                        if r['success']:
                            n.status, n.output = 'done', r['output']
                            pre_ledgers[nid] = r['ledger']
                        else:
                            n.status, n.output = 'failed', None
                            n.failure_type = r['failure']
                    for nid in pre_state.nodes:
                        n = pre_state.nodes[nid]
                        if n.status == 'pending' and any(
                                pre_state.nodes[p].status == 'failed'
                                for p in pre_state.parents(nid)):
                            n.status = 'blocked'
                    if any(n.status == 'failed' for n in pre_state.nodes.values()):
                        break
                from copy import deepcopy as _dc
                fork = dict(state=_dc(pre_state),
                            ledgers={k: _dc(v) for k, v in pre_ledgers.items()},
                            calls=list(pre_calls), t=pre_t)
                print(f'[R10B-shared-{tid}-r{rep}] prefix {len(pre_calls)} calls '
                      f'(paid once; arms fork in-memory)', flush=True)
                # fork arms from the identical post-fault snapshot
                for arm in ARMS:
                    factory.run_id = f'R10B-{arm}-{tid}-r{rep}'
                    st = _dc(fork['state'])
                    led = {k: _dc(v) for k, v in fork['ledgers'].items()}
                    r = R9.run_r9(arm, data, anom, budget_tokens=RUN_BUDGET,
                                  adapter_factory=factory,
                                  fork=(st, led, list(fork['calls']), fork['t']))
                    rec = dict(task=tid, scenario='S2', arm=arm, rep=rep,
                               status=r['status'], tokens=r['tokens'],
                               n_calls=len(r['calls']),
                               suffix_calls=len(r['calls']) - len(fork['calls']),
                               makespan=r['makespan'],
                               terminal_stats=r['terminal_stats'],
                               z_ops=[rd['z_op'] for rd in r['rounds']
                                      if rd['z_op'] != 'KEEP'],
                               comparisons=(r.get('report') or {}).get('comparisons'))
                    writer(rec, r)
                    print(f'  {arm:16s} {r["status"]:8s} tok={r["tokens"]:6d} '
                          f'calls={len(r["calls"])} (suffix {rec["suffix_calls"]}) '
                          f'z={rec["z_ops"] or "KEEP"} '
                          f'ledger={(r["terminal_stats"] or {}).get("n", 0)}',
                          flush=True)
        final = dict(batch='stage_c_r10_v1', status='COMPLETE', results=results,
                     budget=dict(meter=meter.summary(), quota=qm.__dict__,
                                 caps=dict(calls=MAX_CALLS, tokens=MAX_TOKENS,
                                           per_model={k: dict(calls=v[0], tokens=v[1])
                                                      for k, v in QUOTAS.items()})),
                     wall_s=round(time.time() - t0, 1))
        (out / 'RESULTS.json').write_text(json.dumps(final, ensure_ascii=False,
                                                     indent=1, default=str))
        print(f'\nDONE: {len(results)} runs -> {out}')
    except BudgetExceeded as exc:
        (out / 'BUDGET_STOP.json').write_text(json.dumps(
            dict(reason=repr(exc), results=results, quota=qm.__dict__,
                 meter=meter.summary()), ensure_ascii=False, indent=1,
            default=str))
        print(f'BUDGET STOP after {len(results)} runs: {exc!r}')
    except BaseException as exc:
        (out / 'INCOMPLETE.json').write_text(json.dumps(
            dict(reason=repr(exc), results=results, quota=qm.__dict__,
                 traceback=traceback.format_exc()), ensure_ascii=False,
            indent=1, default=str))
        print(f'INCOMPLETE: {exc!r}')
        raise


if __name__ == '__main__':
    main()
