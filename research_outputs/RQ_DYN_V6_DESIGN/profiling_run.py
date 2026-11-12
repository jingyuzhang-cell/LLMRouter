#!/usr/bin/env python3
"""Profiling V1 执行器: 56次真实调用(窗口GO 2026-11-11)
12任务 × 2节点类型 × 2模型 = 48; +4个L3/L4组合×2模型重复 = 8; 总56
预算硬上限 ¥3.00; 熔断即停不补跑
"""
import json, os, sys, time, hashlib, re, glob, urllib.request

BASE = "/root/research_outputs/RQ_DYN_V6_DESIGN"
OUT = f"{BASE}/profiling_runs"
os.makedirs(OUT, exist_ok=True)
V5 = "/root/research_outputs/RQ_DYN_V5_DESIGN_20261107"
RAW = "/root/research_outputs/V6_CANDIDATE_RAW"
sys.path.insert(0, BASE)
from extract_decision import extract

# ---------- 密钥 ----------
def glm_key():
    cfg = json.load(open("/root/.zcode/v2/provider_config.json"))
    for r in cfg["config"]["providerConfigRules"]["providerRules"]:
        if r.get("providerId") == "bigmodel-api-6":
            return r["config"]["access"]["apiKey"]
def ds_key():
    for line in open("/root/.env"):
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.strip().split("=", 1)[1]
GLM_KEY, DS_KEY = glm_key(), ds_key()
GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DS_URL = "https://api.deepseek.com/chat/completions"
QWEN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
def qwen_key():
    for line in open("/root/.env"):
        if line.startswith("QWEN_API_KEY="):
            return line.strip().split("=",1)[1]
QWEN_KEY = qwen_key()

def call(model, system, user, max_tokens=None, timeout=600):
    if model.startswith("glm"):
        url, key = GLM_URL, GLM_KEY
    elif model.startswith("qwen"):
        url, key = QWEN_URL, QWEN_KEY
    else:
        url, key = DS_URL, DS_KEY
    if max_tokens is None:
        max_tokens = 32768 if model.startswith("glm") else 8192
    body = {"model": model, "messages": [{"role":"system","content":system},
            {"role":"user","content":user}], "max_tokens": max_tokens, "temperature": 0}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {key}"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
        if "choices" in d:
            txt = d["choices"][0]["message"].get("content","") or ""
        else:
            txt = "".join(b.get("text","") for b in d.get("content",[]) if b.get("type")=="text")
        u = d.get("usage", {})
        return dict(text=txt, tin=u.get("prompt_tokens",0), tout=u.get("completion_tokens",0),
                    latency=round(time.monotonic()-t0,2), model=model, error=None,
                    raw_response=d)
    except Exception as e:
        return dict(text="", tin=0, tout=0, latency=round(time.monotonic()-t0,2),
                    model=model, error=str(e), raw_response=None)

# ---------- 节点提示词与输出合同 ----------
SYS = "你是严谨的金融信息处理智能体。只输出一个JSON对象，不得编造文书未记载的事实。"
PROMPTS = {
 "extract": (
   "从以下监管文书中抽取关键事实。输出JSON：\n"
   '{"facts":[{"fact":"事实命题","value":"数值或结论","source":"原文片段"}],'
   '"entities":["涉及主体"],"unknown":["文中未明确的事项"]}\n'
   "要求：facts不少于5条；source必须是文书原文的连续片段；不得补充文书中没有的信息。"),
 "reason": (
   "基于以下监管文书进行推理分析。输出JSON：\n"
   '{"reasoning":[{"step":"推理步骤","premise":"依据的原文","conclusion":"结论"}],'
   '"computations":[{"expression":"算式","result":"结果","unit":"单位"}],'
   '"relations":[{"from":"主体A","relation":"关系","to":"主体B"}],'
   '"unknown":["无法从文中确定的事项"]}\n'
   "要求：每个推理步骤必须给出文中依据；计算须写出算式与结果。"),
 "verification": (
   "核验以下监管文书内部事实的一致性与矛盾。输出JSON：\n"
   '{"verified":[{"fact":"被核验事实","status":"consistent|conflict|unverifiable",'
   '"evidence":"原文依据"}],"conflicts":[{"item_a":"事实A","item_b":"事实B","nature":"矛盾性质"}],'
   '"unknown":["证据不足无法判定的事项"]}\n'
   "要求：每条判定必须附原文依据；证据不足必须标unverifiable，不得猜测。"),
 "report": (
   "综合以下监管文书生成结构化结论。输出JSON：\n"
   '{"conclusions":[{"conclusion":"结论","evidence":"原文依据","confidence":"high|medium|low"}],'
   '"key_numbers":[{"item":"项目","value":"数值","period":"期间"}],'
   '"unknown":["文书未支持的结论"]}\n'
   "要求：每条结论须有原文依据；不得出现无依据断言。"),
}

