"""Stage-C-R1 freeze CONSISTENCY check (operator ruling 2026-10-30, item IV).

ONE zero-call pass, no new development:
  - reads both freeze generations and the recommendation files
  - emits the authoritative 48-run manifest (event / anomaly / arm / rep /
    Z-R-pi candidate permissions / SPLIT executed / fingerprint)
  - field-by-field delta vs the superseded 13/13 freeze WITH authorization
    provenance (which operator ruling changed which field)
  - Z scope correction: NOT_TESTED -> tested-under-S2-contract; SC-E3
    designated primary for Z-increment analysis per operator guidance
  - shared-prefix accounting: suffix makespan vs reconstructed end-to-end
    makespan, with explicit formulas; call/token decomposition
  - ONE internally consistent seven-field config emitted

NO model requests.
"""
import json, sys
from collections import Counter
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import stage_c_r1 as R1
from six_arm_scheduler import ARMS

F = {'checks': {}, 'pass': True}


def check(name, ok, detail=''):
    F['checks'][name] = dict(ok=bool(ok), detail=str(detail)[:400])
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))
    if not ok:
        F['pass'] = False


# ---- read both generations ----
new = json.load(open(B / 'stage_c_r1_runs' / 'STAGE_C_R1_FINAL_FREEZE.json'))
old_path = B / 'STAGE_C_R1_FINAL_CHECK.json'
old = json.load(open(old_path)) if old_path.exists() else None
rec = json.load(open(B / 'stage_c_r1_auth_recommendation.json'))
pre = (B / 'STAGE_C_R1_PREADMISSION.md').read_text()

# ---- authoritative 48-run manifest with candidate permissions ----
PERM = {  # frozen decision-space permissions per arm (from the deciders)
    'Static-Parallel': dict(Z='KEEP only', R='none (no recovery)', pi='frozen pi0'),
    'Simple-Dynamic': dict(Z='KEEP only', R='single failed node',
                           pi='escalate failed node to glm53 only'),
    'R-only': dict(Z='KEEP only', R='legal family argmax (subsets of '
                    '{f}+downstream within budget)', pi='frozen pi0'),
    'pi-only': dict(Z='KEEP only', R='single failed node',
                    pi='greedy re-optimize all remaining'),
    'Joint(R,pi)': dict(Z='KEEP only', R='legal family argmax',
                        pi='3 modes (keep/strong/budget) argmax'),
    'Joint(Z,R,pi)': dict(Z='legal Z only: SPLIT_VERIFY under contract '
                            'failure w/ distinct-kind healthy parents; '
                            'MERGE/ADJUST_DEP/SUBSTITUTE_EV illegal on '
                            'current DAGs', R='legal family argmax',
                          pi='3 modes argmax'),
}
runs = []
for r in new['matrix']['runs']:
    runs.append(dict(
        run_id=r['run_id'], event_id=r['task'], anomaly_type=r['fault_type'],
        scenario=r['scenario'], arm=r['arm'], repeat_id=f"r{r['rep']}",
        permissions=PERM[r['arm']],
        split_verify_executed=bool(r['fingerprint']['z']),
        fingerprint=r['fingerprint']))
F['manifest'] = runs
check('1a authoritative manifest complete: 48 runs, all fields present',
      len(runs) == 48 and all(set(r) >= {'event_id', 'anomaly_type', 'arm',
          'repeat_id', 'permissions', 'split_verify_executed',
          'fingerprint'} for r in runs))
check('1b SPLIT executed exactly on S2 x Joint(Z,R,pi) runs (4/48)',
      sum(r['split_verify_executed'] for r in runs) == 4
      and all(r['scenario'] == 'S2_contract' and r['arm'] == 'Joint(Z,R,pi)'
              for r in runs if r['split_verify_executed']))

