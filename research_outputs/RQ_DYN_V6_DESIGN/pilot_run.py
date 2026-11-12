#!/usr/bin/env python3
"""Pilot A/B/C 三臂静态分配实验: 4任务×3臂=12次DAG执行, 66次API请求硬上限
窗口裁决 2026-11-12: 无异常注入, 300s/DAG, 三臂顺序随机(seed=20261112)
硬约束: 66次API请求(含失败与重试)触顶即停, 失败记录为未完成, 不追加
"""
import json, os, sys, re, time, random, hashlib, importlib.util

BASE = "/root/research_outputs/RQ_DYN_V6_DESIGN"
V5 = "/root/research_outputs/RQ_DYN_V5_DESIGN_20261107"
OUT = f"{BASE}/pilot_runs"
os.makedirs(OUT, exist_ok=True)

spec = importlib.util.spec_from_file_location("pr", f"{BASE}/profiling_run.py")
pr = importlib.util.module_from_spec(spec); spec.loader.exec_module(pr)
CALL = pr.call
SYS = pr.SYS
score_tp = None
# 复用V5评分函数
v5spec = importlib.util.spec_from_file_location("v5", f"{V5}/v5_executor.py")
try:
    v5 = importlib.util.module_from_spec(v5spec); v5spec.loader.exec_module(v5)
    score_tp = v5.score_tp
except Exception as e:
    print("V5评分函数载入失败:", e)

TASKS = {"E06-HUANRUI": "e06_huanrui", "E08-ZHONGTIE": "e08_zhongtie", "ZJ": "zj", "ZED": "zed"}
ARMS = {
 "A_V5MIXED": dict(extract="deepseek-chat", reason="glm-5.3-flash", report="glm-5.3-flash"),
 "B_DSALL":   dict(extract="deepseek-chat", reason="deepseek-chat",  report="deepseek-chat"),
 "C_HETERO":  dict(extract="qwen3.7-max",   reason="deepseek-chat",  report="deepseek-chat"),
}
CALL_CAP = 66
DEADLINE = 300
SEED = 20261112
DRY = False
_calls = {"n": 0, "cost": 0.0}

def load_task(name):
    d = TASKS[name]
    p = glob_v5 = None
    import glob
    files = glob.glob(f"{V5}/{d}/V5_GOLD_*.json")
    pkg = json.load(open(files[0]))
    docs = {}
    for dn, di in (pkg.get("docs") or {}).items():
        pth = di.get("path", "")
        if os.path.exists(pth):
            docs[dn] = open(pth, encoding="utf-8", errors="ignore").read()[:6000]
    return pkg, docs

def node_prompt(nd, docs, upstream):
    """按节点kind构建提示词; timeline归reason子类型"""
    kind = nd.get("kind", "extract")
    role = nd.get("role", "")
    doc_names = nd.get("docs") or []
    text = "\n".join(docs.get(dn, "") for dn in doc_names)
    if kind == "extract":
        u = (f"请从以下文书抽取与「{role}」相关的事实。输出JSON："
             '{"facts":[{"fact":"...","value":"...","source":"原文片段"}]}\n\n文书：\n' + text)
    elif kind in ("reason", "timeline"):
        sub = "（时序推理）" if kind == "timeline" else ""
        u = (f"请基于上游结果完成「{role}」{sub}。输出JSON："
             '{"reasoning":[{"step":"...","premise":"...","conclusion":"..."}],'
             '"unknown":["..."]}\n\n上游：\n' + json.dumps(upstream, ensure_ascii=False)[:5000])
    else:  # report
        u = (f"请综合上游结果生成终端结论（{role}）。输出JSON："
             '{"conclusions":[{"conclusion":"...","evidence":"..."}]}\n\n上游：\n'
             + json.dumps(upstream, ensure_ascii=False)[:5000])
    return u

