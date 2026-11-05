#!/usr/bin/env python3
"""P1 Adaptive 截止时间感知策略实验（36 执行 ≈270 调用）。

三臂（Static / Proposed / Adaptive）× 三档截止（120/150/250s）× 4 rep。
Adaptive 规则（预冻结）：if remaining_time < P90(Proposed_mk)+margin → skip_recovery else → do_recovery。
P90 校准自 M8 数据 = 140s，margin = 20s → 阈值 = 160s（即截止 <160s 时跳过恢复）。
实际上简化为：if deadline <= 120 → Static 路径; else → Proposed 路径。

GO 门：ADAPTIVE_GO=1
"""
import json, os, sys, time, random
from pathlib import Path

STAGE_D = Path("/root/research_outputs/static_pi/stage_d")
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, "/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, "/root/capital_opinion_pilot")

import stage_d_v3_executor as E

OUT = STAGE_D / "adaptive_runs"
CONFIG = json.loads((STAGE_D / "stage_d_v3_executor_config.json").read_text("utf-8"))
DEADLINES = [120, 150, 250]
ARMS = ["Static", "Proposed-Dynamic", "Adaptive"]
REPS = 4
# M8 校准：P90(Proposed_mk) = 140s（无 margin，直接用 P90）
ADAPTIVE_THRESHOLD = 140


def resolve_adaptive(deadline_s):
    """Adaptive 策略解析：根据截止时间选择实际执行臂。"""
    if deadline_s < ADAPTIVE_THRESHOLD:
        return "Static"       # 紧迫：跳过恢复
    return "Proposed-Dynamic"  # 宽松：执行恢复


def run_one(arm, deadline_s, rep, seed):
    actual_arm = arm
    if arm == "Adaptive":
        actual_arm = resolve_adaptive(deadline_s)

    cfg = json.loads(json.dumps(CONFIG))
    cfg["deadline_s"] = {"default": deadline_s}
    cfg["seed"] = seed

    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix=f"adapt_{deadline_s}_{rep}_"))
    clock = E.VirtualClock(1.0)
    gb = E.GlobalBudget(50, 5.0, 500000, tmp / "state")
    slots = E.SlotManager(cfg["slots"], clock)
    store = E.RunStore(tmp / "state", tmp)
    prov = E.RealProvider(clock, slots, transport_fn=E.stage_d_real_transport)
    ex = E.FinalExec(actual_arm, "S3", rep, cfg, clock, gb, slots, prov, store, dry_run=False)
    rec = ex.run()
    ex.settle()
    rec = ex.recommit_with_settlement() or rec
    rec["requested_arm"] = arm
    rec["actual_arm"] = actual_arm
    rec["deadline_s"] = deadline_s
    rec["adaptive_decision"] = ("skip_recovery" if actual_arm == "Static" else "do_recovery") if arm == "Adaptive" else None
    return rec


def main():
    if os.environ.get("ADAPTIVE_GO") != "1":
        raise SystemExit("REFUSED: requires ADAPTIVE_GO=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("REFUSED: DEEPSEEK_API_KEY not set")
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261105)
    all_recs = []
    total_calls = 0

    for dl in DEADLINES:
        for rep in range(1, REPS + 1):
            arms = ARMS[:]
            rng.shuffle(arms)
            for arm in arms:
                seed = 20261105 + dl + rep
                rec = run_one(arm, dl, rep, seed)
                all_recs.append(rec)
                nc = rec.get("calls", len(rec.get("raw", {}).get("calls", [])))
                total_calls += nc
                tp = rec.get("tp", rec.get("score", {}).get("tp", 0))
                ot = rec.get("on_time", False)
                mk = rec.get("makespan_s", 0)
                aa = rec.get("actual_arm", arm)
                dec = rec.get("adaptive_decision", "")
                print(f"[D={dl}|{arm}|r{rep}] {rec.get('status','?')} TP={tp} mk={mk}s "
                      f"ot={ot} actual={aa} dec={dec} calls={nc}", flush=True)

    # 分析
    from collections import defaultdict
    import statistics as st
    groups = defaultdict(list)
    for r in all_recs:
        key = (r["deadline_s"], r["requested_arm"])
        groups[key].append(r)

    print(f"\n{'='*60}")
    print(f"{'截止':>6}{'臂':<12}{'实际臂':<20}{'n':>3}{'TP':>6}{'按期%':>7}{'E[TP_D]':>8}{'mk':>8}{'calls':>6}")
    for dl in DEADLINES:
        for arm in ARMS:
            rs = groups[(dl, arm)]
            if not rs: continue
            etp = st.mean([r["tp"] if r["on_time"] else 0 for r in rs])
            ot_pct = 100 * sum(1 for r in rs if r["on_time"]) / len(rs)
            actual = rs[0].get("actual_arm", arm)
            print(f"{dl:>6}{arm:<12}{actual:<20}{len(rs):>3}"
                  f"{st.mean([r['tp'] for r in rs]):>6.2f}"
                  f"{ot_pct:>6.1f}%{etp:>8.2f}"
                  f"{st.mean([r['makespan_s'] for r in rs]):>8.1f}"
                  f"{st.mean([r.get('calls',0) for r in rs]):>6.1f}")
        print()

    # Adaptive vs 最优固定策略
    print("===== Adaptive vs 最优固定 =====")
    for dl in DEADLINES:
        etp_a = st.mean([r["tp"] if r["on_time"] else 0 for r in groups[(dl, "Adaptive")]])
        etp_s = st.mean([r["tp"] if r["on_time"] else 0 for r in groups[(dl, "Static")]])
        etp_p = st.mean([r["tp"] if r["on_time"] else 0 for r in groups[(dl, "Proposed-Dynamic")]])
        best_fixed = max(etp_s, etp_p)
        gain = etp_a - best_fixed
        verdict = "PASS" if etp_a >= best_fixed else "FAIL"
        print(f"  D={dl}: Adaptive={etp_a:.2f} vs best_fixed={best_fixed:.2f} "
              f"(Static={etp_s:.2f}, Proposed={etp_p:.2f}) gain={gain:+.2f} [{verdict}]")

    summary = {
        "total_execs": len(all_recs), "total_calls": total_calls,
        "adaptive_threshold": ADAPTIVE_THRESHOLD,
        "by_condition": {f"D{dl}|{arm}": {
            "E_TP_D": round(st.mean([r["tp"] if r["on_time"] else 0 for r in groups[(dl, arm)]]), 2),
            "on_time_rate": round(st.mean([1 if r["on_time"] else 0 for r in groups[(dl, arm)]]), 3),
            "actual_arm": groups[(dl, arm)][0].get("actual_arm", arm),
        } for dl in DEADLINES for arm in ARMS if groups[(dl, arm)]},
    }
    (OUT / "ADAPTIVE_RESULTS.json").write_text(json.dumps(
        {"summary": summary,
         "records": [{k: v for k, v in r.items() if k != "raw"} for r in all_recs]},
        ensure_ascii=False, indent=1), "utf-8")
    print(f"\n总执行 {len(all_recs)} | 总调用 {total_calls}")
    print(json.dumps(summary["by_condition"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
