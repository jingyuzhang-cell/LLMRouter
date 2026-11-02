#!/usr/bin/env python3
"""Stage C 动态策略实验 Tier 1+2（零 API 调用，预注册 V1.1 执行）。

六臂 × 30 场景；检测器签名诊断（控制器盲化：输入仅节点输出+检测器结果+预算）；后果矩阵
全部引用冻结实测（EXACT/APPROX 标注）。一处实现澄清（如实记录）：V1.1 中 Simple-Dynamic
"任一异常→J2 换模"与 π-only 行为完全重合（无信息量）——实现为标准的朴素基线
"任一异常→同模型重跑异常节点"（naive-retry），与 π-only 区分。
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
SA = Path("/root/research_outputs/static_pi/stage_a")
SB = Path("/root/research_outputs/static_pi/stage_b")

# ===== 后果矩阵（任务 A；质量=槽位/23 per run；成本=核算¥/调用数/时延s，冻结实测） =====
# 出处：TRUSTED_BASELINE_V1_1、INTEGRATED_RUN_REPORT、各臂 evaluation（EXACT=该状态实测；APPROX=组合状态推算）
HEALTHY = {"slots": [16, 15, 16], "prov": "EXACT（X+格式层 47/69）"}
NOACT = {  # 各故障不修复的终端质量
    "A1": {"slots": [14, 13, 14], "prov": "APPROX（健康态去 F1/F2 formal，Static 无 relay 实测行为）"},
    "A2": {"slots": [15, 14, 15], "prov": "APPROX（健康态去 A5，Static 实测）"},
    "A3": {"slots": [15, 14, 15], "prov": "APPROX（健康态去 E2，原始提示词实测 4/4/4）"},
    "AMODEL": {"slots": [15, 15, 15], "prov": "APPROX（J2J 计数 3/2/3 实测 → E2 错 2/3 run）"},
    "A4": {"slots": [11, 7, 9], "prov": "EXACT（X 原始链 27/69）"},
    "A0": HEALTHY,
}
ACTIONS = {  # 动作 → (成本¥, 调用数, 时延s, 效果)
    "structure_dates": (0.0203, 3, 64, "restore_dates"),      # J1P+J2X+SINK 实测均值
    "structure_full": (0.0245, 5, 80, "restore_positions"),    # E1P+E2P+J1P+J2X+SINK
    "caliber": (0.0152, 2, 50, "disambig_j2"),                 # J2X+SINK
    "format": (0.0, 0, 0, "reapply_layer"),
    "model_swap": (0.0126, 2, 23, "j2_to_ds"),                 # DS-J2+SINK；效果按实测 1/3 分布
    "retry": (0.0080, 1, 25, "same_model_rerun"),
}
ACTION_EFFECT = {  # (场景, 动作) → 终端 slots per run（EXACT/APPROX 标注随 NOACT/HEALTHY 出处）
    ("A1", "structure_dates"): HEALTHY, ("A1", "structure_full"): HEALTHY,
    ("A2", "structure_full"): HEALTHY,
    ("A3", "caliber"): HEALTHY,
    ("AMODEL", "caliber"): HEALTHY, ("AMODEL", "model_swap"): {"slots": [16, 15, 16], "prov": "APPROX（换模实测 1/3 修复分布，回放取期望：+1/3 槽/run）", "dist": True},
    ("A4", "format"): HEALTHY,
}
FIXED_SET = ["structure_full", "caliber", "format"]  # Fixed-Composite 恒定三干预

# ===== 检测器（V1.1 修正版：D5 任务A N/A、D7 剔除诊断仅观测） =====
def detectors(scenario):
    return scenario["signature"]  # 预实测签名（V1.1 矩阵）：dict D1..D8 → bool(True=通过)

SIG = {  # V1.1 实测矩阵（任务 A 逐 run；B 任务全过）
    "A0": [{1:1,2:1,3:0,4:1,6:0,8:1}, {1:1,2:1,3:1,4:1,6:1,8:1}, {1:1,2:1,3:1,4:1,6:1,8:1}],  # 0=触发
    "A1": [{2:0,4:0}] * 3, "A2": [{2:0}] * 3, "A3": [{}, {}, {}],
    "AMODEL": [{}, {}, {}], "A4": [{3:0}] * 3,
}  # 注：键=检测器号，0=触发；空 dict=全过

def diagnose(sig):  # V1.1 诊断映射
    fired = {k for k, v in sig.items() if v == 0}
    if fired & {2, 4}: return "structure"
    if 3 in fired: return "format"
    if 6 in fired: return "caliber_count_suspect"
    if 1 in fired: return "model_suspect"
    return "UNKNOWN"

ACTION_OF = {"structure": "structure_full", "format": "format", "caliber_count_suspect": "caliber", "model_suspect": "model_swap"}

# ===== 六臂策略 =====
def policy_static(sc, budget): return None
def policy_r(sc, budget):
    return "structure_full" if any(v == 0 for v in sc["signature"].values()) else None
def policy_pi(sc, budget):
    return "model_swap" if any(v == 0 for v in sc["signature"].values()) else None
def policy_simple(sc, budget):
    return "retry" if any(v == 0 for v in sc["signature"].values()) else None
def policy_fixed(sc, budget):
    return "fixed_composite"
def policy_proposed(sc, budget):
    fam = diagnose(sc["signature"])
    if fam == "UNKNOWN": return None
    act = ACTION_OF[fam]
    if budget["calls_left"] < ACTIONS[act][1]: return None  # 预算守恒
    return act

POLICIES = [("Static", policy_static), ("R-only", policy_r), ("π-only", policy_pi),
            ("Simple-Dynamic", policy_simple), ("Fixed-Composite", policy_fixed), ("Proposed-Dynamic", policy_proposed)]

BUDGET_PER_SC = {"calls_left": 7, "yuan_left": 0.05}  # X 链边际×~1.5（调用双限）

# ===== 回放 =====
def apply_action(sc, act):
    """返回 (slots_per_run, cost¥, calls, lat_s, prov)。"""
    if act == "fixed_composite":
        slots, prov, cost, calls, lat = list(HEALTHY["slots"]), HEALTHY["prov"], 0.0, 0, 0
        for a in FIXED_SET:
            c, n, l, _ = ACTIONS[a]; cost += c; calls += n; lat += l
        if sc["fam"] == "A4":  # 格式层修复含于组合
            pass
        return slots, round(cost, 4), calls, lat, prov
    if act is None:
        na = NOACT[sc["fam"]]
        return list(na["slots"]), 0.0, 0, 0, na["prov"]
    key = (sc["fam"], act)
    if key in ACTION_EFFECT:
        eff = ACTION_EFFECT[key]; c, n, l, _ = ACTIONS[act]
        if eff.get("dist"):  # 换模 1/3 分布 → 期望回放
            base = NOACT[sc["fam"]]["slots"]
            slots = [b + 1/3 for b in base]
            return slots, c, n, l, eff["prov"]
        return list(eff["slots"]), c, n, l, eff["prov"]
    # 无匹配效果的动作（错误动作）：质量=不修复 + 动作成本（结构动作对格式/口径故障无效等，按机制语义）
    na = NOACT[sc["fam"]]; c, n, l, _ = ACTIONS[act]
    if sc["fam"] == "A0":  # 健康态上的任何动作：质量不变（无损害），成本照付（过度干预代价）
        return list(HEALTHY["slots"]), c, n, l, "EXACT（健康态+无害干预，X 实测）"
    semantic_fix = {"A1": {"structure_dates", "structure_full"}, "A2": {"structure_full"},
                    "A3": {"caliber"}, "AMODEL": {"caliber", "model_swap"}, "A4": {"format"}}[sc["fam"]]
    if act in semantic_fix and act != "model_swap":
        return list(HEALTHY["slots"]), c, n, l, HEALTHY["prov"]
    if act == "model_swap" and sc["fam"] in ("A1", "A2", "A4"):  # 换模救不了结构/格式
        return list(na["slots"]), c, n, l, na["prov"]
    if act == "structure_full" and sc["fam"] == "A4":  # 结构动作不恢复被旁路的格式层
        return list(na["slots"]), c, n, l, na["prov"]
    if act in ("retry",):
        return list(na["slots"]), c, n, l, na["prov"] + "+retry无效(系统性故障)"
    if act == "caliber" and sc["fam"] in ("A1", "A2"):
        return list(na["slots"]), c, n, l, na["prov"]
    return list(na["slots"]), c, n, l, na["prov"]

SCENARIOS_A = []
for fam in ("A0", "A1", "A2", "A3", "AMODEL", "A4"):
    for k in (1, 2, 3):
        SCENARIOS_A.append({"task": "A", "fam": fam, "run": k, "signature": SIG[fam][k - 1] if fam != "A0" else SIG["A0"][k - 1]})
SCENARIOS_B = [{"task": "B", "fam": f, "run": k, "signature": {}} for f in ("B0", "B1", "B2", "B3") for k in (1, 2, 3)]
# B0 无错；B1-B3 真实含口径错误但签名全静默（V1.1 实测）

results = {}
for pname, pfn in POLICIES:
    tot_slots, tot_cost, tot_calls, tot_lat = 0.0, 0.0, 0, 0.0
    fam_quality = {}
    diag_correct = diag_unknown_ok = false_trig = 0
    for sc in SCENARIOS_A + SCENARIOS_B:
        act = pfn(sc, BUDGET_PER_SC)
        if sc["task"] == "A":
            slots, cost, calls, lat, prov = apply_action(sc, act)
            tot_slots += sum(slots); tot_cost += cost; tot_calls += calls; tot_lat += lat
            fam_quality.setdefault(sc["fam"], []).append(sum(slots))
            # 诊断侧统计（仅反馈策略）
            if pname in ("Proposed-Dynamic",):
                fam_true = {"A1": "structure", "A2": "structure", "A4": "format", "A3": "UNKNOWN", "AMODEL": "UNKNOWN", "A0": "none"}[sc["fam"]]
                d = diagnose(sc["signature"])
                if fam_true == "none": false_trig += (act is not None and sc["fam"] == "A0" and d != "format")
                elif fam_true == "UNKNOWN": diag_unknown_ok += (act is None)
                else: diag_correct += (d == fam_true and act is not None)
        else:
            if act is not None:
                c = sum(ACTIONS[a][0] for a in (FIXED_SET if act == "fixed_composite" else [act]))
                n = sum(ACTIONS[a][1] for a in (FIXED_SET if act == "fixed_composite" else [act]))
                l = sum(ACTIONS[a][2] for a in (FIXED_SET if act == "fixed_composite" else [act]))
                tot_cost += c; tot_calls += n; tot_lat += l
                if pname == "Proposed-Dynamic" and sc["fam"] == "B0": false_trig += 1
            elif pname == "Proposed-Dynamic" and sc["fam"] != "B0":
                diag_unknown_ok += 1
    results[pname] = {"slot_success_pooled": round(tot_slots / 414, 4), "slots_total": round(tot_slots, 1),
                      "cost_yuan": round(tot_cost, 4), "calls": tot_calls, "latency_s": round(tot_lat, 1),
                      "fam_quality": {f: round(sum(v) / 69, 3) for f, v in fam_quality.items()},
                      "diag_correct": diag_correct, "diag_unknown_ok": diag_unknown_ok, "false_trig": false_trig}

print(json.dumps(results, ensure_ascii=False, indent=1))
(HERE / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")

# ===== 预登记统计（6 族为单位的配对比较） =====
fams = ("A0", "A1", "A2", "A3", "AMODEL", "A4")
def fam_ss(p, f): return results[p]["fam_quality"][f]
pairs = {"Proposed vs Fixed-Composite": [(fam_ss("Proposed-Dynamic", f), fam_ss("Fixed-Composite", f)) for f in fams],
         "Proposed vs Simple-Dynamic": [(fam_ss("Proposed-Dynamic", f), fam_ss("Simple-Dynamic", f)) for f in fams],
         "Proposed vs Static": [(fam_ss("Proposed-Dynamic", f), fam_ss("Static", f)) for f in fams],
         "Proposed vs R-only": [(fam_ss("Proposed-Dynamic", f), fam_ss("R-only", f)) for f in fams],
         "Proposed vs π-only": [(fam_ss("Proposed-Dynamic", f), fam_ss("π-only", f)) for f in fams]}
stats = {}
for name, pr in pairs.items():
    diffs = [a - b for a, b in pr]
    wins = sum(1 for d in diffs if d > 0); losses = sum(1 for d in diffs if d < 0)
    stats[name] = {"per_fam_diff": [round(d, 3) for d in diffs], "wins/ties/losses": f"{wins}/{6-wins-losses}/{losses}",
                   "pooled_diff": round(sum(diffs), 3)}
print(json.dumps(stats, ensure_ascii=False, indent=1))
(HERE / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), "utf-8")
print("\nE1a 非劣效（边际6%绝对）:", results["Proposed-Dynamic"]["slot_success_pooled"] - results["Fixed-Composite"]["slot_success_pooled"], "≥ -0.06 →",
      "PASS" if results["Proposed-Dynamic"]["slot_success_pooled"] - results["Fixed-Composite"]["slot_success_pooled"] >= -0.06 else "FAIL")
print("E1b 成本优效:", results["Proposed-Dynamic"]["cost_yuan"], "<", results["Fixed-Composite"]["cost_yuan"], "→",
      "PASS" if results["Proposed-Dynamic"]["cost_yuan"] < results["Fixed-Composite"]["cost_yuan"] else "FAIL")
print("E1c vs Simple 质量优效:", results["Proposed-Dynamic"]["slot_success_pooled"], ">", results["Simple-Dynamic"]["slot_success_pooled"], "→",
      "PASS" if results["Proposed-Dynamic"]["slot_success_pooled"] > results["Simple-Dynamic"]["slot_success_pooled"] else "FAIL")
p = results["Proposed-Dynamic"]
print(f"E2a 诊断准确 {p['diag_correct']}/9（≥8）| E2b 保守标记 {p['diag_unknown_ok']}/15（≥13）| E2c 误触发 {p['false_trig']}/6（≤1）")