# ---------- 任务定义(12任务×2节点类型) ----------
def v5_doc(task):
    """V5任务: 从Gold包docs字段取主文档"""
    names = {"E07C":"e07c","LS":"ls","CS":"cs","E04":"e04","KM":"km","MD":"md"}
    d = names[task]
    gp = glob.glob(f"{V5}/{d}/V5_GOLD_*.json")
    if not gp: return None
    pkg = json.load(open(gp[0]))
    texts = []
    for dn, di in (pkg.get("docs") or {}).items():
        p = di.get("path","")
        if p and os.path.exists(p):
            try: texts.append(open(p, encoding="utf-8", errors="ignore").read())
            except: pass
    if not texts:
        # 回退: 从slots+facts构造
        texts = [json.dumps(pkg.get("facts", pkg.get("slots", [])), ensure_ascii=False)]
    return "\n".join(texts)

STAGE_D = "/root/research_outputs/static_pi/stage_d/independent_case_search/raw"
def new_doc(code, fname):
    for pat in [f"{STAGE_D}/{code}_decision_{fname}.pdf.txt",
                f"{RAW}/**/{code}_decision_{fname}.pdf.txt"]:
        p = glob.glob(pat, recursive=True)
        if p: return open(p[0], encoding="utf-8", errors="ignore").read()
    return None

TASKS = {
 "E07C":   dict(tier="L1", kinds=["extract","report"],       doc=lambda: v5_doc("E07C")),
 "LS":     dict(tier="L1", kinds=["extract","verification"], doc=lambda: v5_doc("LS")),
 "CS":     dict(tier="L1", kinds=["extract","reason"],       doc=lambda: v5_doc("CS")),
 "E04":    dict(tier="L2", kinds=["reason","verification"],  doc=lambda: v5_doc("E04")),
 "KM":     dict(tier="L2", kinds=["reason","report"],        doc=lambda: v5_doc("KM")),
 "MD":     dict(tier="L2", kinds=["verification","report"],  doc=lambda: v5_doc("MD")),
 "中昌数据": dict(tier="L3", kinds=["extract","reason"],       doc=lambda: new_doc("600242","1622563200000")),
 "中捷资源": dict(tier="L3", kinds=["reason","verification"],  doc=lambda: new_doc("002021","1612454400000")),
 "大智慧":   dict(tier="L3", kinds=["verification","report"],  doc=lambda: new_doc("601519","1469548800000")),
 "天成控股": dict(tier="L3", kinds=["extract","report"],       doc=lambda: new_doc("600112","1543420800000")),
 "ST仰帆":  dict(tier="L4", kinds=["extract","verification"], doc=lambda: new_doc("600421","1544457600000")),
 "银亿股份": dict(tier="L4", kinds=["reason","report"],        doc=lambda: new_doc("900981","0") or new_doc("000981","1579104000000")),
}
MODELS = ["glm-5.3-flash", "deepseek-chat"]
REPEAT_CELLS = [("中昌数据","extract"), ("大智慧","verification"), ("ST仰帆","extract"), ("银亿股份","report")]

def build_plan():
    plan = []
    for t, cfg in TASKS.items():
        for k in cfg["kinds"]:
            for m in MODELS:
                plan.append(dict(task=t, tier=cfg["tier"], kind=k, model=m, repeat=False))
    for t, k in REPEAT_CELLS:
        for m in MODELS:
            plan.append(dict(task=t, tier=TASKS[t]["tier"], kind=k, model=m, repeat=True))
    return plan