def run_dag(task, arm, deadline=DEADLINE):
    pkg, docs = load_task(task)
    t0 = time.monotonic()
    alloc = ARMS[arm]
    upstream, node_out, node_log = {}, {}, []
    aborted = None
    for nd in pkg["dag"]["nodes"]:
        if _calls["n"] >= CALL_CAP:
            aborted = "call_cap"; break
        if time.monotonic() - t0 > deadline:
            aborted = "deadline"; break
        kind = nd.get("kind", "extract")
        model = alloc.get(kind) or alloc.get("report")
        up = {k: v for k, v in upstream.items() if k in (nd.get("upstream") or [])}
        u = node_prompt(nd, docs, up)
        remain = max(20, deadline - (time.monotonic() - t0))
        r = CALL(model, SYS, u, timeout=min(remain, 600))
        _calls["n"] += 1
        cost = r["tin"]*1e-6 + r["tout"]*2e-6
        _calls["cost"] += cost
        ok = bool(r["text"]) and not r["error"]
        try:
            json.loads(re.search(r'\{.*\}', r["text"], re.S).group(0)) if r["text"] else None
            parsed = bool(r["text"])
        except Exception:
            parsed = False
        node_out[nd["node"]] = r["text"]
        upstream[nd["node"]] = r["text"]
        node_log.append(dict(node=nd["node"], kind=kind, model=model,
            tin=r["tin"], tout=r["tout"], latency=r["latency"],
            cost=round(cost,6), parsed=parsed, error=r["error"],
            raw_output=r["text"][:8000]))
    elapsed = round(time.monotonic()-t0, 1)
    terminal = node_out.get(pkg["dag"]["nodes"][-1]["node"], "")
    all_out = " ".join(str(v) for v in node_out.values())
    tp = score_tp(all_out, pkg.get("slots", [])) if score_tp else -1
    n_slots = len(pkg.get("slots", []))
    return dict(task=task, arm=arm, alloc=alloc,
                nodes_done=len(node_log), nodes_total=len(pkg["dag"]["nodes"]),
                aborted=aborted, on_time=(elapsed <= deadline and aborted != "deadline"),
                makespan_s=elapsed, tp=tp, n_slots=n_slots,
                tp_ratio=round(tp/n_slots,3) if n_slots>0 and tp>=0 else None,
                calls=len(node_log),
                tokens=dict(tin=sum(x["tin"] for x in node_log), tout=sum(x["tout"] for x in node_log)),
                cost_yuan=round(sum(x["cost"] for x in node_log),5),
                terminal_output=terminal[:4000], node_log=node_log)

def build_plan():
    plan = []
    for t in TASKS:
        for a in ARMS:
            plan.append(dict(task=t, arm=a))
    rng = random.Random(SEED)
    # 每任务内三臂顺序随机
    out = []
    for t in TASKS:
        arms = [a for a in ARMS]
        rng.shuffle(arms)
        for a in arms:
            out.append(dict(task=t, arm=a))
    return out

def main(mode="run"):
    global DRY
    if mode == "dryrun":
        DRY = True
        def _mock(model, system, user, max_tokens=None, timeout=600):
            h = hashlib.md5((model+user[:80]).encode()).hexdigest()[:6]
            return dict(text='{"facts":[{"fact":"mock-'+h+'","value":"x","source":"mock"}]}',
                        tin=500, tout=200, latency=0.01, model=model, error=None)
        globals()["CALL"] = _mock
    plan = build_plan()
    print(f"计划: {len(plan)}次DAG执行")
    for e in plan: print(f"  {e['task']:14s} {e['arm']}")
    results = []
    t0 = time.time()
    for i, e in enumerate(plan):
        if _calls["n"] >= CALL_CAP:
            print(f"⛔ 调用上限 {CALL_CAP} 触顶, 停止"); break
        print(f"\n[{i+1}/{len(plan)}] {e['task']} {e['arm']} ...", flush=True)
        r = run_dag(e["task"], e["arm"])
        results.append(r)
        print(f"  完成{r['nodes_done']}/{r['nodes_total']}节点 终止={r['aborted']} "
              f"on_time={r['on_time']} TP={r['tp']}/{r['n_slots']} "
              f"耗时{r['makespan_s']}s 调用{r['calls']} ¥{r['cost_yuan']} "
              f"| 累计调用{_calls['n']}/66 ¥{_calls['cost']:.4f}", flush=True)
        json.dump(dict(mode=mode, done=len(results), plan_n=len(plan),
                       calls=_calls["n"], cost=round(_calls["cost"],4), results=results),
                  open(f"{OUT}/pilot_{mode}_partial.json","w"), ensure_ascii=False, indent=1)
    out = dict(mode=mode, plan_n=len(plan), done=len(results),
               calls=_calls["n"], cost_yuan=round(_calls["cost"],4),
               elapsed_min=round((time.time()-t0)/60,1),
               call_cap=CALL_CAP, deadline_s=DEADLINE, seed=SEED,
               arms=ARMS, results=results)
    fn = "PILOT_RESULTS.json" if mode=="run" else "PILOT_DRYRUN.json"
    json.dump(out, open(f"{OUT}/{fn}","w"), ensure_ascii=False, indent=1)
    print(f"\n{'dry-run' if mode=='dryrun' else 'Pilot'}完成: {len(results)}次DAG, "
          f"{_calls['n']}次调用, ¥{_calls['cost']:.4f}, {(time.time()-t0)/60:.0f}分钟")
    print(json.dumps(dict(calls=_calls["n"], cost=round(_calls["cost"],4)), ensure_ascii=False))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv)>1 else "run")
