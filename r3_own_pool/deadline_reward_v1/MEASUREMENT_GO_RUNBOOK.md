# MEASUREMENT_GO_RUNBOOK — operator checklist for the supplementary measurement

Standing state: real calls HOLD. Nothing below runs without the
operator's explicit measurement GO. PREFLIGHT_PASS is an admission-check
record, not a permission.

## 1. What is being authorized (one line)

The DAG-quality supplementary measurement per
DAG_QUALITY_CALIBRATION_PROTOCOL_v1: 5 arms × 2 conditions × 20 frozen
tasks, full real 4-node cascade, v2.1 terminal scoring, per-cell Wilson
95% CIs — INITIAL QUALITY CALIBRATION ONLY (no strategy selection, no
weight adjustment, no superiority claim; D=3600 makes deadlines
non-binding by design).

## 2. Pre-GO checks (operator, zero-call)

```bash
cd /root/r3_own_pool
# preflight (re)confirmation — must print PREFLIGHT_PASS
python3 -m deadline_reward_v1.supplementary_runner
# full entry-point rehearsal — must print REHEARSAL_PASS, zero side effects
SUPPLEMENTARY_EXECUTE=1 python3 -m deadline_reward_v1.supplementary_runner \
  --execute --rehearse \
  --approved-freeze-sha256 $(python3 -c \
  "import hashlib;print(hashlib.sha256(open('deadline_reward_v1/evidence/SUPPLEMENTARY_PANEL_FREEZE.json','rb').read()).hexdigest())")
```

Rehearsal verifies, on the real entry point: approved freeze SHA =
sha256(SUPPLEMENTARY_PANEL_FREEZE.json); preflight status PREFLIGHT_PASS;
the FULL freeze manifest re-derived (16 files + params/caps/planned/
scaffold + beliefs hash; refuses any drift including uncommitted
modifications to bound files); beliefs rebuilt from trajectories with 0
mirror/production divergences; priors validation. It exits before any
run dir / GPU lock / model server / call.

## 3. The approved identifiers (re-approve if any hash moved)

- panel freeze sha256: see `evidence/SUPPLEMENTARY_PREFLIGHT.json`
  → hashes.panel_freeze (value also printed by the rehearsal)
- preflight evidence: `evidence/SUPPLEMENTARY_PREFLIGHT.json` at the
  approved commit; freeze_manifest inside binds: 11 code files
  (arm_entry, detection, dag_closure, scheduler_state, policy,
  reassign, predictor, compensator, reward, stub_engine,
  supplementary_runner), 5 docs (panel freeze, protocol, prerequisites,
  PRIORS_REAL_V1, PRIORS_REAL_V1_families), beliefs hash, PARAMS/CAPS/
  PLANNED/D_SCAFFOLD
- git HEAD at approval: freeze_manifest.git_commit (provenance; the
  enforced objects are the bound-file hashes)

## 4. GO-day execution (ONLY after explicit GO)

```bash
cd /root/r3_own_pool
SUPPLEMENTARY_EXECUTE=1 python3 -m deadline_reward_v1.supplementary_runner \
  --execute --approved-freeze-sha256 <panel_freeze_sha256>
```

Hard caps (production Budget class): 1,200 requests / 800,000 tokens /
7,200 s wall; per-attempt reservations (a failed dispatch attempt keeps
its reservation charged and is audited as an `attempt_failed` DISPATCH
event); SIGALRM wall backstop; no silent resume; fresh run dir only.
Expected shape (structural cache plan): 150–250 physical requests,
~3,000–5,000 s; 10 cell records with per-cell metering
(new_requests/cache_hits/injected_faults/physical_tokens/logical_calls)
and execution_order audits.

## 5. Post-run verification (operator/assistant)

- `supplementary_runs/<run_id>/STATUS.json`: status COMPLETE, cells_done 10
- `PRIORS_REAL_V1_quality.json` written ONLY if COMPLETE (else the
  separately-named INCOMPLETE file — never treated as the calibration)
- per-cell metering vs the structural cache plan (VERIFICATION_GUIDE §3):
  large deviations = identity drift to investigate, not results to read
- budget reconciliation: attempts/tokens vs caps; DISPATCH ledger
  reserve/settle/attempt_failed arithmetic
- read results ONLY as quality calibration: P(correct) per cell with CI;
  q_parse-belief vs realized-correctness gap is itself a finding
  (boundary: proxy ≠ correctness)

## 6. What this measurement can NOT support (standing)

Time-pressure scheduling claims (D inert); strategy selection or DD>SS
claims; adjustment of Q_min/eps/reward weights; treating node parse
rates as task correctness. Next gates after this one: real-deadline
prediction reliability, then the dynamic-vs-static comparison under the
frozen V2.3 protocol.
