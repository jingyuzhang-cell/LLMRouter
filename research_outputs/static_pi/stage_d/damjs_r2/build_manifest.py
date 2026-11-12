"""Builds DAMJS_R2_BATCH_MANIFEST.json (batch DAMJS_EXP_36) from the files on disk.

Runtime components are re-verified by every execution (pre and post) and by the runner before
and after a batch; non-runtime entries record provenance. Re-run after any registered file changes.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, str(HERE))
import damjs_bridge as BR
import damjs_r2_runner as R

RUNTIME = [
    ("child", "damjs_r2/damjs_r2_child.py"), ("bridge", "damjs_r2/damjs_bridge.py"),
    ("runner", "damjs_r2/damjs_r2_runner.py"), ("wrapper", "damsj_executor.py"), ("engine", "damsj_engine.py"),
    ("executor", "stage_d_v2_executor.py"), ("config", "stage_d_v2_executor_config.json"),
    ("dependency_d2", "d2_executor.py"),
    ("dependency_prompts", "/root/research_outputs/static_pi/stage_a/executor.py"),
    ("dependency_transport", "/root/capital_opinion_pilot/transport.py"),
    ("scorer", "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4/terminal_quality.py"),
    ("task_contract", "/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/TASK_CONTRACT_PHASE2B_v2_1.json"),
]
PROVENANCE = [
    ("test", "damjs_r2/test_damjs_r2.py"), ("test", "test_damsj_engine.py"), ("test", "test_damsj_executor.py"),
    ("screen", "damjs_r2/deadline_grid_check.py"), ("screen", "damjs_r2/DEADLINE_GRID_CHECK.json"),
    ("governance_tool", "damjs_r2/build_manifest.py"),
    ("prereg", "DAMJS_DESIGN.md"), ("prereg", "DAMJS_V0_2.md"), ("prereg", "DAMJS_V0_2_1.md"),
    ("governance", "EXECUTOR_IDENTITY_ERRATUM.md"), ("governance", "e_node_audit/E_NODE_COMPAT_AUDIT.md"),
    ("evidence", "e_node_audit/REPLAY_192_RESULTS.json"), ("evidence", "e_node_audit/replay_all_192.py"),
]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def entry(role, rel, runtime):
    p = rel if os.path.isabs(rel) else str(STAGE_D / rel)
    return dict(role=role, path=rel, sha256=sha(p), bytes=os.path.getsize(p), runtime=runtime)


def main():
    comps = [entry(r, p, True) for r, p in RUNTIME] + [entry(r, p, False) for r, p in PROVENANCE]
    comps += [entry("replay_source", f"runs_final/{a}__{s}__r{r}.json", False)
              for s in ("S3", "S4") for a in ("Static", "Proposed-Dynamic") for r in range(1, 9)]
    plan = R.build_order()
    mf = dict(
        batch_id=R.BATCH, created=time.strftime("%Y-%m-%dT%H:%M:%S"), status="FROZEN",
        authorization=dict(
            design="Design and engineering approved by the operator on 2026-11-06.",
            smoke=("GO 2026-11-06: 6 real executions (Static / Current-Proposed / DAMJS x S3, S4 x 240 s, rep 1), "
                   "phase caps 50 calls / 190,000 tokens / Y0.37 inside the batch caps; counted in the 36."),
            main="NOT authorized: the remaining 30 executions need a separate explicit GO after the smoke report.",
            credential_sources=dict(glm="provider entry bigmodel-api-6 (no fallback; stop if unavailable)",
                                    deepseek="provider entry deepseek"),
            credential_handling="injected into the child process environment only; never printed, logged or written to any file"),
        supersedes_for_new_runs="DAMJS_BATCH_MANIFEST.json (DAMJS_PILOT_54, INCOMPLETE, no admissible data); left unchanged",
        evidence_status="EXPLORATORY: 2 repetitions per cell; not confirmatory evidence",
        design=dict(
            arms={k: dict(executor_arm=v[0], policy=v[1]) for k, v in BR.ARM_MAP.items()},
            deadlines_s=R.DEADLINES, deadline_note="110 s dropped (Static S4 finishes within 95 s usable in 2/8 baseline runs)",
            scenarios=R.SCENARIOS, reps=R.REPS, executions=len(plan),
            phases=dict(smoke=[p["tag"] for p in plan if p["phase"] == "smoke"],
                        main=[p["tag"] for p in plan if p["phase"] == "main"]),
            order_seed=R.ORDER_SEED, order=[f"{p['phase']}:{p['tag']}" for p in plan],
            routing="A‴ (stage_d_v2_executor.AROUT/AMAX): E1-E4/J2/SINK DeepSeek thinking-off @4000; J1 GLM-5.3-Flash reasoning_effort=low @8192; FMT local",
            primary_comparison="DAMJS-Recovery vs Current-Proposed (paired within block); Static is the reference arm",
            metrics=dict(
                joint_success="TP >= 12 and the execution completes before D - 15 s (L3)",
                delta_tp="TP(DAMJS) - TP(Current-Proposed), paired by block",
                cost_increment="accounting Y and cash Y, DAMJS minus Current-Proposed, paired",
                latency_increment="makespan / elapsed, DAMJS minus Current-Proposed, paired",
                negative_gain_rate="share of blocks with TP(DAMJS) < TP(Current-Proposed)",
                worst_negative_gain="min over blocks of TP(DAMJS) - TP(Current-Proposed)",
                invalid_intervention_rate=("share of executed recovery actions whose re-executed node still shows the "
                                           "triggering signal, failed, or after which the run missed D - 15 s"),
                recovery_rounds="number of executed recovery actions per execution (and extra calls beyond the 7-call DAG)"),
            stop_rules=["a reservation denied by the batch ledger (INCOMPLETE_BUDGET)",
                        "any ledger metric at its cap, or headroom below the smallest single-call reservation",
                        "identity mismatch in any execution, or before/after the batch (INTEGRITY_FAIL)",
                        "a tag with a progress log but no result is never retried automatically (real mode)"]),
        scope=dict(
            validates="deadline-aware selective recovery (Z/R) against the existing dynamic recovery policy",
            does_not_validate="model switching (PI) or cross-agent migration (X'); multi-agent cooperative scheduling is NOT validated by this batch",
            damjs_action_space=list(BR.ALLOWED_KINDS), pi_enabled=False, x_prime_enabled=False,
            agents="fixed roster: one agent per role (extractor x4 capacity, reasoner, verifier, reporter, formatter); no compatible second agent exists for any node"),
        algorithm=dict(
            engine="damsj_engine.Scheduler (V0.2.1), unmodified: build_candidates -> select -> apply; GAIN_TABLE, reliable(), feasible(), Pareto, U weights 1.0/0.3/0.5, T_reserve 15 s",
            latency_prediction=("L_hat(a) = sum of per-node p95 wall over the nodes the executor re-runs because of a "
                                "(target plus invalidated descendants; FMT only for Z_format). p95 table frozen in "
                                "DAMJS_DESIGN.md section Q3. Replaces the engine's 2.0 s/call placeholder, per V0.2.1 correction 3. "
                                "sigma_l, cost and sigma_c are the engine's own estimates."),
            p95_wall_s=BR.P95_WALL,
            history=("Scheduler.apply() records a predicted-gain placeholder; when the re-executed target completes, "
                     "the placeholder is overwritten by the gold-blind observed gain: +1 triggering signal cleared, "
                     "0 signal persists, -1 node failed. C3-a / C3-b act on these observations."),
            current_q="0.0 (decision-equivalent: Q_current cancels in argmax U and is unused by feasible() since V0.2.1-R2)",
            executability=("Z_structure only for nodes with a repair spec (REPAIR_LIB); Z_format only before the first "
                           "format repair; Z_structure/R not after the executor's rerun cap (2)"),
            watchdog=dict(
                L2="every call's socket timeout = min(max(3*p95, 120 s), D_rem - 15 s) via the engine's effective_node_timeout (all arms)",
                L3="child refuses calls once D_rem <= 15 s or the cancel token exists; parent terminates the child at D - 15 s (all arms)",
                L4="degraded result from node_end outputs, minus invalidated ones, cut at the abort time; late results quarantined",
                anchor="all deadlines measured from the parent's launch; the child subtracts its startup offset (M5)"),
            current_proposed_note=("native V2 Proposed-Dynamic. Under A‴ routing a 'swap' re-runs the node on the same model "
                                   "(AROUT overrides the spec model): 89/89 swaps in the 192 baseline runs, S0-S4")),
        budget=dict(
            caps=R.CAPS, phase_caps=R.PHASE_CAPS, currency="accounting Y (GLM accounted at notional price, cash Y0)",
            authorization_remaining=dict(calls=377, tokens=1_348_528, yuan=2.3788),
            ledger="state/GLOBAL_BUDGET.json of the batch runs dir, shared by all child processes (stage_d_v2_executor.GlobalBudget)",
            reconciliation="after each child: worst-case charge (prompt chars + 64 + max_tokens; matching Y) for every call that errored or was cut off",
            per_execution="14 calls / Y0.18 (V2 config per_exec)",
            min_call_headroom=dict(tokens=R.MIN_CALL_TOKENS, yuan=R.MIN_CALL_YUAN)),
        identity=dict(per_execution="identity block with all runtime component SHAs, verified at child start and end",
                      batch="runner verifies every registered component before the first and after the last execution",
                      rule="any mismatch -> INTEGRITY_FAIL; results not admissible as evidence"),
        modes=dict(replay="zero-call acceptance: recorded responses through the executor's real handle, network tripwire, credentials stripped, records marked dry_run",
                   real="needs --mode real, STAGE_D_REAL_CALLS_AUTHORIZED=1 and DAMJS_R2_GO=<phase>; separate runs dir"),
        components=comps)
    out = STAGE_D / "DAMJS_R2_BATCH_MANIFEST.json"
    if out.exists():
        prev = json.loads(out.read_text("utf-8"))
        if {k: v for k, v in prev.items() if k != "created"} == {k: v for k, v in mf.items() if k != "created"}:
            mf["created"] = prev["created"]
    out.write_text(json.dumps(mf, ensure_ascii=False, indent=1), "utf-8")
    print(out, sha(out), f"{sum(c['runtime'] for c in comps)} runtime + {sum(not c['runtime'] for c in comps)} provenance")


if __name__ == "__main__":
    main()
