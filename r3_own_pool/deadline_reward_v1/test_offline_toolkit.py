"""Zero-call tests for the offline toolkit (model registry gates,
panel freeze, screening plan, Q/C/L analyzer, budget calculator).

Run: python3 -m deadline_reward_v1.test_offline_toolkit
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent

from deadline_reward_v1.offline_toolkit import (
    BudgetCalculator, GateReject, NodeScreeningAnalyzer,
    MODEL_REGISTRY_TEMPLATE, SCREENING_MODELS, SCREENING_SEED,
    freeze_screening_panel, freeze_screening_plan, verify_model_registry)


def main():
    checks, detail = {}, {}

    # ---- G1: registry gates -------------------------------------------
    # unverified registry MUST be rejected
    try:
        verify_model_registry(MODEL_REGISTRY_TEMPLATE)
        checks['G1_unverified_rejected'] = False
    except GateReject as exc:
        checks['G1_unverified_rejected'] = 'Unverified' in str(exc)

    # fill + verify
    reg = json.loads(json.dumps(MODEL_REGISTRY_TEMPLATE))
    for name, cfg in reg.items():
        cfg['model_id'] = cfg.get('model_id') or f'{name}-test'
        cfg['billing']['input_per_1k_cny'] = 0.01
        cfg['billing']['output_per_1k_cny'] = 0.02
        cfg['verified'] = True
        cfg['verification_method'] = 'test'
        cfg['subscription_covered'] = (
            cfg.get('subscription_covered') or False)
        if cfg['subscription_covered'] or name == 'qwen_local':
            cfg['normalized_cost_basis'] = \
                cfg.get('normalized_cost_basis') or 'token_units'
    status = verify_model_registry(reg)
    checks['G1_verified_accepted'] = all(v['ok'] for v in status.values())

    # subscription-covered without normalized basis must be rejected
    reg2 = json.loads(json.dumps(reg))
    reg2['glm']['subscription_covered'] = True
    del reg2['glm']['normalized_cost_basis']
    try:
        verify_model_registry(reg2)
        checks['G1_subscription_needs_normalized'] = False
    except GateReject:
        checks['G1_subscription_needs_normalized'] = True

    # ---- G2: panel freeze ----------------------------------------------
    panel = freeze_screening_panel()
    assert len(panel['uids']) == 20
    assert len(set(panel['uids'])) == 20
    # deterministic
    panel2 = freeze_screening_panel()
    checks['G2_deterministic'] = panel['uids'] == panel2['uids']
    checks['G2_gold_isolated'] = panel['gold_isolation'].startswith(
        'gold NEVER')
    detail['G2'] = dict(n=panel['n'], pool=panel['pool_size'],
                        sha=panel['uids_sha256'][:16])

    # ---- G3: screening plan freeze -------------------------------------
    try:
        freeze_screening_plan(panel, MODEL_REGISTRY_TEMPLATE)
        checks['G3_gates_reject_unverified'] = False
    except GateReject:
        checks['G3_gates_reject_unverified'] = True
    plan = freeze_screening_plan(panel, reg)
    checks['G3_80_calls'] = plan['total_calls'] == 80
    # 4 models × 4 nodes, 20 tasks split
    nodes_covered = set(a['node'] for a in plan['assignments'].values())
    models_covered = set(a['model']
                         for a in plan['assignments'].values())
    checks['G3_all_nodes_models'] = (nodes_covered == {'e1','e2','r','v'}
                                     and models_covered ==
                                     set(SCREENING_MODELS))
    detail['G3'] = dict(calls=plan['total_calls'],
                        nodes=sorted(nodes_covered),
                        models=sorted(models_covered))

    # ---- G4: Q/C/L analyzer --------------------------------------------
    an = NodeScreeningAnalyzer()
    # synthetic: model A succeeds on tasks 0-4, model B on 2-6
    for i in range(8):
        for model, ok_range in (('glm', range(5)), ('deepseek',
                                                    range(2, 7))):
            an.add(model, 'r', f't{i}',
                   q=1 if i in ok_range else 0,
                   tokens=100 + i * 10, latency_s=0.5 + i * 0.1,
                   cash_cost_cny=0.001, normalized_cost=0.1)
    tbl = an.full_table()
    checks['G4_table_has_cells'] = 'r|glm' in tbl and 'r|deepseek' in tbl
    comp = an.complementarity('r')
    checks['G4_complementarity'] = len(comp) >= 1 and any(
        p['complementarity_rate'] > 0 for p in comp)
    detail['G4'] = dict(cells=list(tbl.keys()),
                        complementarity=comp)

    # ---- G5: budget calculator -----------------------------------------
    bc = BudgetCalculator(reg)
    est = bc.estimate_screening_budget()
    checks['G5_dual_cost'] = (est['total_cash_cny'] >= 0
                              and est['total_normalized'] > 0)
    checks['G5_local_nonzero_normalized'] = (
        est['per_model']['qwen_local']['normalized'] > 0)
    checks['G5_never_mixed'] = 'never mixed' in est['note']
    detail['G5'] = est

    evidence = dict(milestone='offline_toolkit',
                    ruling='operator 2026-10-13 GPU-independent prep',
                    checks=checks, detail=detail,
                    zero_model_calls=True,
                    all_pass=all(checks.values()))
    (HERE / 'evidence' / 'OFFLINE_TOOLKIT.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f"\nzero_model_calls=true; "
          f"{'ALL PASS' if evidence['all_pass'] else 'FAIL PRESENT'}")
    return 0 if evidence['all_pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
