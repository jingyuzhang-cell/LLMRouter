#!/usr/bin/env python3
"""π专项冒烟实验: 验证真实模型重分配收益(设计V0,2026-11-11)
问题: 恢复调用切换到能力匹配的异构模型,能否改善Q/C/L?
设计: 8次执行 = 2任务(MX2_STSHUN/MX3_ZD) × 2场景(S3/S4) × 2臂
  臂A PD-base : 恢复调用沿用原节点模型(MX原行为,π静态)
  臂B PD-pi   : 恢复调用按规则切换(S4→deepseek-chat轻量修复; S3→切换备用模型)
注入: 配对共享(同节点同场景,种子规则同v6执行器) — 两臂同异常条件
预算: 上限¥0.15(MX均值口径8次≈¥0.15)
真实调用须驾驶舱GO; 本脚本 dryrun 模式零API。
"""
import sys, json, time, hashlib, random, importlib.util
sys.path.insert(0, "/root/research_outputs/RQ_DYN_V6_DESIGN")
spec = importlib.util.spec_from_file_location("v6ex", "/root/research_outputs/RQ_DYN_V6_DESIGN/v6_executor.py")
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)

def alt_model(model, scenario):
    """π切换规则V0: S4格式修复→低时延模型; S3内容重建→异构备用"""
    if scenario == "S4":
        return "deepseek-chat" if model != "deepseek-chat" else "glm-5.3-flash"
    else:  # S3 重任务: 备用强模型
        return "glm-5.3-flash" if model != "glm-5.3-flash" else "deepseek-chat"

def execute_with_pi(task_pkg, arm, scenario, pair_id, deadline_s=300, exec_tag="PI"):
    """与v6.execute_task同构; 恢复调用的模型由臂规则决定并留痕"""
    t0 = time.monotonic()
    dag = task_pkg["dag"]["nodes"]; slots = task_pkg["slots"]
    doc_texts = {dn: open(di["path"], encoding="utf-8", errors="ignore").read()[:4000]
                 for dn, di in task_pkg.get("docs", {}).items() if __import__("os").path.exists(di["path"])}
    upstream = {}; node_outputs = {}; node_log = []; decision_log = []
    tin = tout = calls = 0; cost = 0.0
    _seed_material = f"{task_pkg.get('task_id')}|{pair_id}|{scenario}"
    _seed = int(hashlib.sha256(_seed_material.encode()).hexdigest()[:8], 16)
    up_refs = set()
    for nd in dag: up_refs.update(nd.get("upstream") or [])
    elig = sorted(nd["node"] for nd in dag if (nd.get("upstream") and nd["node"] in up_refs))
    inject_node = elig[random.Random(_seed).randrange(len(elig))]

    for node in dag:
        if time.monotonic() - t0 > deadline_s: break
        nn = node["node"]; kind = node.get("kind", "extract")
        rtxt = "\n".join(doc_texts.get(d, "") for d in node.get("docs", []))
        upn = {k: v for k, v in upstream.items() if k in (node.get("upstream") or [])}
        system, user = v6.build_node_prompt(node, rtxt, upn)
        model = "glm-5.3-flash" if kind in ("verification","report","reason","timeline") else "deepseek-chat"
        r = v6.call_model(model, system, user, timeout=min(120, deadline_s-(time.monotonic()-t0)))
        calls += 1; tin += r.get("in",0); tout += r.get("out",0)
        cost += r.get("in",0)*1e-6 + r.get("out",0)*2e-6
        output = r.get("text","")
        anomaly_hit = (nn == inject_node)
        if anomaly_hit:
            corrupted = v6.inject_anomaly(output, scenario, kind)
            # π决策: 臂A沿用原模型; 臂B按规则切换
            rec_model = model if arm == "PD-base" else alt_model(model, scenario)
            rec = v6.pd_recovery(corrupted, (system, user), rec_model, scenario)
            calls += 1; tin += rec.get("in",0); tout += rec.get("out",0)
            cost += rec.get("in",0)*1e-6 + rec.get("out",0)*2e-6
            output = rec.get("text", corrupted)
            decision_log.append({"node_id": nn, "arm": arm, "scenario": scenario,
                "original_model": model, "recovery_model": rec_model,
                "pi_changed": rec_model != model,
                "Z": "repair_format" if scenario=="S4" else "reExecute_node",
                "rec_latency": round(rec.get("latency",0),2), "rec_out_tokens": rec.get("out",0),
                "recovered_text": output[:2000]})
        node_outputs[nn] = output; upstream[nn] = output
        node_log.append({"node_id": nn, "model": model, "status": "recovered" if anomaly_hit else "ok",
                         "latency": round(r.get("latency",0),2)})
    all_out = " ".join(str(v) for v in node_outputs.values())
    tp = v6.score_tp(all_out, slots)
    mk = time.monotonic() - t0
    return {"arm": arm, "scenario": scenario, "pair": pair_id,
            "task": task_pkg["task_id"], "tp": tp, "n_slots": len(slots),
            "tp_ratio": tp/len(slots), "makespan_s": round(mk,1), "calls": calls,
            "tokens": {"in": tin, "out": tout}, "cost_yuan": round(cost,4),
            "on_time": mk <= deadline_s, "inject_node": inject_node,
            "decision_log": decision_log, "final_outputs": node_outputs}

