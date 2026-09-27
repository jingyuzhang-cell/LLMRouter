"""Phase 1.5: Empirical Search-Space Freeze + zero-call evidence upgrades.

1. Freeze G_feasible with STABLE config IDs (Y__X__Z__M); every surrogate,
   archive, and results table addresses configs by ID only.
2. Zero-call upgrade: the 9 cross_model SER cells (Q-only) -> full (Q,C,L)
   reconstructed from per-call usage/latency in the frozen manifests
   (REQUESTS/RESPONSES.jsonl carry usage, latency_s, model, and combo keys).
3. Reference Cube design (draft): 18 cooperative configs + anchors on ONE
   task panel under s_clean and s_fault30 -> exact empirical Pareto fronts
   as the SA-PGFS ground truth (reveal/replay, zero additional calls).
"""
import json
import re
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1'
CM = ROOT / 'static_dag_v0/cross_model_matrix'
POOL = ['medium', 'large', 'coder']

YS = {'Single': ['cheap', 'quality'],
      'SER': ['cheap', 'balanced', 'quality', 'heterogeneous', 'type-prior'],
      'SERV': ['cheap', 'balanced', 'quality', 'heterogeneous', 'type-prior'],
      'ParallelER': ['cheap', 'balanced', 'quality', 'heterogeneous', 'type-prior'],
      'DynamicDAG': ['cheap', 'balanced', 'quality', 'heterogeneous', 'type-prior']}
X_MAP = {  # node->model per family (v-consistent with frozen200 'heterogeneous')
    'cheap': {'e': 'medium', 'r': 'medium', 'v': 'medium'},
    'balanced': {'e': 'medium', 'r': 'large', 'v': 'medium'},
    'quality': {'e': 'large', 'r': 'large', 'v': 'large'},
    'heterogeneous': {'e': 'large', 'r': 'medium', 'v': 'coder'},
    'type-prior': 'router-top per node',
}


def freeze_space():
    ids = []
    for y, xs in YS.items():
        for x in xs:
            zs = ['none', 'retry'] if y == 'Single' else \
                (['none'] if y != 'DynamicDAG' else ['none', 'local-reroute', 'local-recompute'])
            for z in zs:
                for m in (['fresh'] if y != 'history-slot' else MS):
                    ids.append(f'{y}__{x.upper()}__{z.upper().replace("-", "_")}__{m.upper()}')
    space = dict(config_ids=ids, n=len(ids), x_map=X_MAP,
                 note='M != fresh feasible only in history-enabled states; '
                      'Z != none only on DynamicDAG (v1); Single X collapses to '
                      '{cheap, quality}, Z to {none, retry}')
    (OUT / 'SPACE.json').write_text(json.dumps(space, indent=1))
    return space


def upgrade_cross_model():
    """Reconstruct (Q, C, L) for the 9 SER (extractor, reasoner) combos."""
    results = json.loads((CM / 'CROSS_MODEL_RESULTS.json').read_text())['matrix']
    resp = {}
    for l in (CM / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        resp[r['key']] = r['response']
    # panel size from any combo
    cells = {}
    for k, v in results.items():
        me, mr = k.split('->')
        me, mr = me.split('_')[1], mr.split('_')[1]
        keys = [key for key in resp if key.startswith(f'X:{me}:{mr}:')]
        if keys:
            toks = [float(resp[key].get('usage', {}).get('total_tokens', 0)) for key in keys]
            lats = [float(resp[key].get('latency_s', 0)) for key in keys]
            cells[f'SER__E{me}_R{mr}__NONE__FRESH'] = dict(
                Q=v['Q'], n=v['n'],
                C_reasoning_stage=float(sum(toks) / len(toks)),
                L_reasoning_stage=float(sum(lats) / len(lats)),
                n_calls=len(keys),
                evidence='measured Q (full chain) + measured per-call tokens/latency for '
                         'the REASONING stage (this manifest holds the 6 off-diagonal '
                         'combos, 200 calls each); extraction-stage cost not separable here')
        else:
            cells[f'SER__E{me}_R{mr}__NONE__FRESH'] = dict(
                Q=v['Q'], n=v['n'],
                evidence='Q-only: diagonal combos were served from cache in the frozen '
                         'run; no per-call records in this manifest -> C/L not '
                         'reconstructable at zero calls')
    return cells


def run():
    space = freeze_space()
    cells = upgrade_cross_model()
    cube_design = dict(
        reference_cube=dict(  # B-prime: legality fixed per SPACE.json rules
            YX_none=['SER', 'SERV', 'ParallelER'],
            Y_dynamic_with_Z='DynamicDAG x {NONE, LOCAL_REROUTE}',
            X=['BALANCED', 'HETEROGENEOUS', 'QUALITY'],
            n_core=15,  # 3Y x 3X (Z=NONE) + DynamicDAG x 3X x 2Z
            clean_dedup='under s_clean DynamicDAG NONE and LOCAL_REROUTE share the '
                        'execution path (no faults to trigger recovery) -> one clean '
                        'evaluation, reported under both Z labels',
            anchors=['SINGLE__QUALITY__RETRY__FRESH', 'DYNAMICDAG__HETEROGENEOUS__NONE__FRESH',
                     'DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH'],
            states=['s_clean', 's_fault30 (3 seeds, frozen200 fault model)'],
            same_panel=True, purpose='exact empirical Pareto fronts P*_clean, P*_fault '
                                     '= SA-PGFS ground truth for reveal/replay'),
        cost_estimate=('unique real calls ≈ extraction 3 models×200 + reasoning '
                       '3 reasoners×3 fact-sets×200 + verify 2×200 + fault-recovery '
                       'reroutes ≈ 3–4k calls; node-level caching across configs '
                       'exploited; exact count to be frozen in the run protocol'),
        M_handling='reuse/selective-reuse EXCLUDED from the cube (history panel is a '
                   'separate case study); cube searches (Y,X,Z) under clean/fault only',
        cache_boundary='cache key = (task, node, model, input_hash, prompt_version); ONLY '
                       'pure model executions cached; fault injection / failure status / '
                       'reroute decisions / descendant recomputation NEVER shared across '
                       'clean/fault states',
        crossmodel_upgrade_scope='the 6 zero-call upgrades carry REASONING-STAGE C/L only; '
                                 'usable as X priors / sanity checks / cache-reuse basis; '
                                 'NEVER mixed into the unified (Q_workflow, C_workflow, '
                                 'L_critical_path) Pareto front')
    (OUT / 'PHASE15_FREEZE.json').write_text(json.dumps(
        dict(space_n=space['n'], upgraded_cells=cells, cube_design=cube_design), indent=1))
    print(json.dumps(dict(space_n=space['n'], upgraded=list(cells),
                          sample=cells[list(cells)[0]]), indent=1))


if __name__ == '__main__':
    run()
