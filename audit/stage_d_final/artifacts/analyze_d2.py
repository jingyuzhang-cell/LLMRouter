#!/usr/bin/env python3
"""D2 聚合分析（零调用）：H1（S3 主/S4 次）、H2（瞬态+混合）、门禁校验、四问表。"""
import json, math
from pathlib import Path
OUT = Path("/root/research_outputs/static_pi/stage_d/runs_d2")
ARMS = ["Static", "R-only", "π-only", "Simple-Dynamic", "Fixed-Composite", "Proposed-Dynamic"]

recs = {}
invalid = []
for f in OUT.glob("*.json"):
    r = json.loads(f.read_text("utf-8"))
    recs[(r["arm"], r["scenario"], r["rep"])] = r
    if r.get("invalid_reason"): invalid.append(f'{r["arm"]}|{r["scenario"]}|r{r["rep"]}: {r["invalid_reason"]}')

def R(arm, sc, rep): return recs.get((arm, sc, rep))

print(f"记录 {len(recs)}/108 | 无效执行: {invalid or '无'}")
# 门禁 1 抽验：S3 持续性核验一致性
bad_g1 = [f'{a}|S3|r{k}' for a in ARMS for k in range(1, 6) if R(a, 'S3', k)
          and any(not c["consistent"] for c in R(a, 'S3', k)["fault_checks"] if c["node"] == "J1")]
print(f"门禁1 S3 持续性异常: {bad_g1 or '无'}")

print("\n=== 分场景六臂汇总（TP 均值 | F1F2 恢复率 | 调用均值 | makespan 均值 | 动作均值）===")
for sc, reps in (("S0", 2), ("S1", 3), ("S2", 3), ("S3", 5), ("S4", 5)):
    print(f"-- {sc} --")
    for arm in ARMS:
        rs = [R(arm, sc, k) for k in range(1, reps + 1)]
        rs = [r for r in rs if r]
        if not rs: continue
        tp = sum(r["tp"] for r in rs) / len(rs)
        f12 = sum(1 for r in rs if r["F1_ok"] and r["F2_ok"]) / len(rs)
        cl = sum(r["calls"] for r in rs) / len(rs)
        ms = sum(r["makespan_s"] for r in rs) / len(rs)
        ac = sum(len(r["actions"]) for r in rs) / len(rs)
        print(f"  {arm:18s} TP={tp:5.2f} F1F2={f12:.0%} calls={cl:5.1f} ms={ms:6.1f}s acts={ac:4.1f}")

print("\n=== H1 主判定：S3 Proposed vs Simple（配对 r1-r5，符号检验含平局规则）===")
pairs = []
for k in range(1, 6):
    p, s = R("Proposed-Dynamic", "S3", k), R("Simple-Dynamic", "S3", k)
    if p and s: pairs.append((k, p["tp"], s["tp"]))
for k, a, b in pairs: print(f"  r{k}: {a} v {b} → {'胜' if a>b else ('平' if a==b else '负')}")
wins = sum(1 for _, a, b in pairs if a > b); ties = sum(1 for _, a, b in pairs if a == b); n = len(pairs) - ties
if n: print(f"  有效对 n={n}（平局 {ties} 对剔除并列出如上）全胜 p={0.5**n:.4f} → {'显著(单侧0.05)' if wins==n and 0.5**n<0.05 else '未达显著/方向性'}")

print("\n=== H1 次要：S4 Proposed vs Simple ===")
pairs4 = [(k, R("Proposed-Dynamic", "S4", k)["tp"], R("Simple-Dynamic", "S4", k)["tp"])
          for k in range(1, 6) if R("Proposed-Dynamic", "S4", k) and R("Simple-Dynamic", "S4", k)]
for k, a, b in pairs4: print(f"  r{k}: {a} v {b} → {'胜' if a>b else ('平' if a==b else '负')}")
w4 = sum(1 for _, a, b in pairs4 if a > b); t4 = sum(1 for _, a, b in pairs4 if a == b); n4 = len(pairs4) - t4
if n4: print(f"  n={n4} 全胜 p={0.5**n4:.4f}")

print("\n=== H2：瞬态+混合（S1/S2 逐执行 vs Simple 与 Fixed）===")
for sc in ("S1", "S2"):
    for k in range(1, 4):
        p = R("Proposed-Dynamic", sc, k); s = R("Simple-Dynamic", sc, k); f_ = R("Fixed-Composite", sc, k)
        if not (p and s and f_): continue
        print(f"  {sc}r{k}: TP {p['tp']}v{s['tp']}(Δ{p['tp']-s['tp']:+d}) / v{f_['tp']}(Δ{p['tp']-f_['tp']:+d}) | "
              f"calls {p['calls']}v{s['calls']}v{f_['calls']} | ms {p['makespan_s']}v{s['makespan_s']}v{f_['makespan_s']}s")

print("\n=== S0 误触发（四问之三）===")
for arm in ARMS:
    acts = sum(len(R(arm, "S0", k)["actions"]) for k in (1, 2) if R(arm, "S0", k))
    print(f"  {arm:18s} S0 动作总数 {acts}")

print("\n=== 四问对齐 ===")
if all(R("Proposed-Dynamic", s, 1) for s in ("S3", "S4", "S0")):
    s3 = [R("Proposed-Dynamic", "S3", k) for k in range(1, 6)]
    s4 = [R("Proposed-Dynamic", "S4", k) for k in range(1, 6)]
    print(f"  Q1 持续结构缺陷→修复: {sum(1 for r in s3 if r['F1_ok'] and r['F2_ok'])}/5 F1F2 恢复")
    print(f"  Q2 持续格式缺陷→另一动作: FMT 修复 TP {sum(r['tp'] for r in s4)/5:.1f}（对照 Simple S4）")
    print(f"  Q3 正常不动: S0 动作 {sum(len(R('Proposed-Dynamic','S0',k)['actions']) for k in (1,2))}/2 执行")
    print(f"  Q4 不可辨识→UNKNOWN: D2 无 A3 型场景（预登记边界）")
