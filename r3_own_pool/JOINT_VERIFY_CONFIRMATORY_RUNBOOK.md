# JOINT_VERIFY_CONFIRMATORY_RUNBOOK — run-day procedure (executes only under the written GO)

Pre-agreed at `1988ab3`, zero calls. The run: 60 tasks × 6 arms,
caps 800 req / 300K tok / 11,000 s, estimated ~700 req / ~250K /
~8–10 ks (~2.5 h). ONE run; fail-stop; no in-round repair.

## 1. Pre-launch (operator-independent, ~2 min)

```bash
cd /root/r3_own_pool && git status --short | grep -v '^??'   # must be clean
nvidia-smi --query-compute-apps=pid --format=csv,noheader     # must be empty
# rehearsal: every gate, zero calls — must print REHEARSAL_PASS
JOINT_VERIFY_CONFIRMATORY_GO=1 python3 -m deadline_reward_v1.confirmatory_launch \
  --approved-p3-sha256 1201e9fc90e4f1f8640c1ea6b8355e24e4299ad766adaf610e4202992e0ba9cf \
  --approved-caps-sha256 c0def5d922cc98663c16a965d9874d4c92e030a73bf6c03f350ed45602bb12fe \
  --rehearse
```

## 2. Launch (ONLY the written GO)

Same command without `--rehearse`. The entry itself re-verifies every
gate (hashes, clean tree, GPU lock, unique dir) before the first
request.

## 3. Monitoring discipline (per the standing process corrections)

- Short NON-BLOCKING polls (≤10 min cadence; no long sleeps in the
  foreground): per-arm dispatch counts + wall clock from the run dir.
- NO manual intervention of any kind: any failure → the entry writes
  INCOMPLETE, stops the server, preserves ledgers; my only job is to
  OBSERVE and then report. No repair, no relaunch, no directory swap.
- Caps trip ⇒ INCOMPLETE by design (correct behavior, not an incident).

## 4. Completion verification checklist

1. `JOINT_VERIFY_RESULTS.json` exists with status COMPLETE and all 7
   stage statuses COMPLETE (else the INCOMPLETE twin governs).
2. Resource ledger: DISPATCH reserved == settled (+ any
   attempt_failed rows accounted); totals ≤ caps.
3. 360 settlement rows (60×6): every row has Q/C/T/D/on-time/
   R_conditional/R_full_task_cost_view/R_wall_deployment_view/
   switch fields; B1-style independent recomputation of a sample.
4. Per-task base attribution sums == base total.
5. Decision rows: pre-execution, no oracle keys; tier/fault draws
   match the freeze.
6. Analysis: `python3 -m deadline_reward_v1.joint_verify_analysis
   <results.json>` — the frozen pipeline; verdict language per
   JOINT_VERIFY_OUTCOME_INTERPRETATION_PREREG.md (no reinterpretation).
7. GPU freed; no leftover processes.

## 5. Reporting (fixed format)

PASS/INCOMPLETE; per-arm summary + the pre-registered contrasts with
CIs; degrade funnel + prediction-gap mechanism breakdown (runs
regardless of outcome); resource totals; anomalies; readiness verdict
for whatever the next stage is. No claim beyond the service-latency
ceiling; no equivalence readings; the negative-result path carries
equal prominence.

**This runbook authorizes nothing. Execution begins only at the
operator's written GO naming both hashes.**
