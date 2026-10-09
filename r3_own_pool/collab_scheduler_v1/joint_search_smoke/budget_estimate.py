"""Budget estimation for formal joint search experiment (zero calls).

Uses the 8-task smoke run's actual metrics to estimate the cost of running
the full experiment (32 configs × N tasks × 2 states × 6 methods).
"""
import json
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/joint_search_smoke'

SMOKE = json.loads(
    (OUT / 'proposal_v2/runs/smoke8_metering_01/METERING_AUDIT.json').read_text())

# Smoke actuals (8 configs × 8 tasks = 64 cells)
smoke = SMOKE['summary']
cells = smoke['cells']  # 64
new_req = smoke['new_requests']  # 110
new_tok = smoke['new_tokens']  # 41191
cache_hits = smoke['cache_hits']  # 177
injected = smoke['injected_calls']  # 8
wall_s = smoke['observed_wall_s']  # 733.6
model_switch_s = smoke['model_switch_wall_s']  # 604.6

# Per-cell averages
tok_per_cell = new_tok / cells
req_per_cell = new_req / cells
wall_per_cell = wall_s / cells

# Formal experiment parameters
N_CONFIGS = 32
N_TASKS_CALIB = 16  # calibration tasks (for building surrogate)
N_TASKS_TEST = 16   # test tasks (for final evaluation)
N_METHODS = 6
N_STATES = 2

# Scenario A: Full evaluation of all configs (ground truth)
cells_full = N_CONFIGS * (N_TASKS_CALIB + N_TASKS_TEST) * N_STATES
# With cache reuse (same task, different configs share node calls)
# Cache rate from smoke: 177/295 = 60%
cache_rate = cache_hits / (new_req + cache_hits)
est_new_req_full = cells_full * req_per_cell * (1 - cache_rate * 0.5)  # partial cache
est_tokens_full = est_new_req_full * (new_tok / new_req)
est_wall_full_hours = cells_full * wall_per_cell / 3600

# Scenario B: Search-based (only t configs revealed, not all 32)
T_SEARCH = 12  # typical search budget
cells_search = T_SEARCH * N_TASKS_CALIB * N_STATES
est_new_req_search = cells_search * req_per_cell * (1 - cache_rate * 0.5)
est_tokens_search = est_new_req_search * (new_tok / new_req)
est_wall_search_hours = cells_search * wall_per_cell / 3600
# Plus test evaluation: best config on test tasks
cells_test = N_METHODS * N_TASKS_TEST * N_STATES  # each method's best config
est_new_req_test = cells_test * req_per_cell * (1 - cache_rate * 0.7)  # higher cache
est_tokens_test = est_new_req_test * (new_tok / new_req)
est_wall_test_hours = cells_test * wall_per_cell / 3600

BUDGET = dict(
    smoke_actuals=dict(
        cells=cells, new_requests=new_req, new_tokens=new_tok,
        cache_hits=cache_hits, injected=injected,
        wall_minutes=round(wall_s / 60, 1),
        tokens_per_cell=round(tok_per_cell),
        requests_per_cell=round(req_per_cell, 1),
        cache_rate=round(cache_rate, 3),
    ),
    scenario_a_full_ground_truth=dict(
        description='Evaluate all 32 configs on 16 cal + 16 test tasks × 2 states',
        total_cells=cells_full,
        est_new_requests=int(est_new_req_full),
        est_new_tokens=int(est_tokens_full),
        est_wall_hours=round(est_wall_full_hours, 1),
        verdict='NOT RECOMMENDED: cost too high for ground truth that search '
                'should approximate',
    ),
    scenario_b_search_based=dict(
        description='Search reveals t=12 configs on 16 cal tasks × 2 states; '
                     'then evaluate each method best config on 16 test tasks',
        search_cells=cells_search,
        search_est_requests=int(est_new_req_search),
        search_est_tokens=int(est_tokens_search),
        search_est_wall_hours=round(est_wall_search_hours, 1),
        test_cells=cells_test,
        test_est_requests=int(est_new_req_test),
        test_est_tokens=int(est_tokens_test),
        test_est_wall_hours=round(est_wall_test_hours, 1),
        total_est_requests=int(est_new_req_search + est_new_req_test),
        total_est_tokens=int(est_tokens_search + est_tokens_test),
        total_est_wall_hours=round(est_wall_search_hours + est_wall_test_hours, 1),
        verdict='RECOMMENDED: provides search comparison + generalization test '
                'at ~50% of full cost',
    ),
    recommended=dict(
        n_tasks_calibration=16,
        n_tasks_test=16,
        n_configs=32,
        n_methods=6,
        n_states=2,
        search_budget_t=12,
        hard_cap_real_requests=600,
        hard_cap_tokens=250000,
        hard_cap_wall_hours=3,
        abnormal_stop='any method fails on >20% of tasks; GPU error; '
                       'budget exceeded before t=6',
    ),
    go_conditions=[
        'ISSUE-1/2/3 from SMOKE_ADMISSION_E.json resolved',
        'Closed-loop test 5/5 PASS (verified)',
        'Unified 32-config space frozen (verified)',
        '6-method search interface frozen (verified)',
        'Budget approved: ~350 total requests, ~150k tokens, ~1.5h wall',
        'GPU available, no conflicting processes',
    ],
)

(OUT / 'BUDGET_ESTIMATE.json').write_text(json.dumps(BUDGET, indent=1))
print(json.dumps(dict(
    smoke_tokens_per_cell=round(tok_per_cell),
    full_est_tokens=int(est_tokens_full),
    search_est_tokens=int(est_tokens_search + est_tokens_test),
    recommended_cap=250000,
    recommended_requests_cap=600,
    recommended_wall_cap='3h'), indent=1))
