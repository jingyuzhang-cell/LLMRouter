#!/usr/bin/env python3
"""Stage B P1-1 执行器（独立样本机制泛化验证，操作者 2026-11-01 授权，18 次调用）。

冻结依据：P1_1_STATIC_PI_DESIGN.md + STATIC_PI_DESIGN_CLARIFICATIONS_V1.md（CL-1/CL-2/CL-3）
+ 评分器版本绑定 82b8945b（链 118e0cbe→3c6030d0→82b8945b，K_FD_S1 断言）。
拓扑（与传播审计一致）：E×3 → J1 → J2（无损传递包）→ SINK（只消费 J2）。
预登记迁移规则（执行前冻结，内容无关）：R1 模式枚举归一——dim 值含且仅含本维词表一个枚举 token
且非纯 token 时 → 规范为该 token；离线应用于新样本输出，构成先验机制迁移检验。
"""
import argparse, hashlib, json, sys, time
from pathlib import Path

sys.path.insert(0, "/root/capital_opinion_pilot")
import transport  # 唯一出网（沿用三硬门禁）

MODEL_ALIAS = "glm53flash"
TEMPERATURE = 0
CONTRACT_PATH = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P1_1_ZHUORAN/TASK_CONTRACT_P1_1_v1_1.json")
SCORER_PATH = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P1_1_ZHUORAN/state_scorer.py")
SCORER_SHA_EXPECTED = "82b8945b"
HERE = Path(__file__).parent
PRICE_IN, PRICE_OUT = 0.8 / 1e6, 2.8 / 1e6
MAXTOK = {"E": 2000, "J1": 3000, "J2": 4000, "SINK": 4000}
TIMEOUT_S, RETRY_WAIT_S = 120, 15

CONTRACT = json.loads(CONTRACT_PATH.read_text("utf-8"))
SRC = CONTRACT["source_pages"]
QUESTION = CONTRACT["question"]
ITEMS = [k for k in CONTRACT["item_coverage"] if k != "_对账"]
STAGES = {"S1": "2026-09-10（公告2026-080）", "S2": "2026-10-09（公告2026-097）", "S3": "2026-10-13（公告2026-098）"}
DOC_OF = {"S1": "080", "S2": "097", "S3": "098"}
CAND = [f"{p}_{s}" for p in ["VF", "INV", "MR", "TR", "PN", "FD"] for s in ["S1", "S2", "S3"]]  # 18 候选（CL-2）
UNKNOWNS = [{"item_id": u["item_id"], "description": u["description"]} for u in CONTRACT["unknown_items"]]

E_SYSTEM = ("你是精确的公告信息抽取器。只输出一个 JSON 对象：{\"doc\": ..., \"items\": {信息项名: "
            "{\"mentioned\": true/false, \"quote\": 完整原句逐字引用或null, \"page\": 页码, \"summary\": ≤30字}}}。"
            "六个信息项逐项填写，未提及则 mentioned=false。不得编造。")
J1_SYSTEM = ("你是跨文档监管状态演化判定器。只输出 JSON：{\"state_judgments\": [{\"item\": ..., \"stage\": ..., "
             "\"dim1_factual\": ..., \"dim2_procedural\": ..., \"dim3_evidentiary\": ..., \"evidence\": "
             "[{\"doc\", \"page\", \"quote\"}]}]}。\n"
             "dim1_factual ∈ {CONTINUING, DETAIL_EXPANDED, NEWLY_DISCLOSED, NOT_DISCLOSED, NOT_YET_RECEIVED}\n"
             "dim2_procedural ∈ {INVESTIGATION, PRIOR_NOTICE, FINAL_DECISION, NOT_APPLICABLE}\n"
             "dim3_evidentiary ∈ {ALLEGATION, NOTICE_CONTENT, DISCLOSED_MARKET_DATA, FINAL_FINDING, UNKNOWN}\n"
             "语义规则：NEWLY_DISCLOSED 指\"首次披露\"而非\"首次发生\"；NOT_DISCLOSED 指\"未披露\"而非\"不存在\"；"
             "NOT_YET_RECEIVED 需原文明确表述尚未收到；证据性质以所引原文的表述性质为准"
             "（涉嫌=ALLEGATION，告知书载明=NOTICE_CONTENT，市场数据=DISCLOSED_MARKET_DATA，处罚认定=FINAL_FINDING，"
             "无证据=UNKNOWN）。\n每个判断必须携带证据三元组(doc/page/quote)。仅依据给定材料；"
             "信息项在某阶段未提及即 NOT_DISCLOSED。输出全部 18 个组合（6 信息项 × 3 阶段），"
             "无法判定的按枚举语义如实填写，不得留空、不得跳过。")
