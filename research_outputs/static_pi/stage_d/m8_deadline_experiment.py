#!/usr/bin/env python3
"""M8-4 截止时间约束实验（授权 2026-11-04；36 执行 ≈280 调用）。

三档截止（120/150/250s）× 三策略（Static/Simple/Proposed）× 4 rep。
核心验证：中等截止下 E[TP] 是否翻转（Static > Proposed）。

复用 Stage D v3 执行器（B-1 守卫 + B-2 换模 + 失败感知降级），
每档截止 = 独立 GlobalBudget + SlotManager。
策略语义：
  Static    = 无动态恢复动作（守卫触发→Failed）
  Simple    = 盲目重试（同模型重跑一次）
  Proposed  = 诊断驱动联合调度（守卫→诊断→匹配动作→失败感知降级）

GO 门：M8_GO=1；凭据 env。
"""
import json, os, sys, time, random
from pathlib import Path

STAGE_D = Path("/root/research_outputs/static_pi/stage_d")
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, "/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, "/root/capital_opinion_pilot")

import stage_d_v3_executor as E

OUT = STAGE_D / "m8_runs"
CONFIG_BASE = json.loads((STAGE_D / "stage_d_v3_executor_config.json").read_text("utf-8"))
DEADLINES = [120, 150, 250]
ARMS = ["Static", "Simple-Dynamic", "Proposed-Dynamic"]
REPS = 4


def run_one(arm, deadline_s, rep, seed):
    cfg = json.loads(json.dumps(CONFIG_BASE))
    cfg["deadline_s"] = {"default": deadline_s}
    cfg["seed"] = seed
    import tempfile, copy
    tmp = Path(tempfile.mkdtemp(prefix=f"m8_{deadline_s}_{rep}_"))
    clock = E.VirtualClock(1.0)
    gb = E.GlobalBudget(50, 5.0, 500000, tmp / "state")
    slots = E.SlotManager(cfg["slots"], clock)
    store = E.RunStore(tmp / "state", tmp)
    import urllib.request
    prov = E.RealProvider(clock, slots, transport_fn=E.stage_d_real_transport)
    ex = E.FinalExec(arm, "S3", rep, cfg, clock, gb, slots, prov, store, dry_run=False)
    rec = ex.run()
    ex.settle()
    rec = ex.recommit_with_settlement() or rec
    rec["deadline_s"] = deadline_s
    return rec


def main():
    if os.environ.get("M8_GO") != "1":
        raise SystemExit("REFUSED: requires M8_GO=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("REFUSED: DEEPSEEK_API_KEY not set")
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261104)
    all_recs = []
    total_calls = 0
    for dl in DEADLINES:
        for rep in range(1, REPS + 1):
            # 随机臂序
            arms = ARMS[:]
            rng.shuffle(arms)
            for arm in arms:
                seed = 20261104 + dl + rep
                rec = run_one(arm, dl, rep, seed)
                all_recs.append(rec)
                total_calls += rec.get("calls", 0) or len(rec.get("raw", {}).get("calls", []))
                tp = rec.get("tp", rec.get("score", {}).get("tp", 0))
                status = rec.get("status", "?")
                mk = rec.get("makespan_s", 0)
                ot = rec.get("on_time", False)
                print(f"[D={dl}|{arm}|r{rep}] {status} TP={tp} mk={mk}s on_time={ot} "
                      f"calls={rec.get('calls', len(rec.get('raw', {}).get('calls', [])))}", flush=True)

    # 分析
    from collections import defaultdict
    import statistics as st
    groups = defaultdict(lambda: {"tp": [], "ot": [], "mk": [], "calls": [], "status": []})
    for r in all_recs:
        key = (r["deadline_s"], r["arm"])
        g = groups[key]
        g["tp"].append(r.get("tp", 0))
        g["ot"].append(1 if r.get("on_time") else 0)
        g["mk"].append(r.get("makespan_s", 0))
        g["calls"].append(r.get("calls", len(r.get("raw", {}).get("calls", []))))
        g["status"].append(r.get("status", "?"))

    print("\n=== M8-4 结果 ===")
    print(f"{'截止':>6}{'臂':<20}{'TP':>6}{'按期%':>7}{'E[TP]':>7}{'mk':>8}{'calls':>6}{'INCOMP':>7}")
    for dl in DEADLINES:
        for arm in ARMS:
            g = groups[(dl, arm)]
            n = len(g["tp"])
            tp_mean = st.mean(g["tp"]) if g["tp"] else 0
            ot_rate = st.mean(g["ot"]) if g["ot"] else 0
            # E[TP] = 按期时实际 TP 均值 × 按期率（超时=0 已隐含在 tp 中）
            e_tp = tp_mean  # tp 已含超时零分
            print(f"{dl:>6}{arm:<20}{tp_mean:>6.2f}{100*ot_rate:>6.1f}%{e_tp:>7.2f}"
                  f"{st.mean(g['mk']):>8.1f}{st.mean(g['calls']):>6.1f}"
                  f"{sum(1 for s in g['status'] if 'INCOMPLETE' in s):>7}")

    summary = {
        "total_execs": len(all_recs), "total_calls": total_calls,
        "by_deadline": {str(dl): {arm: {
            "tp_mean": round(st.mean(groups[(dl, arm)]["tp"]), 2),
            "on_time_rate": round(st.mean(groups[(dl, arm)]["ot"]), 3),
            "mk_mean": round(st.mean(groups[(dl, arm)]["mk"]), 1),
            "calls_mean": round(st.mean(groups[(dl, arm)]["calls"]), 1),
        } for arm in ARMS} for dl in DEADLINES},
    }
    (OUT / "M8_RESULTS.json").write_text(json.dumps(
        {"summary": summary, "records": [{k: v for k, v in r.items() if k != "raw"} for r in all_recs]},
        ensure_ascii=False, indent=1), "utf-8")
    print(f"\n总执行 {len(all_recs)} | 总调用 {total_calls}")
    print(json.dumps(summary["by_deadline"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
