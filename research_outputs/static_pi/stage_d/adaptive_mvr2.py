#!/usr/bin/env python3
"""Adaptive 独立任务复现（MVR2 元道；~24 调用；2026-11-04）。

任务: MVR2 元道处罚关联（27 槽，多主体×多阶段矩阵）
臂: Static / Proposed / Adaptive（阈值 P90=140s 不变）
截止: 120s / 250s（两端）
rep: 2/截止
总计: 2×(E共享3 + 3臂×3节点) = ~24 调用

GO 门：ADAPTIVE_REPL_GO=1
"""
import json, os, sys, time, random, re
import urllib.request
from pathlib import Path

STAGE_D = Path("/root/research_outputs/static_pi/stage_d")
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, "/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, "/root/capital_opinion_pilot")
import transport
from executor import extract_json

OUT = STAGE_D / "adaptive_mvr2_runs"
GOLD = "/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR2_yuandao/TASK_CONTRACT_MVR2_v1.json"
GLM_URL = "https://open.bigmodel.cn/api/anthropic/v1/messages"
ADAPTIVE_THRESHOLD = 140
DEADLINES = [120, 250]
ARMS = ["Static", "Proposed", "Adaptive"]
REPS = 2

M_Q = ("元道通信欺诈发行及信息披露违法案：事先告知书拟对各当事人处罚多少？行政处罚决定书最终对公司和李晋、"
       "燕某、曹亚蕾、吴志锋分别处罚多少？曹亚蕾拟罚与终罚差多少？对李晋、曹亚蕾的市场禁入分别几年（拟与终）？"
       "三份文书的文号分别是什么？立案公告、告知书、决定书、停牌各是何日期？2019-2022 各年虚增营业收入及"
       "四年合计是多少？IPO 募集资金总额多少？")
M_E = ("你是精确的监管文书抽取器。只输出一个 JSON 对象：{\"parties\": [{name, penalties: {欺诈发行罚款, "
       "信披违法罚款, 综合罚款, 拟处罚金额}, market_ban_years: {拟, 终}}], \"doc_number\": ..., "
       "\"dates\": {立案公告披露日, 文书收到日, 停牌日}, \"inflated_revenue\": {年度: 金额}, "
       "\"ipo_proceeds\": ...}, 每项含完整原句引用与页码。不得编造。")
M_J1 = ("你是跨文书处罚阶段衔接器。只输出 JSON：{\"party_stage_matrix\": [{party, proposed_penalty, "
        "final_penalty, difference, proposed_ban_years, final_ban_years, evidence:[{doc,page,quote}]}], "
        "\"date_chain\": {...}, \"doc_numbers\": {...}, \"cross_doc_notes\": [...]}。"
        "拟罚取自事先告知书(Db)，终罚取自决定书(Da)；差异=拟−终。仅依据给定材料。")
M_J2 = ("你是处罚矩阵核验器。只输出 JSON：{\"per_party\": [...], \"totals\": {...}, "
        "\"doc_numbers\": {...}, \"date_chain\": {...}}。四年合计=2019+2020+2021+2022。仅依据给定材料。")
M_SINK = ("你是严谨的最终答案汇总器。只输出一个 JSON 对象：{\"answers\": [...], \"unknown_slots\": []}。"
          "不得使用给定上游材料之外的任何信息。")


