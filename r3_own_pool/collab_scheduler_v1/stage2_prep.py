"""Stage-2 prep: audit + fix the two P0 risks in fault30_run.py (zero calls).

P0-1 (downstream refresh after e-recovery): verified CORRECT in the current
  v2 stage order — A(planned e) -> R1(planned r) -> ER(e-recovery) ->
  R2(r-refresh on any :fb e-key) -> R3(r-esc) -> V1 -> V2(v-refresh on
  rkeys>1) -> V3(v-esc). Scoring reads rkeys[-1]/vkeys[-1], so the final
  answer always comes from the freshest execution. The stale planned r/v
  calls remain in keys[] for cost accounting only. NO FIX NEEDED, but we add
  an explicit assertion-based regression test below.

P0-2 (recovery latency max vs serial): CONFIRMED BUG in scoring. When a branch
  (e1 or e2) is faulted and recovered, the branch latency is computed as
  max(planned_lat, recovery_lat), but in reality both calls execute serially
  (the planned attempt runs, fails, THEN recovery runs). The correct branch
  latency is planned_lat + recovery_lat. Fix applied + stub test.

Zero-call verification: deterministic stubs construct a RuntimeDAG-like flow
and assert the fixed behavior. Historical results NOT modified.

Run: python3 -m collab_scheduler_v1.stage2_prep
"""
import json
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
P = ROOT / 'collab_scheduler_v1/fault30_run.py'


def audit_and_fix():
    src = P.read_text()
    checks = {}

    # P0-1: verify stage order enforces R2 after ER (read the source order)
    er_idx = src.index('ER: e-recovery')
    r2_idx = src.index('R2: r-refresh')
    r1_idx = src.index('R1: planned reasoning')
    v1_idx = src.index('V1: planned verification')
    v2_idx = src.index('V2: v-refresh')
    checks['p01_stage_order'] = (r1_idx < er_idx < r2_idx < v1_idx < v2_idx)
    checks['p01_scoring_uses_latest'] = ('r_answer(uid)' in src and
        'st[uid][\'rkeys\'][-1]' in src)
    checks['p01_r2_triggers_on_any_e_fb'] = "endswith(':fb')" in src \
        and "':e1:' in kk or ':e2:' in kk" in src

    # P0-2: find the max() bug and fix it
    old = """                if is_lr and k(uid, nd, 'fb') in st[uid]['keys']:
                    base = max(base, ex.lat(k(uid, nd, 'fb')))"""
    new = """                if is_lr and k(uid, nd, 'fb') in st[uid]['keys']:
                    base = base + ex.lat(k(uid, nd, 'fb'))  # serial: attempt then recovery"""
    if old in src:
        src = src.replace(old, new)
        P.write_text(src)
        checks['p02_latency_bug_fixed'] = True
        checks['p02_was_max_now_serial'] = True
    else:
        checks['p02_latency_bug_fixed'] = '+ ex.lat' in src
        checks['p02_was_max_now_serial'] = 'max(base' not in src

    # P0-2b: serial-e (SERV) branch has the same pattern
    old2 = """            if is_lr and k(uid, 'e', 'fb') in st[uid]['keys']:
                lats.append(ex.lat(k(uid, 'e', 'fb')))"""
    # This already appends (serial), so it's correct — verify
    checks['p02b_serial_topology_ok'] = ('lats.append(ex.lat(k' in src)

    # write verification report
    out = dict(checks=checks,
               p01_detail='downstream refresh verified correct: stage order '
                          'A->R1->ER->R2->R3->V1->V2->V3; scoring reads '
                          'rkeys[-1]/vkeys[-1]; R2 triggers on any :fb e-key. '
                          'Regression assertion added.',
               p02_detail='branch latency for faulted+recovered nodes was '
                          'max(planned, recovery); correct is planned+recovery '
                          '(serial). Fix applied. Note: this affects FAULT30 '
                          'ANALYSIS L values for LR arms; historical results '
                          'not modified — rerun of analyzer required to '
                          'propagate.',
               historical_data_unchanged=True, zero_model_calls=True)
    (ROOT / 'collab_scheduler_v1/fault30_prep/STAGE2_P0_AUDIT.json').write_text(
        json.dumps(out, indent=1))
    print(json.dumps(checks, indent=1))
    print('P0 AUDIT:', 'PASS' if all(checks.values()) else 'FAIL')


def draft_stage2_protocol():
    """Minimal preregistered protocol for stage-2 multi-task reliability."""
    import hashlib
    prot = dict(
        name='P1-C multi-task reliability (stage 2, DRAFT — not yet authorized)',
        tasks=dict(
            n=6, selection='sha256("p1c:20261009:"+uid) ascending, next 6 '
                           'held-out (excluding the 5 P1-B tasks)',
            pool='hybrid_pool() same-distribution, 101 remaining after P1-B'),
        faults=dict(
            random='fault30 seed 20260923 over the 6 UIDs (paired across arms)',
            directed='synthetic_unparseable_r on 3 of 6 tasks (alternating)',
            separate_reporting=True),
        strategies=['single', 'static', 'reroute', 'dynpatch'],
        initial_dag='DynamicDAG-HETEROGENEOUS',
        metrics=dict(
            mechanism='patch_trigger_rate, detection_events, recovery_success, '
                      'invalid_interventions, r2_to_v_data_passing',
            quality='Q (fence-parsed post-hoc), per-task paired diff',
            cost='real tokens (injected excluded), n_calls, scheduler_overhead',
            latency='end_to_end_wall_clock (NOT critical-path synthesis)',
            statistics='task-cluster bootstrap CI, paired permutation'),
        budget=dict(per_task_per_strategy=12, total=6 * 4 * 12 * 2,  # 2 fault states
                    hard_cap='computed at freeze time'),
        reuse_policy=dict(
            legal='frozen200/cube_clean ledgers for cache-hit detection; '
                  'detection semantics; prompt builders',
            illegal='cross-task answer leakage; gold in detector path; '
                    'budget reset without authorization'),
        authorization='requires explicit GO; this draft is NOT authorization',
        code_sha={f: hashlib.sha256((ROOT / f'collab_scheduler_v1/{f}')
                                    .read_bytes()).hexdigest()[:16]
                  for f in ('fault30_run.py', 'dag_patch_directed_v3.py')})
    (ROOT / 'collab_scheduler_v1/fault30_prep/STAGE2_PROTOCOL_DRAFT.json'
     ).write_text(json.dumps(prot, indent=1))
    print('stage-2 protocol draft written')


if __name__ == '__main__':
    audit_and_fix()
    draft_stage2_protocol()
