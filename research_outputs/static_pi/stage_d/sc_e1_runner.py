#!/usr/bin/env python3
"""SC-E1 獐子岛三臂确认性实验 Runner。

三臂（Static/Fixed-Recovery/Joint-Dynamic）× 三条件（正常/执行异常/信息异常）× 4 rep。
Gold 20 槽。Q_terminal = 0.5F + 0.3E + 0.2C。

GO 门：SC_E1_GO=1
"""
import json, os, sys, time, random, re, hashlib
import urllib.request
from pathlib import Path

STAGE_D = Path("/root/research_outputs/static_pi/stage_d")
GOLD = "/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/SC_E1_ZHANGZIDAO/TASK_CONTRACT_SC_E1_v1.json"
OUT = STAGE_D / "sc_e1_runs"
GLM_URL = "https://open.bigmodel.cn/api/anthropic/v1/messages"
REPS = 4
CONDITIONS = ["normal", "exec_anomaly", "info_anomaly"]

# ===== 提示词 =====
E_SYS = ("你是精确的处罚文书抽取器。只输出 JSON：{\"parties\": [{name, penalty_amount, penalty_type, "
         "position, quote}], \"doc_number\": ..., \"dates\": {...}, \"fraud_facts\": [{item, amount, quote}], "
         "\"delisting_risk\": ..., \"quotes\": [...]}。每项附完整原句引用。不得编造。")

J1_SYS = ("你是跨文书处罚阶段衔接器。给定告知书(D1)和决定书(D2)的抽取结果，"
          "只输出 JSON，完成拟终配对：{\"party_matrix\": [{name, proposed_penalty, final_penalty, position, "
          "adjustment_note, evidence:[{doc,quote}]}], \"date_chain\": {...}, \"doc_numbers\": {...}}。"
          "拟罚取自D1告知书，终罚取自D2决定书。仅依据给定材料。")

J2_SYS = ("你是处罚矩阵核验器。核验上游配对：金额是否正确、主体是否对应、合计是否等于各部分之和。"
          "只输出 JSON：{\"verified\": [{fact_id, status, final_value}], \"derived\": [{fact_id, value, computation}]}。"
          "仅依据给定材料。")

SINK_SYS = ("你是严谨的最终答案汇总器。只输出 JSON：{\"answers\": [{fact_id, value, quote, doc}], "
            "\"unknown_slots\": []}。不得使用给定上游材料之外的任何信息。")


