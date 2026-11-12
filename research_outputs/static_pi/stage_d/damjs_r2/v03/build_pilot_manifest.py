"""Builds DAMJS_V03_PILOT_MANIFEST.json from the files on disk (idempotent: unchanged content keeps
its `created` stamp). Runtime components are verified by every execution (pre/post) and by the runner
before/after a batch. Re-run after any registered file changes (e.g. after the prereg is frozen)."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import v03_runner as VR

RUNTIME = [
    ("v03_child", "damjs_r2/v03/v03_child.py"), ("v03_runner", "damjs_r2/v03/v03_runner.py"),
    ("v03_mechanisms", "damjs_r2/v03/damjs_v03.py"), ("r2_child_lib", "damjs_r2/damjs_r2_child.py"),
    ("r2_runner_lib", "damjs_r2/damjs_r2_runner.py"), ("bridge", "damjs_r2/damjs_bridge.py"),
    ("wrapper", "damsj_executor.py"), ("engine", "damsj_engine.py"), ("executor", "stage_d_v2_executor.py"),
    ("config", "stage_d_v2_executor_config.json"), ("dependency_d2", "d2_executor.py"),
    ("dependency_prompts", "/root/research_outputs/static_pi/stage_a/executor.py"),
    ("dependency_transport", "/root/capital_opinion_pilot/transport.py"),
    ("scorer", "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4/terminal_quality.py"),
    ("task_contract", "/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/TASK_CONTRACT_PHASE2B_v2_1.json"),
]
PROVENANCE = [
    ("prereg_mechanisms", "DAMJS_V0_3.md"), ("prereg_draft", "DAMJS_V0_3_PILOT_PREREG_DRAFT.md"),
    ("validation", "damjs_r2/v03/V03_VALIDATION_RESULTS.json"), ("validation", "damjs_r2/v03/V03_VALIDATION_REPORT.md"),
    ("test", "damjs_r2/v03/test_damjs_v03.py"), ("test", "damjs_r2/v03/test_v03_pilot.py"),
    ("governance", "R2_FREEZE.json"), ("governance", "damjs_r2/v03/V03_FREEZE.json"),
    ("governance_tool", "damjs_r2/v03/build_pilot_manifest.py"),
    ("validation", "damjs_r2/v03/V03_VALIDATION_RESULTS_v2.json"),
    ("test", "damjs_r2/v03/test_v03_prelaunch.py"),
    ("audit", "damjs_r2/v03/ev_prior_audit.py"), ("audit", "damjs_r2/v03/EV_PRIOR_AUDIT.json"),
    ("caliber_transform", "damjs_r2/v03/caliber_revision.py"), ("audit", "damjs_r2/v03/CALIBER_REVISION.json"),
    ("erratum", "damjs_r2/v03/DAMJS_V0_3_PILOT_ERRATUM_1.md"), ("erratum", "damjs_r2/v03/DAMJS_V0_3_PILOT_ERRATUM_2.md"),
    ("prereg_draft", "damjs_r2/v03/DAMJS_ND_CONTROLLED_PREREG_DRAFT.md"),
    ("replay_source", "damjs_r2/runs_real/exec_records/Current-Proposed__S4__r1__D240.json"),
    ("replay_source", "damjs_r2/runs_real/exec_records/DAMJS__S3__r1__D240.json"),
    ("replay_source", "damjs_r2/runs_real/exec_records/DAMJS__S4__r1__D240.json"),
]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def entry(role, rel, runtime):
    p = rel if os.path.isabs(rel) else str(STAGE_D / rel)
    return dict(role=role, path=rel, sha256=sha(p), bytes=os.path.getsize(p), runtime=runtime)


def main():
    comps = [entry(r, p, True) for r, p in RUNTIME]
    comps += [entry(r, p, False) for r, p in PROVENANCE if (STAGE_D / p).exists()]
    frozen = VR.PREREG_FROZEN.exists()
    if frozen:
        comps.append(entry("prereg_frozen", VR.PREREG_FROZEN.name, False))
    mf = dict(
        batch_id=VR.BATCH, created=time.strftime("%Y-%m-%dT%H:%M:%S"),
        status="FROZEN_PREREG" if frozen else "WIRING_ACCEPTANCE_ONLY",
        authorization=("No real call is authorized. Real mode is code-locked until the operator-approved prereg "
                       "DAMJS_V0_3_PILOT_PREREG.md (declaring PILOT_PLAN=<A|B>) is frozen and registered here, "
                       "and STAGE_D_REAL_CALLS_AUTHORIZED=1 with DAMJS_V03_GO=<plan>:<phase> is given."),
        plans={k: dict(arms=v["arms"], reps=v["reps"], smoke_blocks=v["smoke_blocks"], caps=v["caps"],
                       executions=len(VR.build_order(k)), order=[f"{p['phase']}:{p['tag']}" for p in VR.build_order(k)])
               for k, v in VR.PLANS.items()},
        smoke_phase_caps=VR.SMOKE_CAPS, deadline_s=VR.DEADLINE, order_seed=VR.ORDER_SEED,
        arms_switches={"R2": "nd=off ev=off", "ND-only": "nd=on ev=off", "EV-only": "nd=off ev=on", "V0.3": "nd=on ev=on"},
        authorization_ceiling=dict(remaining_at_ruling=VR.AUTH, shared_with="damjs_r2/runs_real R2 ledger",
                                   rule="effective caps = min(plan/phase caps, authorization - R2 ledger)"),
        stop_rules=["R2 rules (INCOMPLETE_BUDGET, cap reached, INTEGRITY_FAIL, orphan attempt)",
                    "V03_PATH_EXCEPTION: traceback through damjs_v03",
                    "C1_VIOLATION: ND arm committed an invalid output over a valid one"],
        dual_caliber="every execution records tp (lenient) and tp_strict (CORRECT_GOLD) + unsupported list",
        components=comps)
    out = STAGE_D / "DAMJS_V03_PILOT_MANIFEST.json"
    if out.exists():
        prev = json.loads(out.read_text("utf-8"))
        if {k: v for k, v in prev.items() if k != "created"} == {k: v for k, v in mf.items() if k != "created"}:
            mf["created"] = prev["created"]
    out.write_text(json.dumps(mf, ensure_ascii=False, indent=1), "utf-8")
    print(out.name, sha(out), f"{sum(c['runtime'] for c in comps)} runtime + {sum(not c['runtime'] for c in comps)} provenance",
          "| prereg frozen:", frozen)


if __name__ == "__main__":
    main()