def glm_low(system, user, max_tokens=8192, timeout_s=300):
    key = os.environ.get("STAGE_D_GLM_KEY", "").strip()
    body = {"model": "GLM-5.3-Flash", "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}], "reasoning_effort": "low"}
    req = urllib.request.Request(GLM_URL, data=json.dumps(body, ensure_ascii=False).encode(), method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", key)
    req.add_header("authorization", "Bearer " + key)
    req.add_header("anthropic-version", "2023-06-01")
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    return {"text": "".join(b.get("text","") for b in d.get("content",[]) if b.get("type")=="text"),
            "in": d["usage"]["input_tokens"], "out": d["usage"]["output_tokens"],
            "stop": d.get("stop_reason"), "lat": round(time.monotonic()-t0, 2)}

def ds_call(system, user, max_tokens=4000, timeout_s=300):
    t0 = time.monotonic()
    r = transport.openai_call("deepseek", system, user, max_tokens, timeout_s, 0)
    r["lat"] = round(time.monotonic()-t0, 2)
    return r


def do_call(name, backend, system, user, cap=4000):
    r = glm_low(system, user, cap) if backend == "glm" else ds_call(system, user, cap)
    ok = r.get("stop") in ("end_turn","stop",None) and bool(r.get("text","").strip())
    print(f"  {name}({backend}): stop={r.get('stop')} in={r.get('in')} out={r.get('out')} "
          f"wall={r.get('lat')}s ok={ok}", flush=True)
    return r, ok


def resolve_adaptive(deadline_s):
    return "Static" if deadline_s < ADAPTIVE_THRESHOLD else "Proposed"


def run_arm(arm, deadline_s, rep, E_texts, slots_json):
    actual = arm
    if arm == "Adaptive":
        actual = resolve_adaptive(deadline_s)

    calls = []
    if actual == "Static":
        # Static: 直接 J1(GLM) → J2(DS) → SINK(DS)
        r1, ok1 = do_call("J1", "glm", M_J1,
                          f"任务问题：{M_Q}\n\nDa抽取：\n{E_texts.get('E_Da','')}\n\n"
                          f"Db抽取：\n{E_texts.get('E_Db','')}\n\nDc抽取：\n{E_texts.get('E_Dc','')}", 8192)
        calls.append({"node":"J1","ok":ok1,"lat":r1.get("lat")})
        if not ok1: return {"arm":arm,"actual":actual,"dl":deadline_s,"rep":rep,"status":"J1_FAIL","calls":calls}
        j1_out = r1["text"]
    else:
        # Proposed: J1(GLM) → 诊断守卫 → 如失败 J1(DS) → J2 → SINK
        r1, ok1 = do_call("J1", "glm", M_J1,
                          f"任务问题：{M_Q}\n\nDa抽取：\n{E_texts.get('E_Da','')}\n\n"
                          f"Db抽取：\n{E_texts.get('E_Db','')}\n\nDc抽取：\n{E_texts.get('E_Dc','')}", 8192)
        calls.append({"node":"J1","ok":ok1,"lat":r1.get("lat")})
        j1_out = r1["text"] if ok1 else ""
        parsed = extract_json(j1_out)
        if parsed is None:
            # 诊断触发 → 换模
            r1b, ok1b = do_call("J1_swap", "ds", M_J1,
                                f"任务问题：{M_Q}\n\nDa抽取：\n{E_texts.get('E_Da','')}\n\n"
                                f"Db抽取：\n{E_texts.get('E_Db','')}\n\nDc抽取：\n{E_texts.get('E_Dc','')}")
            calls.append({"node":"J1_swap","ok":ok1b,"lat":r1b.get("lat")})
            if ok1b: j1_out = r1b["text"]
            else: return {"arm":arm,"actual":actual,"dl":deadline_s,"rep":rep,"status":"J1_FAIL","calls":calls}

    # J2
    r2, ok2 = do_call("J2", "ds", M_J2,
                      f"任务问题：{M_Q}\n\nJ1 衔接结果：\n{j1_out[:3000]}")
    calls.append({"node":"J2","ok":ok2,"lat":r2.get("lat")})
    if not ok2: return {"arm":arm,"actual":actual,"dl":deadline_s,"rep":rep,"status":"J2_FAIL","calls":calls}

    # SINK
    r3, ok3 = do_call("SINK", "ds", M_SINK,
                      f"任务问题：{M_Q}\n\nJ2 结果：\n{r2['text'][:2000]}\n\n"
                      f"槽位：{slots_json}")
    calls.append({"node":"SINK","ok":ok3,"lat":r3.get("lat")})

    ps = extract_json(r3["text"]) if ok3 else None
    answers = (ps or {}).get("answers", [])
    wall = sum(c.get("lat",0) for c in calls)
    return {"arm":arm,"actual":actual,"dl":deadline_s,"rep":rep,
            "status":"COMPLETE" if ok3 else "SINK_FAIL","calls":calls,
            "answers":answers,"wall_s":round(wall,1)}


def norm_num(v):
    v = re.sub(r'[,，\s万元亿元]','',str(v))
    m = re.search(r'[\d.]+', v)
    try: return float(m.group()) if m else None
    except: return None


def score(answers, gold_facts):
    gold_map = {f['fact_id']: f for f in gold_facts}
    hits = 0
    for a in answers or []:
        if not isinstance(a, dict): continue
        fid = a.get('fact_id')
        if fid not in gold_map: continue
        gn = norm_num(gold_map[fid].get('value',''))
        an = norm_num(a.get('value',''))
        if gn is not None and an is not None and abs(gn-an)<0.01:
            hits += 1
    return {"hits": hits, "total": len(gold_facts), "rate": round(hits/len(gold_facts),4)}


def main():
    if os.environ.get("ADAPTIVE_REPL_GO") != "1":
        raise SystemExit("REFUSED: requires ADAPTIVE_REPL_GO=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("REFUSED: DEEPSEEK_API_KEY not set")
    OUT.mkdir(parents=True, exist_ok=True)

    gold = json.load(open(GOLD))
    facts = gold["required_facts"]
    src = gold.get("source_pages", {})
    slots_json = json.dumps([{"fact_id":f["fact_id"],"subject":f.get("subject",""),
                              "predicate":f.get("predicate","")} for f in facts], ensure_ascii=False)

    # 构建文书文本
    doc_texts = {}
    for doc_id, doc in src.items():
        doc_texts[doc_id] = "".join(p.get("text","") for p in doc.get("pages",{}).values())

    all_recs = []
    total_calls = 0

    for dl in DEADLINES:
        for rep in range(1, REPS+1):
            # 共享 E（每 dl×rep 一次）
            E_texts = {}
            for doc_id in ("Da","Db","Dc"):
                r, ok = do_call(f"E_{doc_id}", "ds", M_E,
                                f"任务问题：{M_Q}\n\n文书{doc_id}全文：\n{doc_texts.get(doc_id,'')}\n\n请抽取。")
                total_calls += 1
                E_texts[f"E_{doc_id}"] = r["text"] if ok else ""
                if not ok:
                    print(f"  E_{doc_id} FAILED, skipping"); break
            else:
                # 三臂
                arms = ARMS[:]
                random.Random(20261104+dl+rep).shuffle(arms)
                for arm in arms:
                    rec = run_arm(arm, dl, rep, E_texts, slots_json)
                    total_calls += len(rec.get("calls",[]))
                    if rec["status"] == "COMPLETE":
                        sc = score(rec["answers"], facts)
                        rec["score"] = sc
                        print(f"  [{arm}|D={dl}|r{rep}] TP={sc['hits']}/{sc['total']} wall={rec['wall_s']}s", flush=True)
                    else:
                        rec["score"] = {"hits":0,"total":len(facts),"rate":0}
                    all_recs.append(rec)

    # 分析
    from collections import defaultdict
    import statistics as st
    groups = defaultdict(list)
    for r in all_recs:
        if r["status"] == "COMPLETE":
            groups[(r["dl"], r["arm"])].append(r["score"]["hits"])
        else:
            groups[(r["dl"], r["arm"])].append(0)  # 失败计零

    print(f"\n{'='*60}")
    print(f"总调用: {total_calls}")
    for dl in DEADLINES:
        for arm in ARMS:
            scores = groups[(dl, arm)]
            if scores:
                actual = next((r["actual"] for r in all_recs if r["dl"]==dl and r["arm"]==arm), arm)
                print(f"  D={dl} {arm:<12} (→{actual:<10}) n={len(scores)} TP={st.mean(scores):.1f}/{len(facts)}")
        print()

    # Adaptive vs 最优固定
    for dl in DEADLINES:
        a_scores = groups[(dl,"Adaptive")]
        s_scores = groups[(dl,"Static")]
        p_scores = groups[(dl,"Proposed")]
        if a_scores and s_scores and p_scores:
            a = st.mean(a_scores); s = st.mean(s_scores); p = st.mean(p_scores)
            best = max(s, p)
            print(f"  D={dl}: Adaptive={a:.1f} vs best_fixed={best:.1f} (Static={s:.1f}, Proposed={p:.1f}) "
                  f"gain={a-best:+.1f} [{'PASS' if a>=best else 'FAIL'}]")

    (OUT / "ADAPTIVE_MVR2_RESULTS.json").write_text(
        json.dumps({"results":[{k:v for k,v in r.items() if k!='answers'} for r in all_recs],
                     "total_calls":total_calls}, ensure_ascii=False, indent=1), "utf-8")
    print(f"\n结果已保存 ADAPTIVE_MVR2_RESULTS.json")


if __name__ == "__main__":
    main()