# ---------- 评分(五维) ----------
LEAK_NUM = re.compile(r'\d[\d,\.]{3,}')
def score_node(out_text, doc_text, kind):
    """五维评分(可程序化部分)"""
    res = {"json_parsed": False, "completeness": 0.0, "evidence": 0.0,
           "boundary": None, "correctness": None, "contract_violation": False,
           "parse_error": None}
    try:
        d = json.loads(out_text)
        res["json_parsed"] = True
    except Exception as e:
        m = re.search(r'\{.*\}', out_text, re.S)
        if m:
            try:
                d = json.loads(m.group(0)); res["json_parsed"] = True
            except Exception as e2:
                res["parse_error"] = str(e2); return res
        else:
            res["parse_error"] = str(e); return res
    # 完整性: 必需字段
    need = {"extract": ["facts","entities"],
            "reason": ["reasoning","computations"],
            "verification": ["verified"],
            "report": ["conclusions","key_numbers"]}[kind]
    present = sum(1 for k in need if k in d and d[k])
    res["completeness"] = present/len(need)
    # 合同违约: 缺必需字段或facts<5
    if kind == "extract" and len(d.get("facts",[])) < 5:
        res["contract_violation"] = True
    if res["completeness"] < 1.0:
        res["contract_violation"] = True
    # 证据性: 输出中引用的source片段是否在原文中逐字存在
    norm = lambda s: re.sub(r'[\s,，()（）]','',str(s))
    dn = norm(doc_text)
    quotes = []
    for key in ("facts","reasoning","verified","conclusions","conflicts"):
        for it in d.get(key,[]) or []:
            if isinstance(it, dict):
                for f in ("source","evidence","premise"):
                    if it.get(f): quotes.append(str(it[f]))
    if quotes:
        hit = sum(1 for q in quotes if norm(q)[:40] and norm(q)[:40] in dn)
        res["evidence"] = round(hit/len(quotes), 3)
    # 边界遵循: unknown字段是否给出(不编造)
    res["boundary"] = bool(d.get("unknown") is not None)
    return res

def main():
    plan = build_plan()
    assert len(plan) == 56, f"plan={len(plan)}"
    # 复用已成功格
    reuse = {}
    rp = f"{OUT}/reused_cells.json"
    if os.path.exists(rp):
        for r in json.load(open(rp)):
            reuse[(r["task"], r["kind"], r["model"], r["repeat"])] = r
        print(f"复用已成功格: {len(reuse)}")
    cap = 3.00
    spent = 0.0
    results = []
    t_start = time.time()
    for i, e in enumerate(plan):
        if spent >= cap:
            print(f"⛔ 预算熔断 ¥{spent:.4f}>={cap}"); break
        key = (e["task"], e["kind"], e["model"], e["repeat"])
        if key in reuse:
            results.append(reuse[key]); print(f"[{i+1}/56] {e['task']} {e['kind']} {e['model'][:8]} 复用", flush=True); continue
        doc = TASKS[e["task"]]["doc"]()
        if not doc:
            print(f"⚠ {e['task']} 无文档,跳过"); continue
        doc = re.sub(r'\s+',' ', doc)[:9000]
        user = PROMPTS[e["kind"]] + "\n\n【文书】\n" + doc
        r = call(e["model"], SYS, user)
        cost = r["tin"]*1e-6 + r["tout"]*2e-6
        spent += cost
        sc = score_node(r["text"], doc, e["kind"]) if not r["error"] else {"json_parsed":False}
        rec = dict(idx=i+1, task=e["task"], tier=TASKS[e["task"]]["tier"], kind=e["kind"],
                   model=e["model"], repeat=e["repeat"],
                   tin=r["tin"], tout=r["tout"], latency=r["latency"],
                   cost_yuan=round(cost,6), error=r["error"],
                   contract=sc,
                   raw_input=user[:9000], raw_output=r["text"][:12000])
        results.append(rec)
        print(f"[{i+1}/56] {e['task']:6s} {e['tier']} {e['kind']:12s} {e['model'][:10]:10s} "
              f"parse={'✓' if sc.get('json_parsed') else '✗'} "
              f"comp={sc.get('completeness',0):.2f} evid={sc.get('evidence',0):.2f} "
              f"lat={r['latency']:.0f}s ¥{cost:.5f} 累计¥{spent:.4f}", flush=True)
        if i % 4 == 3:
            json.dump(dict(plan_n=56, done=len(results), spent=round(spent,4), results=results),
                      open(f"{OUT}/profiling_results_partial.json","w"), ensure_ascii=False, indent=1)
    out = dict(plan_n=56, done=len(results), spent=round(spent,4),
               elapsed_min=round((time.time()-t_start)/60,1),
               frozen_plan=dict(models=MODELS, repeat_cells=REPEAT_CELLS,
                                task_kinds={t:c["kinds"] for t,c in TASKS.items()}),
               results=results)
    json.dump(out, open(f"{OUT}/PROFILING_RESULTS.json","w"), ensure_ascii=False, indent=1)
    print(f"\n完成: {len(results)}/56次 | 花费¥{spent:.4f} | 用时{(time.time()-t_start)/60:.0f}分钟")

if __name__ == "__main__":
    main()