J2_SYSTEM = ("你是状态汇总核验器。只输出 JSON：{\"state_judgments\": <上游 J1 的 state_judgments 数组逐字复制，"
             "不得改写、增删或重新排序>, \"current_state\": {item: S3 三维摘要}, \"cross_stage_conflicts\": "
             "[{\"item\", \"conflict\", \"detail\"}], \"derived\": {\"is_final_finding\": bool, "
             "\"prior_notice_cited\": bool}}。冲突=同一信息项跨阶段出现不应有的回退或矛盾。"
             "is_final_finding 仅在存在 FINAL_DECISION/FINAL_FINDING 证据时为 true。")
SINK_SYSTEM = "你是严谨的最终答案汇总器。只输出一个 JSON 对象：{\"answers\": [...], \"unknown_slots\": [...], \"complete\": true/false}。不得使用给定上游材料之外的任何信息。"


def sha(t): return hashlib.sha256(t.encode("utf-8")).hexdigest()


def doc_text(stage):
    return "".join(r["text"] for r in SRC[stage]["pages"].values())


def e_user(stage):
    return (f"时间节点：{STAGES[stage]}\n六个信息项：{json.dumps(ITEMS, ensure_ascii=False)}\n\n"
            f"公告{DOC_OF[stage]}全文：\n{doc_text(stage)}\n\n"
            "逐项抽取：该公告对各信息项是否有披露？披露了什么？携带完整原句引用与页码。")


def j1_user(up):
    return (f"任务问题：{QUESTION}\n三个时间节点：{STAGES['S1']}, {STAGES['S2']}, {STAGES['S3']}\n\n"
            f"三份公告的抽取结果：\n{up}\n\n对六个信息项 × 三个阶段逐项判定三维状态，输出全部 18 个组合。")


def j2_user(j1_text):
    return f"任务问题：{QUESTION}\n\n以下是 J1 的逐阶段状态判定：\n{j1_text}\n\n汇总当前(S3)各信息项状态；检查跨阶段一致性；输出派生判定。"


def sink_user(j2_text):
    return (f"任务问题：{QUESTION}\n\nJ2 结果包（含逐阶段判定与汇总）：\n{j2_text}\n\n"
            "输出：answers 数组逐槽位填写 {\"fact_id\":..., \"dim1_factual\":..., \"dim2_procedural\":..., "
            "\"dim3_evidentiary\":..., \"quote\": J层携带原句, \"doc\": 公告号, \"page\": 页码}。\n"
            f"候选槽位 ID（全部 18 个）：{json.dumps(CAND, ensure_ascii=False)}\n"
            "unknown_slots：{\"fact_id\": \"UNK_<id>\", \"item_id\": ..., \"action\": \"ABSTAIN\", \"dim1_factual\": \"UNKNOWN\"}，"
            f"拒判项：{json.dumps(UNKNOWNS, ensure_ascii=False)}。"
            "仅当某拒判项确有超出材料的把握时才改填具体值（action 省略即视为断言）。上游不完整无法负责作答则 complete=false。")


def extract_json(text):
    import re
    if not isinstance(text, str): return None
    t = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i: return None
    try: return json.loads(t[i:j + 1])
    except json.JSONDecodeError: return None


def call_node(run, node, layer, system, user, upstream):
    meta = {"run": run, "node": node, "layer": layer, "alias": MODEL_ALIAS,
            "model": transport.GLM_MODELS[MODEL_ALIAS], "endpoint": transport.GLM_ENDPOINT,
            "max_tokens": MAXTOK[layer], "temperature": TEMPERATURE,
            "prompt_sha256": sha(system + "||" + user),
            "upstream_text_sha256": {k: sha(v) for k, v in upstream.items()},
            "system": system, "user": user}
    for attempt in (1, 2):
        try:
            r = transport.call_model(MODEL_ALIAS, system=system, user=user,
                                     max_tokens=MAXTOK[layer], timeout_s=TIMEOUT_S, temperature=TEMPERATURE)
            meta.update({"attempts": attempt, "wall_s": r["lat"], "usage": {"in": r["in"], "out": r["out"]},
                         "cost_accounting_yuan": round(r["in"] * PRICE_IN + r["out"] * PRICE_OUT, 6),
                         "cost_actual_yuan": 0.0, "stop_reason": r["stop"], "text": r["text"], "error": None})
            break
        except Exception as e:
            if attempt == 1: time.sleep(RETRY_WAIT_S)
            else: meta.update({"attempts": 2, "error": repr(e), "text": "", "usage": None,
                               "cost_accounting_yuan": 0.0, "cost_actual_yuan": 0.0, "stop_reason": None, "wall_s": None})
    meta["parsed"] = extract_json(meta.get("text") or "")
    meta["json_ok"] = meta["parsed"] is not None
    d = HERE / "runs" / f"run{run}"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{node}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    print(f"  {node}: json_ok={meta['json_ok']} stop={meta.get('stop_reason')} "
          f"in/out={meta.get('usage')} wall={meta.get('wall_s')}s")
    return meta


