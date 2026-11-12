#!/usr/bin/env python3
"""Profiling V3: 补测 GLM-5.3 与 Qwen3.7-Max 各28格(共56格)
GO: 2026-11-12; 预算上限: 本次¥1.60(累计不超¥3.00)
"""
import json, os, sys, re, time, importlib.util

BASE = "/root/research_outputs/RQ_DYN_V6_DESIGN"
OUT = f"{BASE}/profiling_runs"
os.makedirs(OUT, exist_ok=True)
spec = importlib.util.spec_from_file_location("pr", f"{BASE}/profiling_run.py")
pr = importlib.util.module_from_spec(spec); spec.loader.exec_module(pr)

NEW_MODELS = ["glm-5.3", "qwen3.7-max"]
CAP = 1.86   # 本次上限(累计不超¥3.00)

def build_plan():
    plan = []
    for model in ["qwen3.7-max", "glm-5.3"]:
        for t, cfg in pr.TASKS.items():
            for k in cfg["kinds"]:
                plan.append(dict(task=t, tier=cfg["tier"], kind=k, model=model, repeat=False))
        for t, k in pr.REPEAT_CELLS:
            plan.append(dict(task=t, tier=pr.TASKS[t]["tier"], kind=k, model=model, repeat=True))
    return plan

def main():
    plan = build_plan()
    assert len(plan) == 56, f"plan={len(plan)}"
    reuse = {}
    rp = f"{OUT}/V3_RESULTS.json"
    if os.path.exists(rp):
        prev = json.load(open(rp))
        for r in prev.get("results", []):
            if r.get("contract", {}).get("json_parsed"):
                reuse[(r["task"], r["kind"], r["model"], r["repeat"])] = r
        print(f"续跑: 复用已完成成功格 {len(reuse)} 个 (上次花费¥{prev.get('spent',0)})")
    results = []
    spent = 0.0
    t0 = time.time()
    for i, e in enumerate(plan):
        if spent >= CAP:
            print(f"⛔ 本次预算熔断 ¥{spent:.4f}>={CAP}"); break
        key = (e["task"], e["kind"], e["model"], e["repeat"])
        if key in reuse:
            results.append(reuse[key]); continue
        doc = pr.TASKS[e["task"]]["doc"]()
        if not doc:
            print(f"⚠ {e['task']} 无文档"); continue
        doc = re.sub(r'\s+', ' ', doc)[:9000]
        user = pr.PROMPTS[e["kind"]] + "\n\n【文书】\n" + doc
        mt = 65536 if e["model"] == "glm-5.3" else None
        r = pr.call(e["model"], pr.SYS, user, max_tokens=mt)
        cost = r["tin"]*1e-6 + r["tout"]*2e-6
        spent += cost
        sc = pr.score_node(r["text"], doc, e["kind"]) if not r["error"] else {"json_parsed": False}
        rec = dict(idx=i+1, task=e["task"], tier=e["tier"], kind=e["kind"], model=e["model"],
                   repeat=e["repeat"], tin=r["tin"], tout=r["tout"], latency=r["latency"],
                   cost_yuan=round(cost, 6), error=r["error"], contract=sc,
                   config_phase=("p3_glm53_maxtok65536" if e["model"]=="glm-5.3" else "p3_qwen37max"),
                   from_cache=False, experiment="V3",
                   raw_input=user[:9000], raw_output=r["text"][:12000])
        results.append(rec)
        print(f"[{i+1}/56] {e['task']:6s} {e['tier']} {e['kind']:12s} {e['model']:12s} "
              f"parse={'✓' if sc.get('json_parsed') else '✗'} comp={sc.get('completeness',0):.2f} "
              f"evid={sc.get('evidence',0) if sc.get('evidence') is not None else -1:.2f} "
              f"lat={r['latency']:.0f}s ¥{cost:.5f} 累计¥{spent:.4f}", flush=True)
        json.dump(dict(experiment="V3", plan_n=56, done=len(results), spent=round(spent,4),
                       results=results),
                  open(f"{OUT}/V3_RESULTS.json","w"), ensure_ascii=False, indent=1)
    out = dict(experiment="V3", plan_n=56, done=len(results), spent=round(spent,4),
               elapsed_min=round((time.time()-t0)/60,1),
               models=NEW_MODELS, results=results)
    json.dump(out, open(f"{OUT}/V3_RESULTS.json","w"), ensure_ascii=False, indent=1)
    print(f"\nV3完成: {len(results)}/56 | 花费¥{spent:.4f} | {(time.time()-t0)/60:.0f}分钟")

if __name__ == "__main__":
    main()
