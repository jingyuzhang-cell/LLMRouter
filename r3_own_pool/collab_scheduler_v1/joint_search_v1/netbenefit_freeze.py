"""NET-BENEFIT final freeze: 50 held-out tasks, fault pre-registration, arms.

Zero model requests. Produces NET_BENEFIT_FREEZE.json, the single input
manifest the runner validates against before any execution.

Frozen decisions (BEFORE any NET-BENEFIT model call):
  - 50 task UIDs: hybrid_pool() minus ALL previously used panels, ordered by
    sha256('netbenefit:20261009:'+uid) ascending, first 50.
  - Six attribution arms (A, A', B, C, D, E) with FIXED configs; V2 candidates
    as two separate arms (V2_static, V2_dynamic); FULL candidate DEFERRED.
  - Mechanism fault draws (per state, bit-identical rule from frozen200).
  - Competitive fault draws: (task, interaction_kind) where kind is drawn
    uniform from {single, e1, e2, r, v} with reference models
    single=large, e1=large, e2=large, r=medium, v=coder. A strategy is
    exposed only when it actually calls the faulted (task, kind, model)
    triple. Deviation from the earlier (model, prompt_sha) draft is
    deliberate and pre-registered: prompt-level matching is unresolvable
    before first execution on held-out tasks (r/v prompts depend on runtime
    upstream outputs). The (task, kind, model) rule is deterministic,
    pre-registrable, and structure-agnostic.

Run:  python3 -m collab_scheduler_v1.joint_search_v1.netbenefit_freeze
"""
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'
FREEZE_PATH = OUT / 'NET_BENEFIT_FREEZE.json'

N_TASKS = 50
SEED_TAG = 'netbenefit:20261009:'

# state -> (rate, mechanism seed); competitive RNG seeds derive from state tag
STATES = {
    'clean': None,
    'fault10': (0.10, 20261023),
    'fault20': (0.20, 20261024),
    'fault30': (0.30, 20261025),
}
COMPETITIVE_INTERACTIONS = ('single', 'e1', 'e2', 'r', 'v')
REFERENCE_MODELS = {'single': 'large', 'e1': 'large', 'e2': 'large',
                    'r': 'medium', 'v': 'coder'}

# Six attribution arms (X mapping e1/e2/r/v; Z policy) + V2 candidate arms.
ARMS = {
    'A_single': dict(kind='single', model='large'),
    'A_single_cross_fallback': dict(kind='single', model='large',
                                    fallback='medium', max_fallbacks=1),
    'B_same_model_dag': dict(kind='dag', X=dict(e1='large', e2='large',
                                                r='large', v='large'), Z='NONE'),
    'C_static_hetero': dict(kind='dag', X=dict(e1='large', e2='large',
                                               r='medium', v='coder'), Z='NONE'),
    'D_dynamic_local': dict(kind='dag', X=dict(e1='large', e2='large',
                                               r='medium', v='coder'), Z='LOCAL'),
    'E_dynamic_full': dict(kind='dag', X=dict(e1='large', e2='large',
                                              r='medium', v='coder'), Z='FULL',
                           replay_rule=(
                               'SAME detection predicate and per-task '
                               'alternative models as D (recovery_plans: '
                               'e-nodes use the memory rule coder/medium by '
                               'panel det order; r escalates to large; v '
                               'escalates to large); every other node '
                               're-executes on its PLANNED model. D and E '
                               'differ ONLY in re-execution scope (local '
                               'subtree vs full graph). D post-repair '
                               'cascades (R2/V2 refresh, V3) are D-defined '
                               'behavior on non-trigger nodes.')),
    'V2_static': dict(kind='dag', X=dict(e1='medium', e2='large',
                                         r='medium', v='coder'), Z='NONE',
                      role='v2_candidate'),
    'V2_dynamic': dict(kind='dag', X=dict(e1='medium', e2='medium',
                                          r='medium', v='coder'), Z='LOCAL',
                       role='v2_candidate'),
}
DEFERRED = {
    'V2_full_extension': dict(config_id='large__medium__medium__large__FULL',
        reason='kept frozen as resource-available extension; never enters the '
               'six-arm attribution; not scheduled this round'),
}


def materialize(t):
    """hybrid_pool tasks carry raw `para`; contexts are deterministic
    functions of it (same rule as fullval_runner)."""
    from static_dag_v0.multidag_dynamic import ctx_table, ctx_text
    out = dict(t)
    out['ctx_table'] = ctx_table(t['para'])
    out['ctx_text'] = ctx_text(t['para'])
    return out


def content_sha(task):
    t = materialize(task) if 'para' in task else task
    payload = {k: t.get(k) for k in
               ('uid', 'question', 'ctx_table', 'ctx_text', 'derivation', 'answer')}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def exclusion_uids():
    """Every UID ever used by a prior panel that touches this distribution."""
    import static_dag_v0.exact_pareto as ep
    from collab_scheduler_v1 import dag_patch_p1b as p1b
    excl = {}
    fz = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json').read_text())
    excl['frozen200'] = {t['uid'] for t in fz['tasks']}
    main120 = json.loads((ep.OUT / 'POLICY.json').read_text())['tasks'][:120]
    excl['main120'] = {t['uid'] for t in main120}
    excl['p1b_5'] = {t['uid'] for t in p1b.select_tasks()}
    fvp = json.loads((OUT / 'FULL_VALIDATION_PROTOCOL_V3.json').read_text())
    excl['fullval_4'] = {x['uid'] if isinstance(x, dict) else x
                         for x in fvp['frozen_tasks']}
    panel = [json.loads(l) for l in
             (OUT / 'formal_campaign_v2/proposed_state_incremental_20261009'
              '/TASK_PANEL.jsonl').read_text().splitlines() if l.strip()]
    excl['v2_campaign_8'] = {t['uid'] for t in panel[0]}
    return excl