def build_plan():
    plan = []
    for task in ["MX2_STSHUN", "MX3_ZD"]:
        for pair, sc in [(1,"S3"),(3,"S4")]:
            for arm in ["PD-base", "PD-pi"]:
                plan.append({"task": task, "pair": pair, "scenario": sc, "arm": arm})
    return plan  # 8条

def main(mode):
    if mode == "dryrun": v6.set_dry_run(True)
    plan = build_plan(); assert len(plan) == 8
    pkgs = {t: json.load(open(f"/root/research_outputs/RQ_DYN_V6_DESIGN/mech_experiment/{t}.json"))
            for t in ["MX2_STSHUN","MX3_ZD"]}
    runs = []; spent = 0.0; CAP = 0.15
    for i, e in enumerate(plan):
        if spent > CAP:
            print(f"⛔ π冒烟预算熔断 ¥{spent:.4f}>¥{CAP}"); break
        r = execute_with_pi(pkgs[e["task"]], e["arm"], e["scenario"], e["pair"])
        runs.append(r); spent += r["cost_yuan"]
        dl = r["decision_log"][0] if r["decision_log"] else {}
        print(f"[{i+1}/8] {e['task']} {e['scenario']} p{e['pair']} {e['arm']:8s} "
              f"TP={r['tp']}/{r['n_slots']} inj={r['inject_node']} "
              f"π:{dl.get('original_model','-')}→{dl.get('recovery_model','-')} "
              f"{'[切换]' if dl.get('pi_changed') else '[沿用]'} rec_lat={dl.get('rec_latency','-')}s "
              f"cost=¥{r['cost_yuan']:.4f}", flush=True)
    # 配对分析
    print(f"\n实际花费: ¥{spent:.4f} (上限¥0.15)")
    pairs = {}
    for r in runs: pairs.setdefault((r["task"], r["scenario"], r["pair"]), {})[r["arm"]] = r
    print(f"\n{'任务':11s} {'场景':3s} {'注入':4s} {'base_TP':7s} {'pi_TP':6s} {'ΔTP':4s} {'Δrec_lat(s)':11s} {'Δcost':8s}")
    for (t,sc,p),pp in sorted(pairs.items()):
        b, pi_ = pp.get("PD-base"), pp.get("PD-pi")
        if not b or not pi_: continue
        dtp = pi_["tp"]-b["tp"]
        rb, rp = b["decision_log"][0], pi_["decision_log"][0]
        dlat = rp["rec_latency"]-rb["rec_latency"]
        dc = pi_["cost_yuan"]-b["cost_yuan"]
        print(f"{t:11s} {sc:3s} {b['inject_node']:4s} {b['tp']:7d} {pi_['tp']:6d} {dtp:+4d} {dlat:+11.2f} {dc:+8.4f}")
    out = "/root/research_outputs/RQ_DYN_V6_DESIGN/mech_experiment/" + ("pi_dryrun.json" if mode=="dryrun" else "pi_smoke_result.json")
    json.dump({"runs": runs, "spent": spent}, open(out,"w"), ensure_ascii=False, indent=1)
    print(f"\n→ {out}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dryrun")
