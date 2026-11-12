"""Child process for DAMJS_PILOT_54: runs ONE execution with the frozen executor.

Reads env: APILOT_ARM, APILOT_SCEN, APILOT_REP, APILOT_DEADLINE, APILOT_OUT,
           APILOT_PROGRESS, APILOT_CANCEL, APILOT_BATCH, APILOT_REAL
Writes: APILOT_OUT (result json incl. identity block), APILOT_PROGRESS (jsonl)

NOTE: the frozen executor has no agent layer, so the DAMJS arm here exercises
Z / R / Π / deadline-gating / repeat-guard only — NOT the X' migration action.
"""
import json, os, sys, time, hashlib
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import stage_d_executor as SDE   # frozen, read-only import
from damsj_engine import Scheduler, Agent, NodeState, Clock, GAIN_TABLE, reliable

E = os.environ
ARM = E['APILOT_ARM']; SCEN = E['APILOT_SCEN']; REP = int(E['APILOT_REP'])
DEADLINE = float(E['APILOT_DEADLINE']); OUT = E['APILOT_OUT']
PROGRESS = E['APILOT_PROGRESS']; CANCEL = E['APILOT_CANCEL']
BATCH = E['APILOT_BATCH']; REAL = E.get('APILOT_REAL') == '1'


def w(rec):
    with open(PROGRESS, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(65536), b''):
            h.update(c)
    return h.hexdigest()


def identity_block():
    mf = json.load(open(HERE / 'DAMJS_BATCH_MANIFEST.json'))
    comps = {c['role'] + ':' + os.path.basename(c['path']): c['sha256']
             for c in mf['components'] if not c.get('missing')}
    return dict(batch_id=BATCH, components=comps,
                manifest_sha256=sha_file(HERE / 'DAMJS_BATCH_MANIFEST.json'),
                prereg_sha256=sha_file(HERE / 'DAMJS_V0_2_1.md'),
                verified_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                n_components=len(comps))


def make_damsj_policy(ex, hist, clock, started):
    """Return a policy(node,sig) closure backed by the DAMJS decision rules."""
    def policy(node, sig):
        t_rem = DEADLINE - (clock.now() - started)
        if os.path.exists(CANCEL):
            return []
        if not sig:                                  # 无异常 → 不干预
            return []
        fam = list(sig.values())[0]
        if t_rem <= 0:                               # L3
            return []
        # 映射 DAMJS 候选 → 冻结执行器的动作元组
        if fam == 'format':
            if hist.forbidden('FMT', 'Z_format'):
                return []
            mu, sd, rel = GAIN_TABLE[('format', 'Z_format')]['mu'], \
                          GAIN_TABLE[('format', 'Z_format')]['sd'], \
                          reliable('format', 'Z_format')
            if rel and mu - sd > 0:
                w(dict(ev='damjs_decide', node=node, fam=fam, act='format_repair', t_rem=round(t_rem, 1)))
                return [('format_repair', 'FMT')]
            return []
        if fam == 'structure':
            if node in SDE.D2.REPAIR_LIB and not hist.forbidden(node, 'Z_structure'):
                g = GAIN_TABLE[('structure', 'Z_structure')]
                if reliable('structure', 'Z_structure') and g['mu'] - g['sd'] > 0:
                    w(dict(ev='damjs_decide', node=node, fam=fam, act='structure_repair', t_rem=round(t_rem, 1)))
                    return [('structure_repair', node)]
            if not hist.forbidden(node, 'R'):
                w(dict(ev='damjs_decide', node=node, fam=fam, act='rerun_asis', t_rem=round(t_rem, 1)))
                return [('rerun_asis', node)]
            return []
        return []                                     # model_suspect: 不可靠 → 不动作
    return policy


def main():
    cfg = SDE.load_config(HERE / 'stage_d_executor_config.json')
    cfg['deadline_s']['default'] = DEADLINE       # 真实强制截止期（由父包装器执行）
    cfg['deadline_s'][SCEN] = DEADLINE
    clock = SDE.make_clock(REAL, cfg['mock']['scale'])
    state_dir = HERE / 'damsj_pilot_runs' / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)
    out_dir = Path(OUT).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    gb = SDE.GlobalBudget(cfg['global']['calls'], cfg['global']['yuan'],
                          cfg['global'].get('tokens'), state_dir)
    slots = SDE.SlotManager(cfg['slots'], clock)
    store = SDE.RunStore(state_dir, out_dir)
    provider = (SDE.RealProvider(clock, slots, transport_fn=SDE.stage_d_real_transport)
                if REAL else SDE.MockProvider(clock, slots, cfg, SCEN, REP))
    ex = SDE.FinalExec(ARM if ARM != 'DAMJS' else 'Proposed-Dynamic',
                       SCEN, REP, cfg, clock, gb, slots, provider, store, dry_run=not REAL)

    if ARM == 'DAMJS':
        from damsj_engine import History
        hist = History()
        orig_policy = ex.policy
        started = [None]

        def wrapped_policy(node, sig):
            if started[0] is None:
                started[0] = clock.now()
            return make_damsj_policy(ex, hist, clock, started[0])(node, sig)
        ex.policy = wrapped_policy

    w(dict(ev='exec_start', arm=ARM, scen=SCEN, rep=REP, deadline=DEADLINE, real=REAL))
    t0 = time.time()
    ret = ex.run()                       # finish() 的返回记录才是权威结果
    ret = ret if isinstance(ret, dict) else {}
    score = ret.get('score') or {}
    rec = dict(arm=ARM, scenario=SCEN, rep=REP, deadline_s=DEADLINE,
               status=ret.get('status') or ('COMPLETE' if not ex.deadline_hit else 'INCOMPLETE_DEADLINE'),
               tp=ret.get('tp', score.get('tp')),
               slot_success=score.get('slot_success'),
               makespan_s=ret.get('makespan_s'),
               cost_yuan=ret.get('actual_cash_yuan'),
               actions=len(ret.get('actions') or []),
               anomalies=len(ret.get('anomalies') or []),
               decisions=len(ret.get('decisions') or []),
               final_states=ret.get('final_states'),
               wall_s=round(time.time() - t0, 1),
               migration_count=0,       # 冻结执行器无智能体层 → X' 不可执行
               identity=identity_block())
    with open(OUT, 'w') as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    w(dict(ev='exec_end', arm=ARM, scen=SCEN, rep=REP, wall=rec['wall_s'], tp=rec['tp']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
