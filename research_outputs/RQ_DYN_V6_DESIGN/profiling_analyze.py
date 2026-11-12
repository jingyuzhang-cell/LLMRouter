#!/usr/bin/env python3
"""Profiling结果分析: 四类节点能力画像 + 六指标"""
import json, statistics as st
from collections import defaultdict

d = json.load(open("/root/research_outputs/RQ_DYN_V6_DESIGN/profiling_runs/PROFILING_RESULTS.json"))
rs = d["results"]
print(f"执行: {d['done']}/56次 | 花费¥{d['spent']:.4f} | 用时{d['elapsed_min']}分钟\n")

def agg(rows):
    n=len(rows)
    if not n: return None
    parse=sum(1 for r in rows if r["contract"].get("json_parsed"))/n
    comp=[r["contract"].get("completeness",0) for r in rows]
    ev=[r["contract"].get("evidence",0) for r in rows if r["contract"].get("evidence") is not None]
    viol=sum(1 for r in rows if r["contract"].get("contract_violation"))/n
    lat=[r["latency"] for r in rows]
    cost=[r["cost_yuan"] for r in rows]
    return dict(n=n, parse_rate=round(parse,3), comp_mean=round(st.mean(comp),3),
                evid_mean=round(st.mean(ev),3) if ev else None,
                viol_rate=round(viol,3), lat_mean=round(st.mean(lat),1),
                lat_range=(min(lat),max(lat)), cost_mean=round(st.mean(cost),5),
                cost_sum=round(sum(cost),4))

print("=== 一、按节点类型×模型 ===")
print(f"{'kind':13s} {'model':15s} {'n':2s} {'解析率':6s} {'完整性':6s} {'证据性':6s} {'违约率':6s} {'时延s':8s} {'成本¥'}")
by=defaultdict(list)
for r in rs: by[(r["kind"], r["model"])].append(r)
for (k,m),rows in sorted(by.items()):
    a=agg(rows)
    print(f"{k:13s} {m:15s} {a['n']:2d} {a['parse_rate']:6.2f} {a['comp_mean']:6.2f} "
          f"{(a['evid_mean'] if a['evid_mean'] is not None else -1):6.2f} {a['viol_rate']:6.2f} "
          f"{a['lat_mean']:8.1f} {a['cost_mean']:.5f}")

print("\n=== 二、按复杂度层级×模型 ===")
by2=defaultdict(list)
for r in rs: by2[(r["tier"], r["model"])].append(r)
print(f"{'tier':4s} {'model':15s} {'n':2s} {'解析率':6s} {'完整性':6s} {'证据性':6s} {'时延s':8s}")
for (t,m),rows in sorted(by2.items()):
    a=agg(rows)
    print(f"{t:4s} {m:15s} {a['n']:2d} {a['parse_rate']:6.2f} {a['comp_mean']:6.2f} "
          f"{(a['evid_mean'] if a['evid_mean'] is not None else -1):6.2f} {a['lat_mean']:8.1f}")

print("\n=== 三、模型总体对比 ===")
for m in sorted(set(r["model"] for r in rs)):
    a=agg([r for r in rs if r["model"]==m])
    print(f"  {m:15s} n={a['n']:2d} 解析{a['parse_rate']:.2f} 完整性{a['comp_mean']:.2f} "
          f"证据性{(a['evid_mean'] if a['evid_mean'] is not None else -1):.2f} "
          f"违约{a['viol_rate']:.2f} 时延{a['lat_mean']:.0f}s(范围{a['lat_range'][0]:.0f}-{a['lat_range'][1]:.0f}) "
          f"均成本¥{a['cost_mean']:.5f}")

print("\n=== 四、逐任务明细 ===")
by3=defaultdict(list)
for r in rs: by3[r["task"]].append(r)
for t,rows in sorted(by3.items()):
    a=agg(rows)
    print(f"  {t:8s} n={a['n']:2d} 解析{a['parse_rate']:.2f} 完整性{a['comp_mean']:.2f} 证据性{(a['evid_mean'] if a['evid_mean'] is not None else -1):.2f} 时延{a['lat_mean']:.0f}s")

print("\n=== 五、重复格一致性(n=2) ===")
rep=defaultdict(list)
for r in rs:
    if r["repeat"]: rep[(r["task"],r["kind"],r["model"])].append(r)
for k,rows in rep.items():
    if len(rows)==2:
        c=[r["contract"].get("completeness",0) for r in rows]
        e=[r["contract"].get("evidence",0) or 0 for r in rows]
        print(f"  {k[0]}/{k[1]}/{k[2][:8]}: 完整性{c} 证据性{e} 时延[{rows[0]['latency']:.0f},{rows[1]['latency']:.0f}]")

print("\n=== 六、统计口径声明 ===")
print("  n=1格仅给点估计; 跨任务极值称'观测范围'不称置信区间; 统计单元=任务(12), 非56次调用")