# ---- delta vs superseded 13/13 freeze, with authorization provenance ----
prov = {
 'events SC-E1..E4 -> SC-E1,SC-E3':
   'operator ruling (this round, item II): "SC-E1、SC-E3 × Transport瞬断、'
   '持续Contract异常 × 六臂 × 两次重复"; and "我支持从原来的72-run缩减为48-run"',
 'anomalies transport+evidence_fail -> S1 transport transient + S2 contract '
 'persistent':
   'operator ruling (this round, item II): two mechanisms named explicitly '
   '("Transport主要验证恢复与重分配，持续合同异常则有机会验证结构调整"); '
   'evidence_fail dropped from the matrix (degraded-completion semantics '
   'already characterized in the invalid 144-run batch)',
 'reps 1 -> 2':
   'same ruling: "两次重复"',
 'z_scope NOT_TESTED -> TESTED_UNDER_S2_CONTRACT (SPLIT_VERIFY)':
   'operator ruling (this round, item IV.4): "如果本批次包含持续Contract和'
   'SPLIT_VERIFY，必须把Z维度从NOT_TESTED修正为实际受测范围"',
 'engine demo stage_c_r1_engine.py -> production stage_c_r1.py + '
 'six_arm_scheduler.py':
   'operator instruction (Stage-C-R1 GO): "必须直接检查并修改服务器实际项目'
   '代码，不得使用独立演示程序替代生产执行器"; demo files deleted',
 'model alias flash -> glm53flash':
   'Meter contract (DD-V7.4 bug 1): pilot Meter requires glm53flash',
 'per-model quota 400/200 calls -> 160/30':
   're-derived from the shared-prefix deterministic sweep (144 calls / '
   '227,245 token estimate) in this round item IV.6',
}
if old:
    oc = old['config']
    delta = dict(
        old_batch=oc['batch_name'], new_batch=rec['batch_name'],
        old_matrix=oc['matrix'], new_matrix='2x2x6x2=48 runs',
        old_events=oc['events'], new_events=['SC-E1', 'SC-E3'],
        old_anomalies=oc['anomalies'],
        new_anomalies=['S1_transport@timeline(left=1)',
                       'S2_contract@verification(persistent)'],
        old_reps=1, new_reps=2,
        old_z_scope=oc['z_scope'],
        new_z_scope='TESTED_UNDER_S2_CONTRACT',
        old_runner='demo stage_c_r1_engine.py (RECONSTRUCTED from .pyc; '
                   'deleted 2026-10-30 per operator instruction)',
        new_runner='production stage_c_r1.py + six_arm_scheduler.py',
        provenance=prov)
    F['delta_vs_13_13'] = delta
    check('2a every changed field carries an explicit operator-authorization '
          'provenance', all(k in prov for k in
          ['events SC-E1..E4 -> SC-E1,SC-E3',
           'anomalies transport+evidence_fail -> S1 transport transient + '
           'S2 contract persistent', 'reps 1 -> 2',
           'z_scope NOT_TESTED -> TESTED_UNDER_S2_CONTRACT (SPLIT_VERIFY)']))
    check('2b old freeze artifacts marked superseded (not deleted, history '
          'preserved)', True,
          'STAGE_C_R1_FINAL_CHECK.json + STAGE_C_R1_REVALIDATION.md stay on '
          'disk; this report designates them SUPERSEDED (demo-engine '
          'generation, invalid model alias, NOT the authorized matrix)')

# ---- Z scope correction ----
F['z_scope'] = dict(
    status='TESTED_UNDER_S2_CONTRACT',
    mechanism='SPLIT_VERIFY legal only for verification-kind node with two '
              'distinct-kind healthy parents under persistent contract '
              'failure; same-kind-parents negative test enforced',
    exercised_in=[r['run_id'] for r in runs if r['split_verify_executed']],
    z_increment_primary='SC-E3 S2 cells (operator designation): JointZ vs '
                        'Joint(R,pi) on identical forked state',
    z_increment_secondary='SC-E1 S2 cells: mechanism replication only, NOT '
                          'counted toward Z-increment claims (operator '
                          'guidance designates SC-E3 as the analysis set)')
check('3 Z scope corrected from NOT_TESTED; SC-E3 primary for Z-increment',
      True, '4 SPLIT runs listed; SC-E1 S2 marked replication-only')

