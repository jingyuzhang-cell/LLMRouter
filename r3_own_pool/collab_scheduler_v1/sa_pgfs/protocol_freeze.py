"""SA-PGFS Protocol Freeze (search experiment, zero LLM calls).

This file is the single source of truth for the SA-PGFS reveal/replay
experiment. All parameters are FROZEN before any replay run. No
post-hoc tuning.

Search space: |G_collab| = 14 configs (Y×X×Z grid from Reference Cube).
States: s_clean, s_fault30 (mean over 3 seeds as fixed lookup truth).
Single: NOT in search space, shown as external global baseline in all figures.

Initial design: n_0 = 3 (same for ALL algorithms, same per replay seed).
Budget: full curve t = 3..14 (one reveal per step).
Replay seeds: 200 (paired: all algorithms share D_0 per seed).

Algorithms:
  Random: uniform over unevaluated
  Scalarized: argmax w·F̂ from frozen weight bank (rotated per step)
  Greedy-Q: argmax Q̂ (surrogate mean only)
  EHVI: MC-EHVI (48 samples, acquisition = EHVI)
  SA-PGFS: cost-aware EHVI / C_eval(G)^alpha (alpha=1, C_eval = estimated
    evaluation cost of the config — NOT the objective cost C(G), avoiding
    double-counting)

Metrics:
  R_HV(t) = 1 - HV(P_t)/HV(P*)  (normalized HV regret)
  Recall_P(t) = |P_t ∩ P*| / |P*|
  N_95 = min{t : HV(P_t)/HV(P*) ≥ 0.95}
  AUC_HV = (1/T) Σ_t HV(P_t)/HV(P*)

Robustness: seed-level fault replay (each of the 3 fault seeds as separate
lookup truth, 100 replay seeds each).

Surrogate: GP (Matérn 5/2, ARD, fixed hyperparams), features = structural
(config encoding), NOT gold-derived.
"""
import json
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/sa_pgfs'

PROTOCOL = dict(
    frozen_unix=time.time(),
    search_space=dict(
        n_configs=14,
        grid='SER/SERV/PARALLELER × {BAL,HET,QUAL} × NONE + DYN × {BAL,HET,QUAL} × {NONE,LOCAL_REROUTE}',
        single='external baseline, not searched',
    ),
    states=['s_clean', 's_fault30_mean'],
    initial_design=dict(n_0=3, shared_across_algorithms=True, sampled_uniformly=True),
    budget=dict(t_min=3, t_max=14, one_reveal_per_step=True),
    replay_seeds=200,
    algorithms=[
        dict(name='random', params={}),
        dict(name='scalarized', params=dict(
            weight_bank=[[0.6, 0.2, 0.2], [0.4, 0.3, 0.3], [1/3, 1/3, 1/3], [0.2, 0.4, 0.4]],
            rotation='cyclic per step')),
        dict(name='greedy_q', params={}),
        dict(name='ehvi', params=dict(n_mc=48)),
        dict(name='sa_pgfs', params=dict(n_mc=48, alpha=1.0,
                                          cost_source='C_eval estimated from config structure '
                                                      '(number of model nodes × estimated tokens/node), '
                                                      'NOT the C(G) objective')),
    ],
    metrics=['R_HV(t)', 'Recall_P(t)', 'N_95', 'AUC_HV'],
    surrogate=dict(
        kernel='Matern(nu=1.5, ARD) + White',
        normalize_y=True,
        n_restarts=0,
        features='structural encoding of (Y,X,Z): n_nodes, n_edges, depth, width, '
                 'has_v, has_dual_e, recovery_flag, model_onehot per role',
        noise_floor=0.01,
    ),
    ehvi=dict(
        n_mc_samples=48,
        reference_point='per-state worst in each objective from full cube',
        qMC_variance_check='regression test on synthetic 3D front'),
    hv=dict(
        reference_point='per-state, normalized to [0,1]^3'),
    robustness=dict(
        mode='seed-level fault cube replay',
        n_seeds_per_fault_seed=100,
    ),
    regression_gate='pareto.hypervolume() exactness on known 3D cases + '
                    'acquisition EHVI improvement ≥ 0 on dominating point',
    new_llm_calls=0,
)


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'PROTOCOL_SAPGFS_FREEZE.json').write_text(json.dumps(PROTOCOL, indent=1))
    print(json.dumps(dict(frozen=True, n_algos=len(PROTOCOL['algorithms']),
                          n_replay_seeds=PROTOCOL['replay_seeds'])))


if __name__ == '__main__':
    freeze()
