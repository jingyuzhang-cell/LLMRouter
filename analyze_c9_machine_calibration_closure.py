#!/usr/bin/env python3
"""Read-only calibration analysis; no scoring, training, or provider calls."""
import hashlib
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import cohen_kappa_score

ROOT = Path('/root/phase_c9_0')
JUDGES = ('doubao', 'qwen-max', 'glm-4-flash')

def analyze():
    source = ROOT / 'C9_2_MULTI_JUDGE_CALIBRATION_BASE_EVENTS.jsonl'
    manifest = json.loads((ROOT / 'C9_2_REPLACEMENT_JUDGE_PROBE_MANIFEST.json').read_text())
    groups = [f"{g['task_id']}:{int(g['repeat_id'])}" for g in manifest['groups'][:15]]
    assert len(groups) == len(set(groups)) == 15
    events = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    latest = {(r['group_id'], r['judge_model']): r for r in events}
    def valid(row):
        scores = (row or {}).get('scores_by_model')
        return bool(row and row.get('success') and isinstance(scores, dict) and scores and all(type(v) is int and 0 <= v <= 4 for v in scores.values()))
    per_judge = {}
    for judge in JUDGES:
        good = sum(valid(latest.get((g, judge))) for g in groups)
        failures = Counter((latest.get((g, judge)) or {}).get('error_type') or 'MissingOrInvalidScore' for g in groups if not valid(latest.get((g, judge))))
        history = Counter(r.get('error_type') or 'MissingOrInvalidScore' for r in events if r['judge_model'] == judge and r['group_id'] in groups and not valid(r))
        per_judge[judge] = {'successful_groups': good, 'expected_groups': 15, 'parse_success_rate': good / 15, 'missing_rate': (15-good)/15, 'latest_failure_types': dict(failures), 'historical_failed_call_types': dict(history)}
    common = [g for g in groups if all(valid(latest.get((g,j))) for j in JUDGES)]
    aligned = {j: [] for j in JUDGES}
    for g in common:
        keys = [set(latest[g,j]['scores_by_model']) for j in JUDGES]
        assert all(k == keys[0] for k in keys), f'candidate mismatch: {g}'
        for j in JUDGES:
            aligned[j].extend(latest[g,j]['scores_by_model'][m] for m in sorted(keys[0]))
    pairwise = {}
    for x,y in combinations(JUDGES,2):
        a,b = np.asarray(aligned[x]), np.asarray(aligned[y])
        n = len(a)
        mae = float(np.mean(np.abs(a-b))) if n else None
        within = float(np.mean(np.abs(a-b)<=1)) if n else None
        rho = float(spearmanr(a,b).statistic) if n and np.std(a)>0 and np.std(b)>0 else None
        kappa = float(cohen_kappa_score(a,b,weights='quadratic')) if n and len(set(a)|set(b))>1 else None
        pairwise[f'{x}__{y}'] = {'common_candidate_scores':n,'exact_agreement':float(np.mean(a==b)) if n else None,'within_one_agreement':within,'mean_absolute_disagreement':mae,'quadratic_weighted_kappa':kappa,'spearman':rho,'gate_pass':bool(n and within>=.8 and mae<=.75)}
    passed = all(v['parse_success_rate']>=.95 for v in per_judge.values()) and all(v['gate_pass'] for v in pairwise.values())
    return {'machine_calibration_status':'MACHINE_CALIBRATION_COMPLETE' if passed else 'MACHINE_CALIBRATION_FAIL','scope':'15-group base machine calibration only; not final scorer validity','human_reviewer_calibration_status':'PENDING_HUMAN_REVIEW','per_judge':per_judge,'all_three_successful_groups':len(common),'agreement_population':'same groups and candidate answers successfully scored by all three judges','pairwise_agreement_on_common_population':pairwise,'frozen_thresholds':{'parse_success_min':.95,'pairwise_within_one_min':.8,'pairwise_mae_max':.75},'stability_calibration_status':'NOT_RUN_THIS_CLOSURE','final_semantic_scorer_frozen':False,'formal_e4_semantic_scoring_started':False,'router_training_started':False,'reserved_holdout_accessed':False,'new_calibration_samples':0,'prompt_or_threshold_changed':False,'event_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}

if __name__ == '__main__':
    result = analyze()
    path = ROOT / 'C9_2_MACHINE_CALIBRATION_CLOSURE.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