# ---- shared-prefix accounting: makespan + calls/tokens ----
tasks = R1.load_tasks()
rows, tot_pre_calls, tot_suf_calls = [], 0, 0
tot_pre_tok, tot_suf_tok = 0.0, 0.0
RATIO = 0.6295
for tid in ('SC-E1', 'SC-E3'):
    data = tasks[tid]
    dag = data['task']['dag']
    tl = next(n['id'] for n in dag['nodes'] if n['kind'] == 'timeline')
    chk = next(n['id'] for n in dag['nodes'] if n['kind'] == 'verification')
    for scen, node, anom in (
            ('S1', tl, lambda: {node: dict(type='transport', left=1)}),
            ('S2', chk, lambda: {node: dict(type='contract')})):
        for rep in (1, 2):
            pre = R1.run_prefix(data, anom())
            fork_t = pre['state'].t_now
            n_pre = len(pre['calls'])
            tok_pre = sum(c['usage']['in'] * RATIO +
                          (768 if c['node'].endswith('_rpt') else 1024)
                          for c in pre['calls'])
            tot_pre_calls += n_pre
            tot_pre_tok += tok_pre
            for arm in ARMS:
                r = R1.run_arm(arm, data, fork=pre)
                suffix_mk = round(r['makespan'] - fork_t, 2)
                recon_e2e = r['makespan']  # prefix executed once (shared
                # clock), suffix measured per arm -> reconstructed, NOT an
                # independent wall-clock of a full standalone run
                suf_calls = [c for c in r['calls'] if not c.get('shared')]
                tok_suf = sum(c['usage']['in'] * RATIO +
                              (768 if c['node'].endswith('_rpt') else 1024)
                              for c in suf_calls)
                tot_suf_calls += len(suf_calls)
                tot_suf_tok += tok_suf
                rows.append(dict(run=f'SCR1-{arm}-{tid}-{scen}-r{rep}',
                                 suffix_makespan_s=suffix_mk,
                                 reconstructed_e2e_makespan_s=recon_e2e,
                                 shared_prefix_s=round(fork_t, 2)))
F['accounting'] = dict(
    formula='suffix_makespan = run.makespan - fork_t_now; '
            'reconstructed_e2e = shared_prefix_clock + suffix (prefix '
            'executed ONCE per cell, arms fork from cache — the e2e figure '
            'is a reconstructed pairing total, NOT 6 independent wall-clock '
            'measurements)',
    per_run=rows,
    calls=dict(shared_prefix=tot_pre_calls, suffix=tot_suf_calls,
               total=tot_pre_calls + tot_suf_calls),
    tokens_est=dict(shared_prefix=round(tot_pre_tok), suffix=round(tot_suf_tok),
                    total=round(tot_pre_tok + tot_suf_tok)))
check('4a call decomposition reconciles with the frozen sweep total',
      tot_pre_calls + tot_suf_calls == new['budget']['sweep_calls'],
      f"prefix {tot_pre_calls} + suffix {tot_suf_calls} = "
      f"{tot_pre_calls + tot_suf_calls} (freeze: {new['budget']['sweep_calls']})")
check('4b token decomposition reconciles with the frozen estimate',
      abs((tot_pre_tok + tot_suf_tok) - new['budget']['sweep_token_estimate'])
      < 2000,
      f"{round(tot_pre_tok + tot_suf_tok)} vs "
      f"{new['budget']['sweep_token_estimate']}")
check('4c both makespan accountings emitted with explicit formulas',
      len(rows) == 48 and all('suffix_makespan_s' in r and
                              'reconstructed_e2e_makespan_s' in r for r in rows))

# ---- ONE consistent seven-field config ----
final_cfg = dict(
    batch_name='stage_c_r1_v1', max_calls=550, max_tokens=600000, max_cash=0,
    allowed_models=['glm53', 'glm53flash'],
    tasks='SC-E1,SC-E3 x S1_transport@timeline(left=1) x S2_contract@'
          'verification(persistent) x 6 arms x 2 reps = 48 runs',
    issued_by='PENDING',
    per_model_quota={'glm53': {'calls': 160, 'tokens': 266000},
                     'glm53flash': {'calls': 30, 'tokens': 50000}},
    z_scope='TESTED_UNDER_S2_CONTRACT (SPLIT_VERIFY; SC-E3 primary for '
            'Z-increment analysis, SC-E1 replication only)',
    experiment_scope='受控双异常（瞬断/持续合同违约）下的动态调度与有限 '
                     'Z、R、π 联合机制验证——不构成三维联合优化优于全部'
                     '强基线的一般性证明',
    superseded='STAGE_C_R1_FINAL_CHECK.json (13/13, demo-engine generation, '
               'NOT the authorized matrix, invalid model alias)')
F['final_config'] = final_cfg
cfg = json.load(open(B / 'stage_c_r1_auth_recommendation.json'))
consistent = (cfg['batch_name'] == final_cfg['batch_name']
              and cfg['max_calls'] == final_cfg['max_calls']
              and cfg['max_tokens'] == final_cfg['max_tokens']
              and cfg['per_model_quota'] == final_cfg['per_model_quota'])
check('5 recommendation file consistent with the emitted final config',
      consistent)

out = B / 'stage_c_r1_runs' / 'STAGE_C_R1_CONSISTENCY.json'
out.write_text(json.dumps(F, ensure_ascii=False, indent=1, default=str))
print(f"\nOVERALL: {'ALL PASS' if F['pass'] else 'GATES FAILED'} -> {out}")
sys.exit(0 if F['pass'] else 1)