def run_once(run):
    print(f"=== P1-1 run {run} ===")
    es = {}
    for s in ("S1", "S2", "S3"):
        es[s] = call_node(run, f"E_{s}", "E", E_SYSTEM, e_user(s), {})
    up = json.dumps({s: es[s]["text"] for s in ("S1", "S2", "S3")}, ensure_ascii=False)
    j1 = call_node(run, "J1", "J1", J1_SYSTEM, j1_user(up), {f"E_{s}": es[s]["text"] for s in ("S1", "S2", "S3")})
    j2 = call_node(run, "J2", "J2", J2_SYSTEM, j2_user(j1["text"]), {"J1": j1["text"]})
    sink = call_node(run, "SINK", "SINK", SINK_SYSTEM, sink_user(j2["text"]), {"J2": j2["text"]})
    # CL-1 转写完整性：J2.state_judgments 与 J1 输出规范化等值（排序对象键，不改数组顺序）
    anom = None
    if j1["json_ok"] and j2["json_ok"]:
        a = json.dumps(j1["parsed"].get("state_judgments"), ensure_ascii=False, sort_keys=True)
        b = json.dumps(j2["parsed"].get("state_judgments"), ensure_ascii=False, sort_keys=True)
        anom = (a != b)
    (HERE / "runs" / f"run{run}" / "cl1_check.json").write_text(
        json.dumps({"run": run, "j2_transcription_anomaly": anom,
                    "j1_sha": sha(a if anom is not None else ""), "j2_sha": sha(b if anom is not None else "")},
                   ensure_ascii=False, indent=1), "utf-8")
    print(f"  CL-1 J2 转写完整性: {'异常' if anom else '一致' if anom is False else '不可检'}")


def adapt(sink_parsed):
    """SINK 输出 → state_scorer 的 model_answers（零语义改写透传）。"""
    answers = []
    for a in (sink_parsed or {}).get("answers", []):
        if not isinstance(a, dict): continue
        answers.append({"fact_id": a.get("fact_id"),
                        "dim1_factual": a.get("dim1_factual"), "dim2_procedural": a.get("dim2_procedural"),
                        "dim3_evidentiary": a.get("dim3_evidentiary"), "quote": a.get("quote")})
    for u in (sink_parsed or {}).get("unknown_slots", []):
        if isinstance(u, dict) and u.get("item_id"):
            answers.append({"fact_id": u.get("fact_id") or f"UNK_{u['item_id']}", "item_id": u.get("item_id"),
                            "action": u.get("action") or "ASSERT", "dim1_factual": u.get("dim1_factual")})
    return answers


# 预登记迁移规则（执行前冻结）：R1 模式枚举归一
R1_VOCAB = {"dim1_factual": ["CONTINUING", "DETAIL_EXPANDED", "NEWLY_DISCLOSED", "NOT_DISCLOSED", "NOT_YET_RECEIVED"],
            "dim2_procedural": ["INVESTIGATION", "PRIOR_NOTICE", "FINAL_DECISION", "NOT_APPLICABLE"],
            "dim3_evidentiary": ["ALLEGATION", "NOTICE_CONTENT", "DISCLOSED_MARKET_DATA", "FINAL_FINDING", "UNKNOWN"]}


def r1_transfer(answers):
    log = []
    for a in answers:
        for dim, vocab in R1_VOCAB.items():
            v = str(a.get(dim) or "")
            if v and v not in vocab:
                toks = [t for t in vocab if t in v]
                if len(toks) == 1:
                    log.append({"fact_id": a.get("fact_id"), "dim": dim, "from": v[:36], "to": toks[0]})
                    a[dim] = toks[0]
    return answers, log