def glm_low(system, user, max_tokens=8192, timeout_s=300):
    key = os.environ.get("STAGE_D_GLM_KEY", "").strip()
    if not key: raise RuntimeError("STAGE_D_GLM_KEY not set")
    body = {"model": "GLM-5.3-Flash", "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}], "reasoning_effort": "low"}
    req = urllib.request.Request(GLM_URL, data=json.dumps(body, ensure_ascii=False).encode(), method="POST")
    for h in [("content-type","application/json"),("x-api-key",key),("authorization","Bearer "+key),("anthropic-version","2023-06-01")]:
        req.add_header(*h)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        return {"text": "", "in": 0, "out": 0, "stop": "error", "lat": round(time.monotonic()-t0,2), "error": str(e)[:100]}
    return {"text": "".join(b.get("text","") for b in d.get("content",[]) if b.get("type")=="text"),
            "in": d["usage"]["input_tokens"], "out": d["usage"]["output_tokens"],
            "stop": d.get("stop_reason"), "lat": round(time.monotonic()-t0,2)}

def ds_call(system, user, max_tokens=4000, timeout_s=300):
    sys.path.insert(0, "/root/capital_opinion_pilot")
    import transport
    t0 = time.monotonic()
    r = transport.openai_call("deepseek", system, user, max_tokens, timeout_s, 0)
    r["lat"] = round(time.monotonic()-t0, 2)
    return r

def extract_json(text):
    if not isinstance(text, str): return None
    t = re.sub(r'^```(json)?|```$', '', text.strip(), flags=re.M).strip()
    i, j = t.find('{'), t.rfind('}')
    if i < 0 or j <= i: return None
    try: return json.loads(t[i:j+1])
    except: return None


def run_arm(arm, condition, rep, E_texts, slots_json):
    calls = []
    j1_input = f"告知书(D1)抽取：\n{E_texts.get('E_D1','')}\n\n决定书(D2)抽取：\n{E_texts.get('E_D2','')}"

    # === 异常注入 ===
    j1_system = J1_SYS
    inject_empty = (condition == "exec_anomaly")
    if condition == "info_anomaly":
        j1_system = J1_SYS.replace("拟罚取自D1告知书，终罚取自D2决定书", "")  # 部署缺陷：遗漏关键指令

    # === J1 ===
    j1_backend = "ds"  # GLM 端点不稳定 + 能力矩阵：矩阵推理用 DS
    j1_text = ""
    parsed_j1 = None

    if not inject_empty:
        r1 = glm_low(j1_system, j1_input) if j1_backend == "glm" else ds_call(j1_system, j1_input, max_tokens=8000)
        calls.append({"node":"J1","backend":j1_backend,"lat":r1.get("lat"),"stop":r1.get("stop")})
        j1_text = r1["text"]
        parsed_j1 = extract_json(j1_text)
    else:
        # 注入空文本（执行异常）
        j1_text = ""
        parsed_j1 = None
        calls.append({"node":"J1","backend":j1_backend,"lat":0,"stop":"injected_empty"})

    # === 恢复逻辑（臂间差异的核心）===
    if parsed_j1 is None:
        if arm == "Static":
            return {"arm":arm,"condition":condition,"rep":rep,"status":"INCOMPLETE_NO_RECOVERY",
                    "calls":calls,"answers":[],"Q_terminal":0,"F":0,"E":0,"C":0}

        elif arm == "Fixed-Recovery":
            # 固定恢复：结构修复+重试（不换模，用同一模型重试）
            retry_sys = J1_SYS + "\n请务必输出完整JSON。"
            r1r = glm_low(retry_sys, j1_input) if j1_backend == "glm" else ds_call(retry_sys, j1_input, max_tokens=8000)
            calls.append({"node":"J1_retry","backend":j1_backend,"lat":r1r.get("lat"),"stop":r1r.get("stop")})
            j1_text = r1r["text"]
            parsed_j1 = extract_json(j1_text)
            if parsed_j1 is None:
                return {"arm":arm,"condition":condition,"rep":rep,"status":"INCOMPLETE_RECOVERY_FAILED",
                        "calls":calls,"answers":[],"Q_terminal":0,"F":0,"E":0,"C":0}

        elif arm == "Joint-Dynamic":
            # 诊断驱动：空文本=模型异常→换模到DS
            # 信息质量异常→补充遗漏指令（结构修复）
            if inject_empty:
                # 诊断：执行实例异常→重试（同模型，注入的是空文本非模型缺陷）
                action = "retry_same_model"
                r1s = ds_call(J1_SYS, j1_input)
                calls.append({"node":"J1_retry","backend":"ds","lat":r1s.get("lat"),"stop":r1s.get("stop"),"action":action})
                j1_text = r1s["text"]
                parsed_j1 = extract_json(j1_text)
            else:
                # 信息质量异常→结构修复（补回遗漏指令）
                action = "structure_repair"
                r1z = glm_low(J1_SYS, j1_input)
                calls.append({"node":"J1_repair","backend":"glm","lat":r1z.get("lat"),"stop":r1z.get("stop"),"action":action})
                j1_text = r1z["text"]
                parsed_j1 = extract_json(j1_text)

            if parsed_j1 is None:
                return {"arm":arm,"condition":condition,"rep":rep,"status":"INCOMPLETE_RECOVERY_FAILED",
                        "calls":calls,"answers":[],"Q_terminal":0,"F":0,"E":0,"C":0}

    # === J2 ===
    r2 = ds_call(J2_SYS, f"上游配对结果：\n{j1_text[:3000]}\n\n槽位：{slots_json}")
    calls.append({"node":"J2","backend":"ds","lat":r2.get("lat"),"stop":r2.get("stop")})

    # === SINK ===
    r3 = ds_call(SINK_SYS, f"核验结果：\n{r2['text'][:2000]}\n\n槽位：{slots_json}")
    calls.append({"node":"SINK","backend":"ds","lat":r3.get("lat"),"stop":r3.get("stop")})
    parsed_sink = extract_json(r3["text"])
    answers = (parsed_sink or {}).get("answers", [])

    return {"arm":arm,"condition":condition,"rep":rep,"status":"COMPLETE",
            "calls":calls,"answers":answers}


def score(answers, gold_facts):
    gold_map = {f['fact_id']: f for f in gold_facts}
    correct = 0; cited = 0; covered = 0; wrong = 0
    for a in answers or []:
        if not isinstance(a, dict): continue
        fid = a.get('fact_id')
        if fid not in gold_map: continue
        g = gold_map[fid]
        gv, av = g.get('value'), a.get('value')
        # 值匹配
        def norm(v):
            if isinstance(v, (int, float)): return float(v)
            s = re.sub(r'[,，\s万元亿元%]', '', str(v))
            m = re.search(r'[\d.]+', s)
            try: return float(m.group()) if m else None
            except: return None
        gn, an = norm(gv), norm(av)
        val_ok = (gn is not None and an is not None and abs(gn-an)<0.01)
        if val_ok:
            correct += 1
            # 证据
            doc = a.get('doc','')
            quote = str(a.get('quote',''))[:30]
            if doc and quote:
                cited += 1
        else:
            wrong += 1
        covered += 1

    n = len(gold_facts)
    F = correct / max(covered, 1) if covered > 0 else 0
    E = cited / max(correct, 1) if correct > 0 else 0
    C = covered / n if n > 0 else 0
    Q = 0.5*F + 0.3*E + 0.2*C
    err_rate = wrong / max(covered, 1) if covered > 0 else 0
    return {"Q_terminal":round(Q,4),"F":round(F,4),"E":round(E,4),"C":round(C,4),
            "correct":correct,"wrong":wrong,"covered":covered,"total":n,"error_rate":round(err_rate,4)}


def main():
    if os.environ.get("SC_E1_GO") != "1":
        raise SystemExit("REFUSED: requires SC_E1_GO=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("REFUSED: DEEPSEEK_API_KEY not set")
    OUT.mkdir(parents=True, exist_ok=True)

    gold = json.load(open(GOLD))
    facts = gold["required_facts"]
    src = gold.get("source_pages", {})
    slots_json = json.dumps([{"fact_id":f["fact_id"],"subject":f.get("subject",""),
                              "predicate":f.get("predicate","")} for f in facts], ensure_ascii=False)
    d1_text = src.get("D1",{}).get("pages",{}).get("1",{}).get("text","")
    d2_text = src.get("D2",{}).get("pages",{}).get("1",{}).get("text","")

    all_recs = []
    total_calls = 0

    for rep in range(1, REPS+1):
        # 共享 E（每 rep 一次）
        E_texts = {}
        for doc_id, doc_text, node_name in [("D1", d1_text, "E_D1"), ("D2", d2_text, "E_D2")]:
            r = ds_call(E_SYS, f"请从以下文书中抽取全部信息：\n\n{doc_text[:6000]}")
            total_calls += 1
            E_texts[node_name] = r["text"]
            print(f"  E_{doc_id}(ds): {len(r['text'])}ch", flush=True)

        for condition in CONDITIONS:
            for arm in ("Static", "Fixed-Recovery", "Joint-Dynamic"):
                try:
                    rec = run_arm(arm, condition, rep, E_texts, slots_json)
                except Exception as e:
                    rec = {"arm":arm,"condition":condition,"rep":rep,
                           "status":f"ERROR:{str(e)[:60]}","calls":[],"answers":[]}
                    print(f"  [{arm}|{condition}|r{rep}] ERROR: {str(e)[:80]}", flush=True)
                total_calls += len(rec.get("calls", []))
                if rec["status"] == "COMPLETE":
                    sc = score(rec["answers"], facts)
                    rec.update(sc)
                    print(f"  [{arm}|{condition}|r{rep}] Q={sc['Q_terminal']:.3f} F={sc['F']:.2f} "
                          f"C={sc['C']:.2f} err={sc['error_rate']:.2f}", flush=True)
                else:
                    rec.update({"Q_terminal":0,"F":0,"E":0,"C":0,"error_rate":0,
                                "correct":0,"wrong":0,"covered":0,"total":len(facts)})
                    print(f"  [{arm}|{condition}|r{rep}] {rec['status']}", flush=True)
                all_recs.append(rec)

    # 分析
    from collections import defaultdict
    import statistics as st
    groups = defaultdict(list)
    for r in all_recs:
        groups[(r["condition"], r["arm"])].append(r["Q_terminal"])

    print(f"\n{'='*70}")
    print(f"总调用: {total_calls}")
    print(f"\n{'条件':<16}{'臂':<18}{'n':>3}{'Q_terminal':>12}")
    for cond in CONDITIONS:
        for arm in ("Static","Fixed-Recovery","Joint-Dynamic"):
            scores = groups[(cond, arm)]
            if scores:
                print(f"{cond:<16}{arm:<18}{len(scores):>3}{st.mean(scores):>12.4f}")
        print()

    # 主终点
    print("===== 主终点: ΔQ = Q_Joint − Q_Fixed =====")
    for cond in CONDITIONS:
        j_scores = groups[(cond, "Joint-Dynamic")]
        f_scores = groups[(cond, "Fixed-Recovery")]
        s_scores = groups[(cond, "Static")]
        if j_scores and f_scores:
            djf = st.mean(j_scores) - st.mean(f_scores)
            djs = st.mean(j_scores) - st.mean(s_scores) if s_scores else 0
            best_fixed = max(st.mean(f_scores), st.mean(s_scores)) if s_scores else st.mean(f_scores)
            gain = st.mean(j_scores) - best_fixed
            verdict = "PASS" if st.mean(j_scores) >= best_fixed else "FAIL"
            print(f"  {cond}: ΔQ(J-F)={djf:+.4f} ΔQ(J-S)={djs:+.4f} "
                  f"vs_best={gain:+.4f} [{verdict}]")

    (OUT / "SC_E1_RESULTS.json").write_text(
        json.dumps({"results":[{k:v for k,v in r.items() if k not in ('answers','calls')} for r in all_recs],
                     "total_calls":total_calls}, ensure_ascii=False, indent=1), "utf-8")
    print(f"\n结果已保存 SC_E1_RESULTS.json")


if __name__ == "__main__":
    main()
