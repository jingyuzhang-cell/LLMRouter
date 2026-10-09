"""Generate the single admission package (ADMISSION_PACKAGE_V1) from frozen evidence.

Assembles (zero model calls, read-only over committed artifacts):
  1. Cross-state closed-loop evidence (TRACK_B_EVIDENCE.json v2, 15/15)
  2. FULL validation v2: frozen tasks, scenarios, global budget, execution
     command, actual execution state (authorized 1h run: 1/4 tasks done)
  3. Two SEPARATE resource envelopes with incomplete-reporting rules:
     A. FULL real validation (authorized, partially executed)
     B. Formal search (18 sessions) + TEST16 confirmation sub-envelope with the
        token upper bound recomputed at the FULL call ceiling
        (12 logical/task-state cap x 8192 reservation), not the optimistic
        mean-token estimate.
"""
import json
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
JS = ROOT / 'collab_scheduler_v1/joint_search_v1'

tb = json.loads((JS / 'review/TRACK_B_EVIDENCE.json').read_text())
fv = json.loads((JS / 'FULL_VALIDATION_PROTOCOL_V2.json').read_text())
fa = json.loads((JS / 'FULL_VALIDATION_PROTOCOL_V2.json').read_text())
run_dir = JS / 'fullval_runs/fullval_authorized_1h_01'
scen = [json.loads(l) for l in (run_dir / 'SCENARIOS.jsonl').read_text().splitlines()]
proto = json.loads((JS / 'SEARCH_BUDGET_V1.json').read_text())
panel = json.loads((JS / 'review/TASK_PANEL_V1.json').read_text())

# ---- TEST16 envelope recomputed at the FULL call ceiling ----
TEST_N = 16
LOGICAL_CAP = 12  # evaluator per task-config-state cap (includes recovery + replay)
RESERVATION = 8192
mean_tok = proto['measured']['mean_tokens_per_new_request']
max_logical = 6 * 2 * TEST_N * LOGICAL_CAP           # methods x states x tasks x cap
hard_requests = max_logical                          # <=1 new request per logical call
hard_tokens_reservation = max_logical * RESERVATION  # failed calls retain full reservation
realistic_tokens = max_logical * mean_tok
wall_per_req_s = proto['scenario']['simple_smoke_scaling_wall_s'] / \
    proto['scenario']['simple_smoke_scaling_requests']
test16 = dict(
    scope='final selection of each of 6 methods, evaluated ONCE on TEST16 x {clean, fault30}',
    max_logical_calls=max_logical,
    hard_upper_bound=dict(new_requests=hard_requests,
                          new_tokens_reservation_basis=hard_tokens_reservation,
                          wall_seconds_estimate=int(max_logical * wall_per_req_s)),
    realistic_estimate=dict(basis=f'mean {mean_tok:.1f} tok/new request (smoke measured)',
                            new_tokens=int(realistic_tokens)),
    declared_for_approval='HARD upper bound (reservation basis); settlement at actuals',
    positioning='SMALL-SCALE INDEPENDENT CONFIRMATION ONLY: MDE(TEST16)=0.24 on paired '
                'marginal delta; cannot exclude small differences and cannot support '
                'equivalence claims',
    cache_policy='fresh per-method cache; no cross-method subsidy')

# ---- FULL validation execution state ----
executed = dict(
    authorization=fa.get('status'),
    authorized_caps=json.loads((JS / 'FULLVAL_AUTHORIZED_1H.json').read_text())['caps'],
    run='fullval_runs/fullval_authorized_1h_01',
    tasks_completed=sorted({s['uid'] for s in scen}),
    scenario_summary={s['scenario']: dict(
        new_requests=s['result']['search_spend']['new_requests'],
        new_tokens=s['result']['search_spend']['new_tokens'],
        Q=s['result']['objectives']['Q']) for s in scen},
    mechanism_findings=[
        'S4 cache reuse: 0 new requests — full-prompt-identity cache reuse verified on real models',
        'S2 LOCAL: 2 new requests (recovery-path prompts) — billing separation recorded',
        'S3 FULL: 5 new requests (replay) — 8 logical calls billed with cache reuse on identical prompts',
        'Q=0 on the executed task for all scenarios (real model answered wrong); mechanism '
        'evidence unaffected (billing/caching, not quality)'],
    remaining='3 of 4 frozen calibration tasks unexecuted; completion inside the '
              'authorized envelope pending')

