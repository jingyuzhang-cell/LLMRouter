#!/usr/bin/env python3
"""MX机制实验分析: 按窗口三问题输出
Q1 决策差异: 每配对PD实际Z/R/π vs fc_would_do(影子) — 是否真实差异
Q2 质量收益: 同注入条件下配对ΔTP(含灾难判定)
Q3 成本时延: 配对ΔCost/ΔLatency
用法: python3 mech_analyze.py [mech_result.json]
"""
import json, sys

fp = sys.argv[1] if len(sys.argv) > 1 else "/root/research_outputs/RQ_DYN_V6_DESIGN/mech_experiment/mech_result.json"
d = json.load(open(fp))
runs = d["runs"]

# 配对重组
pairs = {}
for r in runs:
    key = (r["task"], r["scenario"], r["pair"])
    pairs.setdefault(key, {})[r["arm"]] = r

print(f"配对数: {len(pairs)} (预期12) | 执行数: {len(runs)} (预期24)\n")
print(f"{'任务':12s} {'场景':3s} {'配':2s} {'注入节点':6s} {'一致':3s} {'ΔTP':4s} {'ΔCost(¥)':9s} {'ΔLat(s)':8s} {'PD恢复':6s} {'FC恢复':6s} PD有效恢复")
w=t=l=0; sum_dc=0.0; sum_dl=0.0; eff_pd=0; eff_fc=0
for (task,sc,pair),pp in sorted(pairs.items()):
    pd, fc = pp.get("Proposed-Dynamic"), pp.get("Fixed-Composite")
    if not pd or not fc: print(f"{task} {sc} p{pair}: 缺臂!"); continue
    i_pd = pd["process_log"]["inject_trace"]["inject_node"]
    i_fc = fc["process_log"]["inject_trace"]["inject_node"]
    same = "✓" if i_pd==i_fc else "✗!"
    dtp = pd["tp"]-fc["tp"]; dcost = pd["cost_yuan"]-fc["cost_yuan"]; dlat = pd["makespan_s"]-fc["makespan_s"]
    w+=dtp>0; t+=dtp==0; l+=dtp<0; sum_dc+=dcost; sum_dl+=dlat
    # 恢复有效性(from derive_metrics internals: 重评corrupted直通TP)
    def eff(r):
        pl=r["process_log"]; texts=pl.get("_recovery_texts",{})
        import importlib.util
        spec=importlib.util.spec_from_file_location("v6ex","/root/research_outputs/RQ_DYN_V6_DESIGN/v6_executor.py")
        v6=importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
        for nl in pl["node_log"]:
            an=nl.get("anomaly") or (nl.get("anomaly_injected") and True)
            if not an: continue
            cor=texts.get(nl["node_id"]+"_cor"); 
            if cor is None: continue
            sim=dict(pl["final_outputs"]); sim[nl["node_id"]]=cor
            tp_cor=v6.score_tp(" ".join(str(v) for v in sim.values()), r.get("_slots",[]))
            return "有效" if r["tp"]>tp_cor else ("无效" if r["tp"]==tp_cor else "有害")
        return "—"
    e_pd, e_fc = eff(pd), eff(fc)
    if e_pd=="有效": eff_pd+=1
    if e_fc=="有效": eff_fc+=1
    print(f"{task:12s} {sc:3s} p{pair:<2d} {i_pd:6s} {same:3s} {dtp:+4d} {dcost:+9.4f} {dlat:+8.1f} {e_pd:4s}/{e_fc:4s}")

print(f"\n=== Q2 质量: PD胜{w}/平{t}/负{l} (12配对,同注入条件) ===")
print(f"=== Q3 成本: 平均ΔCost={sum_dc/len(pairs):+.4f}元 | 时延: 平均ΔLat={sum_dl/len(pairs):+.1f}s ===")
print(f"=== 恢复有效性: PD {eff_pd}/12 有效 | FC {eff_fc}/12 有效 ===")
print(f"=== Q1 决策差异(见下明细) ===")
m = d.get("metrics", {})
print(json.dumps(m, ensure_ascii=False, indent=1))
# Q1明细: PD实际决策vs影子
print("\nPD实际决策 vs 影子FC(前6条):")
for r in runs:
    if r["arm"]=="Proposed-Dynamic":
        for dd in r["process_log"]["decision_log"]:
            print(f"  {r['task']} {r['scenario']} p{r['pair']} 节点{dd['node_id']}: PD.Z={dd['Z']} | shadow.FC.Z={dd['shadow_other_arm']['Z']} | 恢复方式={dd.get('recovery_prompt_kind')}")
