"""Zero-call cross-model evidence map: 9 measured SER combos -> cube config IDs.

Sources (both frozen artifacts, no model calls):
  - static_dag_v0/cross_model_matrix/CROSS_MODEL_RESULTS.json: 9 (e_model,
    r_model) SER combos, Q only, n=200, own panel
  - collab_scheduler_v1/PHASE15_FREEZE.json: the 6 off-diagonal combos
    upgraded with REASONING-STAGE C/L (per-call tokens/latency, 200 calls
    each); the 3 diagonal combos are Q-only (served from cache in that run)

Usage rules (frozen in PHASE15_FREEZE.cube_design.crossmodel_upgrade_scope):
these carry reasoning-stage C only — usable as X priors, sanity checks and
cache-reuse basis; NEVER mixed into the unified (Q_workflow, C_workflow,
L_critical_path) Pareto front, which is measured by the cube.

Run: python3 -m collab_scheduler_v1.crossmodel_map
"""
import json
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
CM = ROOT / 'static_dag_v0/cross_model_matrix/CROSS_MODEL_RESULTS.json'
FRZ = ROOT / 'collab_scheduler_v1/PHASE15_FREEZE.json'
OUT = ROOT / 'collab_scheduler_v1/CROSSMODEL_EVIDENCE_MAP.json'

# cube X families by (e_model, r_model); SER only (cross-model matrix is SER)
X_BY_ER = {
    ('medium', 'large'): 'BALANCED',
    ('large', 'medium'): 'HETEROGENEOUS',
    ('large', 'large'): 'QUALITY',
}


def run():
    cm = json.loads(CM.read_text())['matrix']
    freeze = json.loads(FRZ.read_text())
    upgraded = freeze['upgraded_cells']
    rows = {}
    for key, v in cm.items():
        me, mr = key.split('->')
        e, r = me.split('_')[1], mr.split('_')[1]
        fam = X_BY_ER.get((e, r))
        cid = f'SER__{fam}__NONE__FRESH' if fam else None
        # find the reasoning-stage upgrade if present
        up = None
        for ucid, u in upgraded.items():
            if ucid.startswith(f'SER__E{e}_R{r}__'):
                up = u
                break
        row = dict(e_model=e, r_model=r, Q=v['Q'], n=v['n'],
                   evidence='partial (Q-only)' if up is None else
                   f"Q (full chain) + reasoning-stage C/L; {up['evidence']}")
        if up:
            row['C_reasoning_stage'] = up.get('C_reasoning_stage')
            row['L_reasoning_stage'] = up.get('L_reasoning_stage')
        row['cube_config_id'] = cid
        row['relation_to_cube'] = (
            'SAME (e,r) pair as this cube config — prior/sanity check for the '
            'cube SER measurement; extraction-stage cost and verifier effects '
            'not included' if cid else
            'X-prior neighborhood: (e,r) combo outside the three cube families')
        rows[key] = row
    out = dict(
        source_artifacts=[str(CM.relative_to(ROOT)), str(FRZ.relative_to(ROOT))],
        usage_rule='priors / sanity checks / cache-reuse basis ONLY; never part '
                   'of the unified (Q,C,L) Pareto front (reasoning-stage C is '
                   'not workflow C)',
        combos=rows,
        cube_alignment=dict(
            direct=[k for k, v in rows.items() if v['cube_config_id']],
            neighborhood=[k for k, v in rows.items() if not v['cube_config_id']]),
        zero_model_calls=True)
    OUT.write_text(json.dumps(out, indent=1))
    for k, v in rows.items():
        tag = v['cube_config_id'] or '(X-prior)'
        print(f"{k:22s} Q={v['Q']:<6} -> {tag}")


if __name__ == '__main__':
    run()
