"""stage_c_tgv_v1 REAL execution driver — TGV v2.2 frozen design.

Real-MCF per §1.1: NO fault injection on the real path; node success/failure is
judged entirely by REAL model output vs the frozen delta/derivation contracts.
The model/node-type combination (reasoning kind, pi0=flash per INITIAL_PI,
capability gap 0.58 vs 0.80 from frozen Stage-B table) is frozen by STRUCTURE
RULE: MCF target = the task's reasoning-kind node. Three-state outcome coding
(MCF-MANIFESTED / MCF-NOT-MANIFESTED / S3-CONTROL) is post-hoc analysis.
Synthetic model-conditional injection exists ONLY in the stage-3 verification
harness (test scaffolding), never here. Deterministic MCF injection in this
driver = grounds for invalidating the batch.
"""
import fcntl, hashlib, json, sys, time, traceback
from pathlib import Path
B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import stage_c_r9_chain as R9
import stage_c_r1 as R1
from pilot_common import Meter, BudgetExceeded

QUOTAS = {'glm53': (75, 110000), 'glm53flash': (20, 20000)}
MAX_CALLS, MAX_TOKENS = 95, 130000          # = per-model sums (v2.2 §6, no phantom headroom)
RUN_BUDGET = 60000
MCF_TARGET_KIND = 'reasoning'               # frozen structure rule (capability table basis)
ARMS = ('Static-Parallel', 'R-only', 'pi-only', 'Joint(Z,R,pi)')
TASKS = ('TGV-T1', 'TGV-T2')


def load_tgv_tasks():
    d = json.load(open(B / 'tgv_tasks' / 'TGV_TASKS.json'))
    refs = json.load(open(B / 'tgv_tasks' / 'TGV_REFERENCES_ADJUDICATED.json'))['references']
    out = {}
    for t in d['tasks']:
        texts = {did: (B / 'evidence' / 'texts' / f'{did}.txt').read_text()
                 for did in t['doc_ids']}
        out[t['task_id']] = dict(task=t, texts=texts, references=refs[t['task_id']],
                                  deadline=t['deadline'])
    return out


def mcf_target(data):
    """Frozen structure rule: the task's reasoning-kind node (pi0=flash)."""
    return next(n['id'] for n in data['task']['dag']['nodes']
                if n['kind'] == MCF_TARGET_KIND)


def classify_mcf_state(target_calls):
    """Post-hoc three-state coding (v2.2 §1.1). target_calls: list of (model, success)."""
    flash = [ok for m, ok in target_calls if m == 'glm53flash']
    glm = [ok for m, ok in target_calls if m == 'glm53']
    if flash and not any(flash):
        return 'MCF-MANIFESTED' if (not glm or any(glm)) else 'MCF-MANIFESTED'
    return 'MCF-NOT-MANIFESTED'      # flash succeeded at least once -> cliff absent