package = dict(
    version='ADMISSION_PACKAGE_V1',
    date='2026-10-09',
    status='ASSEMBLED_FOR_REVIEW — this package is NOT execution authorization',
    staged_approval=dict(
        stage_1='FULL small-scale real validation (envelope A) — already authorized for 1h; '
                'finish remaining 3 calibration tasks within existing caps',
        stage_2='formal search (envelope B) decided ONLY from stage-1 measurements; '
                'no blanket release of all stages'),
    component_1_cross_state_loop=dict(
        evidence='review/TRACK_B_EVIDENCE.json (v2, 15/15 ALL PASS)',
        what='SAME production closed loop evaluates every selected config on clean AND '
             'fault30 (real fault panel: r-corruption + empty-e2) per step; state '
             'ablation runs INSIDE this loop',
        results=dict(
            both_states_per_selection=True,
            fault30_Q_Z_dependent=True,
            per_state_scores_nondegenerate=True,
            state_ablation_diverges_in_loop=True,
            state_blind_label_invariant=True,
            calibration_spearman=tb['calibration']['spearman']),
        cache_prediction=dict(
            identity_rule=tb['cache_identity_rule'],
            precision='1.0 for all six methods — every predicted hit is an actual '
                      'TRRAJECTORY hit; the incremental estimate never underestimates '
                      'new search tokens (budget-safe direction)',
            recall_e_r='1.0 (exact)',
            recall_v='0.40-0.57, conservative by design: recovery-driven executions '
                     '(v escalation, FULL replay chains) populate cache entries whose '
                     'firing depends on outputs — NOT knowable inside the searcher '
                     'information boundary; unpredicted hits are charged as new',
            verification='predicted vs executor TRAJECTORY.jsonl alias_of records'),
        information_boundary='evaluated (config,state) units use ACTUAL evaluator C/L; '
                             'candidates use frozen ex-ante predictions; identical '
                             'boundary for all six methods; ablations toggle only '
                             'declared bits',
        known_limits='stub-quality structure is uniform (clean Q=1.0); real-model Q '
                     'heterogeneity expected to strengthen, not change, the wiring'),
    component_2_full_validation=dict(
        protocol='FULL_VALIDATION_PROTOCOL_V2.json (v2_20261009)',
        frozen_tasks=[t['uid'] for t in fv['frozen_tasks']],
        scenarios=list(fv['scenarios'].keys()),
        global_budget=fv['budget'],
        minimum_completion=fv['minimum_completion'],
        execution_command=fv['execution_command'],
        execution_state=executed),
    component_3_resource_envelopes=dict(
        envelope_A_full_validation=dict(
            status='AUTHORIZED (1h) and partially executed',
            budget_global=dict(new_requests=30, new_tokens=30000, wall_seconds=3600),
            scope='4 frozen calibration tasks x 4 scenarios; single global budget',
            incomplete_reporting='VALIDATION_INCOMPLETE logged if must-complete scope '
                                 'missed; partial ledger preserved; no retry'),
        envelope_B_formal_search=dict(
            status='PENDING stage-1 measurements — NOT approved by this package',
            sessions=proto['campaign_caps']['sessions'],
            per_session=proto['per_session_caps'],
            task_panel='review/TASK_PANEL_V1.json SEARCH8',
            caveat='caps are operational ceilings, NOT completion guarantees: the '
                   '330-request scenario reference below the 400 cap does not ensure '
                   'completion with new configs and FULL; completion is reported as '
                   'measured',
            incomplete_reporting=proto['stopping']),
        envelope_B_test16_confirmation=dict(
            status='PENDING — separate sub-envelope, NOT approved by this package',
            **test16)),
    non_claims=[
        'Budget-fit does not guarantee experiment completion',
        'TEST16 cannot exclude small differences (MDE 0.24) or support equivalence claims',
        'Cross-state loop is stub-backed (zero real calls): wiring admission, not '
         'performance evidence'],
    references=dict(
        wiring_status='collab_scheduler_v1/joint_search_v1/WIRING_STATUS.md',
        task_panel='collab_scheduler_v1/joint_search_v1/review/TASK_PANEL_V1.json',
        power='collab_scheduler_v1/joint_search_v1/review/TRACK_C_EVIDENCE.json'))

(JS / 'ADMISSION_PACKAGE_V1.json').write_text(json.dumps(package, indent=1))

