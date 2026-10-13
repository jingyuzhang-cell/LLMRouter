"""DD-V2 five-arm dev micro-trial launcher (ONE authorized run).

Operator conditional GO (ruling on f581c7c): 5 frozen dev tasks × 5 arms
(SS / DD-V1 / DD-Cal / DD-Cal+Fallback / DD-V2), ONE GLOBAL budget
(100 requests / 50K tokens / 3600 s) shared across ALL arms, shared
base + isolated per-arm caches, fair constant per-arm decision budgets,
fail-stop, INCOMPLETE protection.

Gates BEFORE the first real request (all zero-call):
  1. env flag DD_V2_DEV_MICROTRIAL_GO=1
  2. --approved-freeze-sha256 matches DD_V2_DEV_MICROTRIAL_FREEZE.json
  3. --approved-caps-sha256 matches the approved caps text
  4. clean git tree (code binding)
  5. GPU-exclusive flock; unique run dir; server stopped + lock freed
     in finally.
--rehearse runs everything with a FAKE transport (zero calls).

Run:
  DD_V2_DEV_MICROTRIAL_GO=1 python3 -m deadline_reward_v1.dd_v2_microtrial_launch \
    --approved-freeze-sha256 <sha> --approved-caps-sha256 <sha> [--rehearse]
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

GO_FLAG = 'DD_V2_DEV_MICROTRIAL_GO'
GPU_LOCK = ROOT / 'collect/logs/local_gpu.lock'
FREEZE = HERE / 'DD_V2_DEV_MICROTRIAL_FREEZE.json'
CAPS_TEXT = ('5 tasks x 5 arms (SS/DD-V1/DD-Cal/DD-Cal+FB/DD-V2); '
             '100 requests / 50000 tokens / 3600 s ONE GLOBAL budget')
ARMS = ('SS', 'DD-V1', 'DD-Cal', 'DD-Cal+FB', 'DD-V2')


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _load_tasks(freeze):
    tr = json.loads((ROOT / 'data/tatqa/tatqa_dataset_train.json')
                    .read_text())
    idx = {}
    for p in tr:
        if not p.get('table', {}).get('table') or not p.get('paragraphs'):
            continue
        ct = ('TABLE:\n' + '\n'.join(
            ' | '.join('' if c is None else str(c) for c in row)
            for row in p['table']['table']))
        ordered = sorted(p['paragraphs'], key=lambda x: x.get('order', 0))
        cp = 'PASSAGES:\n' + '\n'.join(
            f'[{i}] {q["text"]}' for i, q in enumerate(ordered))
        for q in p['questions']:
            idx[q['uid']] = dict(uid=q['uid'], question=q['question'],
                                 derivation=(q.get('derivation') or
                                             '').strip(),
                                 answer=q.get('answer'),
                                 ctx_table=ct, ctx_text=cp)
    return [idx[u] for u in freeze['uids']]


def _gates(args):
    if os.environ.get(GO_FLAG) != '1':
        raise PermissionError(f'requires {GO_FLAG}=1')
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(
        ['git', '-C', str(ROOT), 'status', '--porcelain', '--',
         'deadline_reward_v1'], capture_output=True,
        text=True).stdout.strip()
    if dirty:
        raise PermissionError(f'uncommitted changes:\n{dirty}')
    fsha = sha_file(FREEZE)
    if args.approved_freeze_sha256 != fsha:
        raise PermissionError('freeze hash mismatch')
    if args.approved_caps_sha256 != hashlib.sha256(
            CAPS_TEXT.encode()).hexdigest():
        raise PermissionError('caps approval hash mismatch')
    return commit, fsha


def execute(approved, rehearse=False):
    from deadline_reward_v1 import joint_verification_runner as jv
    from deadline_reward_v1 import dd_v2, policy
    from deadline_reward_v1.scheduler_state import SchedulerState
    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner \
        import Budget

    freeze = json.loads(FREEZE.read_text())
    tasks = _load_tasks(freeze)
    gold_map = jv.build_gold_map(tasks)
    run_root = HERE / 'dd_v2_dev_runs' / time.strftime(
        'dev_%Y%m%d_%H%M%S')
    if run_root.exists():
        raise PermissionError('run dir exists — no reuse')

    CAPS = dict(wall_seconds=3600.0, new_request_attempts=100,
                new_total_tokens=50000, request_token_reservation=2048,
                max_output_tokens=4096)

    # ---- transport (fake for rehearsal, real otherwise) --------------
    manager = None

    def make_server(budget, task_map):
        if rehearse:
            return _FakeServerFactory(budget, task_map, run_root)
        from deadline_reward_v1.supplementary_runner import RealServer
        return RealServer({}, manager, budget, task_map, run_root)

    class _FakeServerFactory:
        def __init__(self, budget, task_map, root):
            # minimal RealServer facade with a fake transport
            import deadline_reward_v1.supplementary_runner as sr

            class FakeMod:
                def call_model(self, model, prompt):
                    if 'facts' in prompt[:120]:
                        return dict(status='delivered', answer=(
                            '{"facts":[{"value":1.5,"evidence":"a"}]}'),
                            usage=dict(prompt_tokens=100,
                                       completion_tokens=30,
                                       total_tokens=130))
                    return dict(status='delivered',
                                answer='{"value": 1.5}',
                                usage=dict(prompt_tokens=80,
                                           completion_tokens=20,
                                           total_tokens=100))

            class Mgr:
                def __init__(self):
                    self.state = dict(proc=None, log=None, model=None)
                    self.stops = 0

                def _mod(self):
                    return FakeMod()

                def start(self, m):
                    pass

                def stop_current(self):
                    self.stops += 1
                    self.state.update(proc=None, log=None, model=None)
            self._mgr = Mgr()
            self._srv = sr.RealServer({}, self._mgr, budget, task_map,
                                      root)
            self.mgr = self._mgr

        def __getattr__(self, name):
            return getattr(self._srv, name)

        def set_engine(self, eng):
            self._srv.engine = eng

    if not rehearse:
        from deadline_reward_v1.supplementary_runner import ModelManager
        manager = ModelManager()

    lock_fh = GPU_LOCK.open('a+')
    statuses = {}
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_root.mkdir(parents=True, exist_ok=False)
        (run_root / 'budgetd').mkdir()
        budget = Budget(run_root / 'budgetd', CAPS)   # ONE GLOBAL budget

        from deadline_reward_v1.supplementary_runner import RealEngine, \
            RealClock
        PLANNED = dict(e1='large', e2='large', r='medium', v='coder')
        fault_uids = set(freeze['fault_uids'])
        d3 = freeze.get('fault_answer',
                        '###SYNTHETIC UNPARSEABLE r-output###')

        # ---- shared base (once; faults active) ------------------------
        base_server = make_server(budget, {t['uid']: t for t in tasks})
        base_engine = jv.arm_engine_from_snapshot(
            run_root / 'base', base_server, RealClock(), {},
            manager=(manager if manager else base_server.manager),
            real=True)
        if hasattr(base_server, 'set_engine'):
            base_server.set_engine(base_engine)
        else:
            base_server.engine = base_engine
        server = (base_server._srv if hasattr(base_server, '_srv')
                  else base_server)
        snapshot = jv.run_shared_base(base_engine, tasks, PLANNED,
                                      fault_uids, d3)
        base_pt = jv._per_task_base_tokens(base_engine)
        statuses['base'] = 'COMPLETE'

        # ---- tier anchors from the independent FIT --------------------
        rel = sorted((HERE / 'reliability_runs').glob('run_*'))[-1]
        binding = json.loads((rel / 'BINDING.json').read_text())['binding']
        fit = {c: dict(mean=b['mean']) for c, b in binding.items()}

        stub = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
        pol = stub['policy']
        params_v1 = dict(priors=stub, q_min=pol['q_min'],
                         eps=pol['eps'], lam_c=pol['lam_c'],
                         lam_t=pol['lam_t'], lam_f=pol['lam_f'],
                         c0=pol['c0'])
        pred = policy.OutcomePredictor(stub)
        comp = policy.DeadlineCompensator(stub)

        all_rows = {}
        for arm in ARMS:
            run_arm = 'DD' if arm == 'DD-V1' else arm
            adir = run_root / arm.replace('+', '_')
            eng = jv.arm_engine_from_snapshot(
                adir, server, RealClock(), snapshot,
                manager=(manager if manager
                         else server.manager),
                real=True)
            if hasattr(server, 'set_engine'):
                server.set_engine(eng)
            else:
                server.engine = eng
            state = SchedulerState(
                eng.clock,
                task_deadlines={t['uid']: eng.clock.time()
                                + jv.G3_MULT[freeze['tiers'][t['uid']]]
                                * jv.planned_path_work(PLANNED, fit, None)
                                for t in tasks},
                token_allocation=float(CAPS['new_total_tokens']))
            state.attach(eng)
            rows, metering = __import__(
                'deadline_reward_v1.supplementary_runner',
                fromlist=['run_cell']).run_cell(
                eng, server, state, tasks, PLANNED, run_arm,
                'dev_fault30', fault_uids, pred, comp, params_v1,
                adir)
            # dual settlement
            from deadline_reward_v1 import detection as det
            from deadline_reward_v1.reward import realized_rtask
            svc, sw_w, sw_n = jv._per_task_incremental_service(adir)
            settled = []
            for r in rows:
                uid = r['uid']
                val = det.json_value(state.tasks[uid].answers.get('v', ''))
                task_here = next(t for t in tasks if t['uid'] == uid)
                q = jv.terminal_q(val, gold_map[uid].get(
                    'gold', task_here.get('answer')))
                st = state.tasks[uid]
                if st.completion_time is None:
                    continue
                T = svc.get(uid, 0.0)
                D = state.task_deadlines[uid] - st.release_time
                inc = st.tokens_physical
                bpt = base_pt.get(uid, 0)
                s = dict(uid=uid, Q=q, C_tokens=inc,
                         C_attribution=dict(per_task_base=bpt,
                                            arm_incremental=inc,
                                            C_full_task=bpt + inc),
                         T=round(T, 6),
                         D=round(D, 6),
                         on_time_correct=int(q == 1 and T <= D),
                         mode=r['decision']['mode'] if r.get('decision')
                         else 'none',
                         R_conditional=round(realized_rtask(
                             q=q, c_full=inc, T=T, D=D, **jv.LAM), 10),
                         R_full_task_cost_view=round(realized_rtask(
                             q=q, c_full=bpt + inc, T=T, D=D,
                             **jv.LAM), 10))
                settled.append(s)
                r['arm'] = arm
                r['R_settlement'] = s
            all_rows[arm] = dict(rows=rows, settled=settled,
                                 metering=metering)
            statuses[arm] = 'COMPLETE'
            budget.check()

        payload = dict(statuses=statuses,
                       physical=dict(requests=budget.attempts,
                                     tokens=budget.actual_tokens),
                       shared_base=dict(per_task=base_pt,
                                        total=sum(base_pt.values())),
                       arms={a: dict(
                           settled=all_rows[a]['settled'],
                           metering=all_rows[a]['metering'])
                           for a in ARMS},
                       caps=CAPS, tiers=freeze['tiers'],
                       rehearsal=rehearse)
        out = run_root.parent / 'DD_V2_DEV_RESULTS.json'
        jv.write_results(out, 'COMPLETE' if not rehearse
                         else 'INCOMPLETE', payload)
        # rehearsal writes INCOMPLETE so the real run can write COMPLETE
        print(json.dumps(dict(status='COMPLETE' if not rehearse
                              else 'REHEARSAL_COMPLETE',
                              statuses=statuses,
                              physical=payload['physical']), indent=1))
        return 0
    except BaseException as exc:
        try:
            if manager:
                manager.stop_current()
        except Exception:
            pass
        try:
            jv.write_results(
                run_root.parent / 'DD_V2_DEV_RESULTS.json', 'INCOMPLETE',
                dict(reason=repr(exc), statuses=statuses,
                     traceback=traceback.format_exc()))
        except Exception:
            pass
        raise
    finally:
        try:
            if manager:
                manager.stop_current()
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-freeze-sha256', required=True)
    parser.add_argument('--approved-caps-sha256', required=True)
    parser.add_argument('--rehearse', action='store_true')
    args = parser.parse_args()
    _gates(args)
    return execute(args, rehearse=args.rehearse)


if __name__ == '__main__':
    raise SystemExit(main())