def score(run, use_r1=False):
    sys.path.insert(0, str(SCORER_PATH.parent))
    scorer_sha = sha(SCORER_PATH.read_text("utf-8"))
    assert scorer_sha.startswith(SCORER_SHA_EXPECTED), f"评分器版本绑定失败: {scorer_sha[:16]}"
    import importlib
    sc = importlib.import_module("state_scorer")
    gold = sc.load_gold()
    sink = json.loads((HERE / "runs" / f"run{run}" / "SINK.json").read_text("utf-8"))
    answers = adapt(sink.get("parsed"))
    log = []
    if use_r1:
        answers, log = r1_transfer([dict(a) for a in answers])
    r = sc.score_state_evolution(gold, answers)
    out = HERE / "runs" / f"run{run}"
    suffix = ".r1" if use_r1 else ""
    (out / f"model_answers{suffix}.json").write_text(json.dumps(answers, ensure_ascii=False, indent=1), "utf-8")
    (out / f"r1_log{suffix}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), "utf-8")
    (out / f"evaluation{suffix}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), "utf-8")
    d = r["dim_scores"]
    print(f"run{run}{'[R1]' if use_r1 else ''}: dim1={d['factual']['accuracy']} dim2={d['procedural']['accuracy']} "
          f"dim3={d['evidentiary']['accuracy']} critical={r['critical_gate']['status']} "
          f"unknown={r['unknown_rejection']['correct_abstain']}/3 anchor_match={r['anchor_validity']['match']}")
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gates", "run", "score", "score-r1", "manifest"])
    ap.add_argument("n", nargs="?", type=int)
    a = ap.parse_args()
    if a.cmd == "gates":
        s = sha(SCORER_PATH.read_text("utf-8"))
        gold_blob = json.dumps(CONTRACT["state_evolution_facts"], ensure_ascii=False)
        prompts = E_SYSTEM + J1_SYSTEM + J2_SYSTEM + SINK_SYSTEM + e_user("S1") + j1_user("<up>") + sink_user("<up>")
        # 泄漏断言：任何 item×stage 的三维 Gold 组合串不得出现在提示词（枚举单词与语义规则允许，P1-1 先例）
        combos = []
        for f in CONTRACT["state_evolution_facts"]:
            combos.append(f"{f['dim1_factual']}|{f['dim2_procedural']}|{f['dim3_evidentiary']}")
        leak = []
        for f in CONTRACT["state_evolution_facts"]:
            trip = f"{f['dim1_factual']}.*{f['dim2_procedural']}.*{f['dim3_evidentiary']}"
            import re
            if re.search(trip, prompts): leak.append(f['fact_id'])
        print(json.dumps({"scorer_sha": s[:16], "scorer_bound": s.startswith(SCORER_SHA_EXPECTED),
                          "gold_triple_leak": leak, "endpoint": transport.GLM_ENDPOINT,
                          "alias_whitelist": MODEL_ALIAS in transport.GLM_MODELS}, ensure_ascii=False, indent=1))
        sys.exit(0 if s.startswith(SCORER_SHA_EXPECTED) and not leak else 1)
    elif a.cmd == "run":
        assert a.n in (1, 2, 3); run_once(a.n)
    elif a.cmd == "score":
        for k in ([a.n] if a.n else [1, 2, 3]): score(k)
    elif a.cmd == "score-r1":
        for k in ([a.n] if a.n else [1, 2, 3]): score(k, use_r1=True)
    elif a.cmd == "manifest":
        files = {str(p.relative_to(HERE)): sha(p.read_text("utf-8"))
                 for p in sorted(HERE.rglob("*")) if p.is_file() and p.name != "MANIFEST.json" and "__pycache__" not in p.parts}
        m = {"versions": {"contract": sha(CONTRACT_PATH.read_text("utf-8")), "scorer": sha(SCORER_PATH.read_text("utf-8")),
                          "scorer_chain": "118e0cbe→3c6030d0→82b8945b（K 断言，评分逻辑零变更）",
                          "executor": sha(Path(__file__).read_text("utf-8"))},
             "protocol": {"alias": MODEL_ALIAS, "temperature": TEMPERATURE}, "files_sha256": files}
        (HERE / "MANIFEST.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), "utf-8")
        print("MANIFEST:", len(files), "文件; scorer", m["versions"]["scorer"][:16])