def build_mechanism_faults(seed, rate, tasks, pools):
    """Bit-identical rule to fp.build_faults (kept local so the freeze file
    records the exact draw without importing runtime state)."""
    rng = random.Random(seed)
    n_fault = int(len(tasks) * rate)
    faulted = rng.sample([t['uid'] for t in tasks], n_fault)
    faults = {}
    for u in faulted:
        node = rng.choice(['e1', 'e2', 'r', 'v'])
        if node in ('e1', 'e2'):
            failing = pools['e'][rng.randrange(len(pools['e']))]
        elif node == 'r':
            failing = pools['r'][rng.randrange(len(pools['r']))]
        else:
            failing = pools['v'][rng.randrange(len(pools['v']))]
        faults[u] = (node, failing)
    return faults


def build_competitive_faults(state, rate, tasks, pools, mech_faults):
    """Same faulted task set as the mechanism draw (paired); interaction kind
    drawn uniform over the five reference service interactions."""
    rng = random.Random(f'netbenefit-competitive:{state}')
    faults = {}
    for u in mech_faults:
        kind = rng.choice(COMPETITIVE_INTERACTIONS)
        pool_key = 'r' if kind in ('single', 'r') else (
            'e' if kind in ('e1', 'e2') else 'v')
        failing = pools[pool_key][rng.randrange(len(pools[pool_key]))]
        faults[u] = (kind, failing)
    assert len(faults) == len(mech_faults)
    return faults


def run():
    from static_dag_v0.multidag_dynamic import hybrid_pool
    pool = hybrid_pool()
    pool_uids = {t['uid'] for t in pool}
    assert len(pool_uids) == len(pool)
    excl = exclusion_uids()
    used = set().union(*excl.values())
    inter = pool_uids & used
    remaining = sorted(pool_uids - used,
                       key=lambda u: hashlib.sha256(
                           (SEED_TAG + u).encode()).hexdigest())
    selected = remaining[:N_TASKS]
    assert len(selected) == N_TASKS, f'only {len(remaining)} tasks remain'

    task_map = {t['uid']: t for t in pool}
    tasks = [materialize(task_map[u]) for u in selected]

    pools = json.loads(
        (ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json').read_text())

    states = {}
    for name, spec in STATES.items():
        if spec is None:
            states[name] = None
            continue
        rate, seed = spec
        mech = build_mechanism_faults(seed, rate, tasks, pools)
        comp = build_competitive_faults(name, rate, tasks, pools, mech)
        states[name] = dict(
            rate=rate, mechanism=dict(seed=seed, faults={
                u: [n, a] for u, (n, a) in sorted(mech.items())}),
            competitive=dict(
                rule='(task, interaction_kind, reference_model); strategy '
                     'exposed only when it actually calls the faulted triple',
                reference_models=REFERENCE_MODELS,
                faults={u: [k, a] for u, (k, a) in sorted(comp.items())}))

    freeze = dict(
        protocol='NET_BENEFIT_FINAL_FREEZE',
        version='FREEZE_v2_20261010',
        status='FROZEN; v2 aligns E-arm replay with D detection/targets '
               'before any E cell ever ran (no E real call exists)',
        pre_halt_real_spend=dict(
            note='3 real cells (A/A-prime/B clean) executed under FREEZE_v1 '
                 'on 2026-10-10 before the halt directive; arm definitions '
                 'are unchanged in v2, records preserved in NB_ROWS.jsonl, '
                 '252 physical requests charged to the global real budget; '
                 'resume will not re-pay them (cache seeded from TRAJECTORY)',
            cells=['mechanism:A_single:clean', 'mechanism:A_single_cross_fallback:clean',
                   'mechanism:B_same_model_dag:clean']),
        task_selection=dict(
            source='static_dag_v0.multidag_dynamic.hybrid_pool()',
            rule=f'sha256("{SEED_TAG}"+uid) ascending, first {N_TASKS}',
            n_pool=len(pool), n_remaining=len(remaining),
            remaining_not_selected=sorted(set(remaining) - set(selected)),
            excluded_from_pool=sorted(inter),
            exclusion_panels={k: len(v) for k, v in excl.items()},
            exclusion_uids={k: sorted(v & pool_uids) for k, v in excl.items()}),
        tasks=[dict(uid=t['uid'], content_sha256=content_sha(t)) for t in tasks],
        arms=ARMS,
        deferred=DEFERRED,
        states=states,
        confirmatory=dict(
            primary=('mechanism', 'fault30', 'B*=3000', 'Q_B(D)-Q_B(A) > 0',
                     'one-sided exact McNemar alpha=0.05'),
            gate2=('only if gate1 passes', 'Q_B(D)-Q_B(A\') > 0',
                   'one-sided exact McNemar alpha=0.05'),
            competitive_family=('competitive', 'fault30', 'B*=3000',
                                'same gate structure, reported as the '
                                'deployment-claim family'),
            multiple_comparison='Holm within each exploratory family'),
        budgets=dict(global_max_physical_requests=4000,
                     global_max_physical_tokens=4000000,
                     global_max_wall_seconds=21600,
                     per_strategy_per_state_physical_max=400,
                     de_reserved_physical_requests=800),
    )
    FREEZE_PATH.write_text(json.dumps(freeze, ensure_ascii=False, indent=1) + '\n')
    print(f'froze {len(tasks)} tasks -> {FREEZE_PATH}')
    for name in states:
        if states[name]:
            print(f"  {name}: mechanism={len(states[name]['mechanism']['faults'])} "
                  f"competitive={len(states[name]['competitive']['faults'])}")
    return freeze


if __name__ == '__main__':
    run()