class QuotaMeter:
    """dynpi-proven: model-suffixed purposes (cache key / quota / identity)."""
    def __init__(self, meter):
        self.meter = meter
        self.calls = {'glm53': 0, 'glm53flash': 0}
        self.tokens = {'glm53': 0, 'glm53flash': 0}

    def call(self, alias, system, user, max_tokens, purpose, timeout_s=60):
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
    ag.require('stage_c_tgv_v1')       # NOT YET REGISTERED -> refuses until authorized

    for name, path, want in (
            ('six_arm_scheduler', B / 'integration' / 'six_arm_scheduler.py', 'cd68ec44'),
            ('stage_c_r1', B / 'integration' / 'stage_c_r1.py', 'eaffda4e'),
            ('stage_c_r9_chain', B / 'integration' / 'stage_c_r9_chain.py', '34e563a8')):
        got = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8]
        if got != want:
            raise PermissionError(f'frozen SHA mismatch {name}: {got} != {want}')

    # RESUME SUPPORT (r9b-proven pattern): argv[1] = existing exec dir -> the
    # Meter reloads its ledger and completed cells dedup-replay free; semantics
    # unchanged. No-arg -> fresh dir.
    resume = sys.argv[1] if len(sys.argv) > 1 else None
    if resume:
        out = Path(resume)
        assert out.exists() and (out / 'LEDGER.jsonl').exists()
    else:
        (B / 'stage_c_tgv_runs').mkdir(parents=True, exist_ok=True)
        out = B / 'stage_c_tgv_runs' / f'EXEC_{time.strftime("%H%M%S")}'
        out.mkdir(parents=False, exist_ok=False)
    lock = open(out / '.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    meter = Meter(ledger_path=out / 'LEDGER.jsonl',
                  max_calls=MAX_CALLS, max_guaranteed_actual=MAX_TOKENS)
    qm = QuotaMeter(meter)
    factory = AdapterFactory(qm)
    tasks = load_tgv_tasks()
    results, t0 = [], time.time()

    def writer(rec, full):
        results.append(rec)
        (out / f'{rec["task"]}-{rec["arm"]}-r{rec["rep"]}.json').write_text(
            json.dumps(full, ensure_ascii=False, indent=1, default=str))
        (out / 'PARTIAL.json').write_text(json.dumps(
            dict(results=results, quota=qm.__dict__), ensure_ascii=False,
            indent=1, default=str))

    try:
        for rep in (1, 2):
            for tid in TASKS:
                data = tasks[tid]
                tgt = mcf_target(data)
                # shared prefix under one namespace: full pi0 pass, arms dedup-replay
                factory.run_id = f'TGV-shared-{tid}-r{rep}'
                pre = R9.run_r9('Static-Parallel', data, {},
                                budget_tokens=RUN_BUDGET,
                                adapter_factory=factory)
                print(f'[shared-{tid}-r{rep}] {len(pre["calls"])} calls '
                      f'{pre["tokens"]} tok target={tgt}({MCF_TARGET_KIND}) '
                      f'status={pre["status"]}', flush=True)
                for arm in ARMS:
                    r = R9.run_r9(arm, data, {}, budget_tokens=RUN_BUDGET,
                                  adapter_factory=factory)
                    tgt_calls = [(c['model'], c['success'])
                                 for c in r['calls'] if c['node'] == tgt]
                    rec = dict(task=tid, arm=arm, rep=rep, status=r['status'],
                               tokens=r['tokens'], n_calls=len(r['calls']),
                               makespan=r['makespan'],
                               terminal_stats=r['terminal_stats'],
                               mcf_state=classify_mcf_state(tgt_calls),
                               target_calls=tgt_calls,
                               z_ops=[rd['z_op'] for rd in r['rounds']
                                      if rd['z_op'] != 'KEEP'])
                    writer(rec, r)
                    print(f'  {arm:16s} {tid} r{rep} {r["status"]:32s} '
                          f'{rec["mcf_state"]:20s} tgt={tgt_calls}', flush=True)
        # S3-CONTROL cell: pre-registered first task (by ID order), 4 arms,
        # 1 rep, descriptive (v2.2 §5); independent namespace = full price
        tid = TASKS[0]
        data = tasks[tid]
        factory.run_id = f'TGV-S3-{tid}'
        pre = R9.run_r9('Static-Parallel', data, {},
                        budget_tokens=RUN_BUDGET, adapter_factory=factory)
        print(f'[S3-{tid}] prefix {len(pre["calls"])} calls status={pre["status"]}',
              flush=True)
        for arm in ARMS:
            r = R9.run_r9(arm, data, {}, budget_tokens=RUN_BUDGET,
                          adapter_factory=factory)
            tgt = mcf_target(data)
            tgt_calls = [(c['model'], c['success'])
                         for c in r['calls'] if c['node'] == tgt]
            rec = dict(task=tid, arm=arm, rep='S3', status=r['status'],
                       tokens=r['tokens'], n_calls=len(r['calls']),
                       makespan=r['makespan'],
                       terminal_stats=r['terminal_stats'],
                       mcf_state='S3-CONTROL',
                       target_calls=tgt_calls,
                       z_ops=[rd['z_op'] for rd in r['rounds']
                              if rd['z_op'] != 'KEEP'])
            writer(rec, r)
            print(f'  {arm:16s} {tid} S3 {r["status"]:32s} '
                  f'tgt={tgt_calls}', flush=True)
        final = dict(batch='stage_c_tgv_v1', status='COMPLETE', results=results,
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
                 meter=meter.summary()), ensure_ascii=False, indent=1, default=str))
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