md = f"""# ADMISSION PACKAGE V1 (2026-10-09)

**Status: assembled for review — this package is NOT execution authorization.**

Staged approval: Stage 1 = FULL small-scale real validation (envelope A, already
authorized for 1h; finish the 3 remaining calibration tasks). Stage 2 = formal
search (envelope B) decided ONLY from stage-1 measurements. No blanket release.

## 1. Cross-state production closed loop (the two admission gaps, closed)

Evidence: `review/TRACK_B_EVIDENCE.json` (v2, **15/15 ALL PASS**).

- **Gap 1 (cache deduction)**: replaced node+model matching with the COMPLETE
  identity chain per (state, task): e=(node,model); r=(m_e1,m_e2,m_r);
  v=(m_e1,m_e2,m_r,m_v)+Z-context in fault30 (recovery changes v's realized
  input). Verified against the executor's own TRAJECTORY hit records:
  **precision = 1.0 for all six methods** (predicted hit ⇒ actual hit; the
  incremental estimate never underestimates new search tokens), e/r recall = 1.0,
  v recall 0.40–0.57 conservative by design — recovery-driven cache population
  (escalation/replay) is output-dependent and outside the searcher's information
  boundary; unpredicted hits are charged as new. Recovery charged conditionally:
  E[new tokens] = overhead × P_fire(state), frozen params, measured fire counts
  reported.
- **Gap 2 (clean-only loop)**: the SAME loop now evaluates every selection on
  clean + fault30 with a real fault panel. Fault30 Q is Z-dependent inside the
  loop (NONE=0, LOCAL/FULL recover); per-state acquisition scores non-degenerate
  from pure evaluator observations; the state ablation diverges WITHIN this loop
  (state-aware vs blind pick sequences differ); state-blind search is label-
  invariant (swapping state labels does not change its picks).
- **Gap 3 (C/L determinism)**: evaluated units use ACTUAL evaluator C/L;
  candidates use frozen ex-ante predictions; all six methods share the identical
  information boundary. Calibration Spearman(est, actual C) = {tb['calibration']['spearman']:.3f}.

Known limit (registered): stub-backed quality structure is uniform in clean
(Q=1.0); this is wiring admission, not performance evidence.

## 2. FULL validation v2 (envelope A)

Protocol `FULL_VALIDATION_PROTOCOL_V2.json`: 4 frozen calibration tasks
(content-hashed), scenarios S1→S4→S2→S3, single global budget
**30 requests / 30,000 tokens / 1800s** (authorized 1h variant: 3600s wall),
command `{fv['execution_command']}`.

Execution state (authorized run `fullval_authorized_1h_01`): 1/4 tasks executed.
Mechanism findings on real models: **S4 cache reuse = 0 new requests**
(full-prompt identity reuse verified); S2 LOCAL = 2 new requests with billing
separation; S3 FULL = 5 new requests / 8 logical calls with replay billing.
Remaining: 3 calibration tasks inside the already-authorized envelope.

## 3. Resource envelopes (separate; incomplete-reporting rules attached)

### Envelope A — FULL real validation (AUTHORIZED, partially executed)
30 req / 30k tok / 1800–3600s global. Incomplete → `VALIDATION_INCOMPLETE`,
partial ledger preserved, no retry. Minimum completion: S1+S4 must, S2 should,
S3 may be partial.

### Envelope B — formal search (PENDING stage-1 measurements)
18 sessions = 6 methods × 3 seeds; per-session caps per SEARCH_BUDGET_V1;
task panel = SEARCH8 from TASK_PANEL_V1.json. **Caveat: caps are ceilings, not
completion guarantees** — the 330-request scenario reference under the 400 cap
does not ensure completion with new configs and FULL; results reported as
measured on common budget support; no extension to equalize completed counts.

### Envelope B — TEST16 confirmation sub-envelope (PENDING)
Recomputed at the FULL call ceiling (not the optimistic mean-token estimate):
- max logical calls = 6 methods × 2 states × {TEST_N} tasks × {LOGICAL_CAP} cap = **{max_logical}**
- hard upper bound: **{hard_requests} new requests / {hard_tokens_reservation:,} tokens**
  (reservation basis; failed calls retain full reservation), wall ≈ {int(max_logical*wall_per_req_s):,}s
- realistic estimate ≈ {int(realistic_tokens):,} tokens (mean {mean_tok:.0f} tok/req)
- Declared for approval: the HARD bound; settlement at actuals.
- **Positioning: small-scale independent confirmation only.** MDE(TEST16) ≈ 0.24
  on paired marginal delta — cannot exclude small differences, cannot support
  equivalence claims.

## 4. Non-claims

- Budget-fit ≠ completion guarantee.
- TEST16 ≠ equivalence evidence.
- Cross-state loop = wiring admission (stub), not performance evidence.
"""
(JS / 'ADMISSION_PACKAGE_V1.md').write_text(md)
print('ADMISSION_PACKAGE_V1 written')
print('TEST16 hard upper bound:', hard_requests, 'req /', f'{hard_tokens_reservation:,}', 'tok;',
      'realistic', int(realistic_tokens), 'tok')
print('cross-state:', sum(1 for v in tb['checks'].values() if v), '/', len(tb['checks']), 'checks pass')
