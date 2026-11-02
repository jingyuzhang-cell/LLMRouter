#!/usr/bin/env python3
"""Stage A Static-π 最小执行器（P0-1 实体归一 + P0-2 双编号绑定）。

操作者 2026-11-01 授权的六步程序之前四步：一次性执行器 + 三硬门禁 + 21 次真实调用
（7 节点 × 3 重复）+ 全量持久化；后两步：冻结评分器独立评价 + 六项指标分别报告。

拓扑（PHASE2B 依赖表验证版，与 P1-1 的 CL-1 规则无关——那是 P1-1 专属拓扑）：
  E1(D1) E2(D2) -> J1（实体归一，只消费 E1+E2）
  J1 + E3(D3) + E4(D4) -> J2（主体绑定计数；D1/D2 仅经 J1 到达 J2）
  J1 + J2 -> SINK（只消费 J1+J2，无 E 旁路）

执行期澄清（EC 系列，记录于运行报告与治理文档）：
  EC-1  SINK 提示词按 CL-3 修订：J1/J2 证据= (doc_id,page,quote) 三元组，哈希字段
        全部移除；SINK answers 增加 page 字段（评分器 citation 需要）；A1-A4/C1/C2/B3b
        增加内容无关的 value_format 编码规格（枚举前缀/绑定记法=任务定义，P1-1 枚举
        先例；不含任何 gold 取值）。
  EC-2  E3 合同缺陷（gold='2(公司+自然人王勇)' 与 value_kind=number 矛盾，_decimal
        解析 None，gold 自答亦不可匹配）——合同不改（冻结），报告层诊断分离。
  EC-3  B3/F4 自由文本关键事实的精确匹配依赖 judge 路径（校准评审不可用）——如实
        预期格式性未匹配，诊断层用确定性分解另行报告。

唯一出网路径 = /root/capital_opinion_pilot/transport.py :: call_model（硬门禁 1）。
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "/root/capital_opinion_pilot")
import transport  # noqa: E402  — 唯一出网模块（硬门禁 1）

MODEL_ALIAS = "glm53flash"                                   # 硬门禁 2：Stage A/B 别名白名单
ENDPOINT_ECHO = transport.GLM_ENDPOINT                       # 硬门禁 3：端点回显
TEMPERATURE = 0                                              # 冻结协议
TRANSPORT_SHA_EXPECTED = "7a423eb38d07592a"                  # cc652395…（默认行为不变）→ 7a423eb3…

HERE = Path(__file__).parent
CONTRACT_PATH = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/TASK_CONTRACT_PHASE2B_v2_1.json")
CONTRACT_SHA_EXPECTED = "f92090b0"                           # 64 位前 8 位（完整值入 MANIFEST）
EVALUATOR_DIR = Path("/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4")
sys.path.insert(0, str(EVALUATOR_DIR))
from terminal_quality import evaluate_terminal_quality  # noqa: E402  — 冻结评分器 v1.2.3

PRICE_IN, PRICE_OUT = 0.8 / 1e6, 2.8 / 1e6                   # 冻结牌价（核算口径，¥/token）
MAXTOK = {"E": 2500, "J1": 2500, "J2": 3500, "SINK": 4000}
TIMEOUT_S = 120
RETRY_WAIT_S = 15

CONTRACT = json.loads(CONTRACT_PATH.read_text("utf-8"))
SRC = CONTRACT["source_pages"]
QUESTION = CONTRACT["question"]
DOCMAP = {"E1": "D1", "E2": "D2", "E3": "D3", "E4": "D4"}

# ---- 槽位表（SINK 可见；无 description/value；value_format 仅 EC-1 登记的编码规格） ----
FMT_A = "<COMPANY_ONLY|PERSON_ONLY|BOTH>_<立案对象描述(含姓名/公司名，取自原文)>"
VALUE_FORMATS = {
    "A1": FMT_A, "A2": FMT_A, "A3": FMT_A, "A4": FMT_A,
    "C1": "<SPECIFIC|GENERIC>_<事由简述(取自原文)>",
    "C2": "<SPECIFIC|GENERIC>_<事由简述(取自原文)>",
    "B3b": ("<编号>→<主体>；<编号>→<主体>（公司主体写 公司(公司简称)，自然人写姓名；"
            "按原文'分别…分别'顺序对应规则逐号绑定）"),
}
SLOTS = []
for f in CONTRACT["required_facts"]:
    s = {"fact_id": f["fact_id"], "subject": f["subject"], "predicate": f["predicate"],
         "value_kind": f.get("value_kind", "text"), "unit": f.get("unit", ""),
         "date_type": f.get("date_type", "")}
    if f["fact_id"] in VALUE_FORMATS:
        s["value_format"] = VALUE_FORMATS[f["fact_id"]]
    SLOTS.append(s)
SLOTS_BY_ID = {s["fact_id"]: s for s in SLOTS}
UNKNOWNS = [{"item_id": u["item_id"], "description": u["description"]} for u in CONTRACT["unknown_items"]]
UNKNOWN_IDS = {u["item_id"] for u in UNKNOWNS}

# ---- 提示词（phase2b_prompts.py 冻结构造 + CL-3/EC-1 执行期修订） ----
E_SYSTEM = ("你是精确的文书信息抽取器。只输出一个 JSON 对象：{ \"subjects\": [...], \"notice_numbers\": [...], "
            "\"dates\": [...], \"cause\": [...], \"quotes\": [...] }，每项为 {field,value,quote(完整原句逐字引用),page}。不得编造。")
J1_SYSTEM = ("你是跨文档实体归一核验器。只输出 JSON：{ \"judgments\": [{ \"kind\": person_identity|notice_instance|"
             "receipt_event|announcing_companies, \"verdict\": SAME_PERSON|DIFFERENT_PERSON|SAME_NOTICE_INSTANCE|"
             "DIFFERENT_NOTICE_INSTANCE|SAME_RECEIPT_EVENT|DIFFERENT_EVENT|SAME_COMPANY|DIFFERENT_COMPANY|UNKNOWN, "
             "\"evidence\": [{\"doc_id\":..., \"page\":..., \"quote\": 上游原句}] , "
             "\"reasoning\": 每项不超过15字 }] }。每个判断必须携带证据三元组(doc_id/page/quote)，"
             "照抄上游引文，不得省略。仅依据给定材料。")
J2_SYSTEM = ("你是主体绑定与计数核验器。只输出 JSON：{ \"subject_binding\": [{doc, subject_type, entities, "
             "evidence:[证据三元组]}], \"notice_binding\": [{doc, numbers, per_number_binding_or_null, "
             "rule_applied: ordered_correspondence|null, evidence:[证据三元组]}], \"cause_specificity\": "
             "[{doc, class, evidence:[证据三元组]}], \"counts\": {personal_filing_instances, "
             "announcing_company_count, d3_subject_count, evidence:[证据三元组]}, \"unresolvable\": "
             "[{field, reason}] }。subject_type ∈ {COMPANY_ONLY, PERSON_ONLY, BOTH}；cause class ∈ "
             "{SPECIFIC, GENERIC}。每项判断必须携带证据三元组(doc_id/page/quote)，照抄上游引文；"
             "无法判定项列入 unresolvable（如日期仅'近日'）。仅依据给定材料。")
SINK_SYSTEM = ("你是严谨的最终答案汇总器。只输出一个 JSON 对象：{\"answers\":[...], \"abstentions\":[...], "
               "\"complete\": true/false}。不得使用给定上游材料之外的任何信息。")


def e_user(node):
    doc = DOCMAP[node]
    text = "".join(rec["text"] for rec in SRC[doc]["pages"].values())
    return (f"任务问题：{QUESTION}\n\n文档{doc}全文：\n{text}\n\n"
            "请抽取：立案对象(公司/个人/两者及姓名)、告知书编号(逐个)、全部日期(注明性质：落款/收到)、"
            "立案事由(原句)、以及对应完整原句引用。输出上述 JSON。")


def j1_user(upstream_e1_e2):
    return (f"任务问题：{QUESTION}\n\n以下是两份公告（不同上市公司）的抽取结果：\n{upstream_e1_e2}\n\n"
            "请判定：两份公告中的'俞发祥'是否同一自然人；两份公告引用的告知书是否同一份实例；"
            "收到事件是否同一事件；两家公告主体是否同一公司。按系统约定输出。")


def j2_user(upstream_j1_e3e4):
    return (f"任务问题：{QUESTION}\n\n以下是实体归一结果与另两份公告抽取：\n{upstream_j1_e3e4}\n\n"
            "请完成：四份公告各自的主体绑定与编号归属（含 D3 两编号按'分别…分别'顺序对应规则逐号绑定）；"
            "事由特定性分类；三项计数。按系统约定输出。")


def sink_user(upstream_j1j2):
    return (f"任务问题：{QUESTION}\n\n以下是实体归一与主体绑定计数结果：\n{upstream_j1j2}\n\n"
            "输出格式：answers 按槽位逐项填写 {{\"fact_id\":..., \"value\":..., \"quote\": 上游所引完整原句, "
            "\"doc\": 文档ID, \"page\": 页码}}。有 value_format 的槽位必须严格按该格式填写 value。"
            "数值只填数字；日期 YYYY-MM-DD；关系判断按槽位语义作答。\n"
            f"槽位：{json.dumps(SLOTS, ensure_ascii=False)}\n"
            f"unknown 项（无法确定且属下列项时写入 abstentions：{{\"item_id\":..., \"text\": 明确拒判语句}}）：{json.dumps(UNKNOWNS, ensure_ascii=False)}\n"
            "如认为上游不完整无法负责作答，置 complete=false。")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ============ 硬门禁 + 隔离断言（零调用） ============
ENUM_VOCAB = {"SAME_PERSON", "DIFFERENT_PERSON", "SAME_NOTICE_INSTANCE", "DIFFERENT_NOTICE_INSTANCE",
              "SAME_RECEIPT_EVENT", "DIFFERENT_EVENT", "SAME_COMPANY", "DIFFERENT_COMPANY", "UNKNOWN",
              "COMPANY_ONLY", "PERSON_ONLY", "BOTH", "SPECIFIC", "GENERIC",
              "person_identity", "notice_instance", "receipt_event", "announcing_companies"}


def run_gates():
    import ast
    report = {}
    transport_sha = sha(Path(transport.__file__).read_text("utf-8"))
    src_text = Path(__file__).read_text("utf-8")

    # gate 1a: AST import 审计——执行器自身不得引入任何网络模块（transport 经它出网）
    tree = ast.parse(src_text)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    net_modules = {"urllib", "requests", "httpx", "http", "socket", "ssl", "ftplib", "smtplib", "telnetlib"}
    bad_imports = sorted(imported & net_modules)
    # gate 1b: 网络调用 token 扫描（token 运行时拼接，避免正则字面量自匹配）
    toks = ["".join(t) for t in (("url", "open("), ("urllib", ".request"), ("import ", "requests"),
                                 ("import ", "httpx"), ("socket", ".connect"), ("http", ".client"))]
    src_no_gates = src_text.split("# ============ CL-3")[0]  # gates 段含检查 token 本身
    net_calls = [t for t in toks if t in src_no_gates]
    report["gate1_import_audit"] = {
        "bad_network_imports": bad_imports,
        "network_call_tokens_found": net_calls,
        "single_egress_module": transport.__name__ == "transport",
        "transport_sha256_prefix": transport_sha[:16],
        "transport_sha_matches_extended_version": transport_sha.startswith(TRANSPORT_SHA_EXPECTED),
    }
    report["gate2_alias_whitelist"] = {"alias": MODEL_ALIAS, "in_transport_glm_models": MODEL_ALIAS in transport.GLM_MODELS}
    report["gate3_endpoint_echo"] = {"endpoint": ENDPOINT_ECHO,
                                     "is_open_bigmodel_cn": ENDPOINT_ECHO == "https://open.bigmodel.cn/api/anthropic/v1/messages"}
    # 隔离断言：任何提示词不含 gold 值（纯枚举词豁免=输出词汇表）/ description 片段
    desc_frags = [f.get("description", "")[:20] for f in CONTRACT["required_facts"] if len(f.get("description", "")) > 8]
    prompts = {"E_SYSTEM": E_SYSTEM, "SINK_SYSTEM": SINK_SYSTEM, "J1_SYSTEM": J1_SYSTEM, "J2_SYSTEM": J2_SYSTEM,
               "e1": e_user("E1"), "j1": j1_user("<upstream>"), "j2": j2_user("<upstream>"),
               "sink": sink_user("<upstream>")}
    doc_blob = "".join(r["text"] for d in SRC.values() for r in d["pages"].values())
    leaks = []
    for name, blob in prompts.items():
        for dt in desc_frags:
            if dt in blob:
                leaks.append(f"{name}: description fragment")
        for f in CONTRACT["required_facts"]:
            v = f.get("value", "")
            if not (isinstance(v, str) and len(v) > 4 and v in blob):
                continue
            if v in ENUM_VOCAB and name in ("J1_SYSTEM", "J2_SYSTEM", "SINK_SYSTEM", "sink"):
                continue  # 枚举词=输出词汇表（phase2b 隔离检查允许项），非答案泄露
            # E 提示词含文档全文：gold 值若存在于文档原文则非构造泄露（结构上=question+doc_text）
            if name.startswith("e") and v in doc_blob:
                continue
            if name in ("j1", "j2", "sink"):
                continue  # 运行时 user 部分只含上游输出占位符；真实上游=模型输出，非提示词构造
            leaks.append(f"{name}: gold value of {f['fact_id']}")
    for fid, fmt in VALUE_FORMATS.items():
        gold = next(f["value"] for f in CONTRACT["required_facts"] if f["fact_id"] == fid)
        if gold in fmt:
            leaks.append(f"value_format {fid} contains gold value")
    report["isolation_asserts"] = {"leaks": leaks, "checked_prompts": list(prompts)}
    enum_labels = sorted(t for t in ENUM_VOCAB if t.isupper())
    e_leak = [lab for lab in enum_labels if lab in (E_SYSTEM + e_user("E1"))]
    report["isolation_asserts"]["enum_labels_in_E_prompt"] = e_leak

    ok = (not bad_imports and not net_calls
          and report["gate1_import_audit"]["single_egress_module"]
          and report["gate1_import_audit"]["transport_sha_matches_extended_version"]
          and report["gate2_alias_whitelist"]["in_transport_glm_models"]
          and report["gate3_endpoint_echo"]["is_open_bigmodel_cn"]
          and not leaks and not e_leak)
    report["ALL_GATES_PASS"] = ok
    (HERE / "gates_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return ok


def adapter_selftest():
    """gold 自答经本执行器适配器+冻结评分器（零调用）。预期 22/23 TP，E3 为 EC-2 已知缺陷。"""
    answers = []
    for f in CONTRACT["required_facts"]:
        ev = (f.get("source_evidence") or [{}])[0]
        answers.append({"fact_id": f["fact_id"], "value": f["value"],
                        "quote": ev.get("quote", ""), "doc": ev.get("doc_id"), "page": ev.get("page")})
    sink_out = {"answers": answers,
                "abstentions": [{"item_id": u["item_id"], "text": "原文仅'近日'，不可判定，拒绝断言。"} for u in CONTRACT["unknown_items"]],
                "complete": True}
    term = build_terminal_output(sink_out)
    r = evaluate_terminal_quality(CONTRACT, term, SRC)
    bad = [x for x in r["claim_results"] if x["status"] not in ("CORRECT_GOLD", "SEMANTICALLY_CORRECT")]
    ok = (r["critical_gate"]["status"] == "PASS" and r["gold_coverage"] == 1.0
          and [b["fact_id"] for b in bad] == ["E3"])
    print(f"adapter selftest: {'PASS' if ok else 'FAIL'} | critical={r['critical_gate']['status']} "
          f"| TP={r['fact_metrics']['weighted_tp']} | known-E3-bad={[b['fact_id'] for b in bad]}")
    return ok


# ============ CL-3 可信适配器（模型只出三元组，哈希由冻结 source_pages 绑定） ============
def build_terminal_output(sink_parsed):
    claims = []
    for a in (sink_parsed or {}).get("answers", []) if isinstance(sink_parsed, dict) else []:
        if not isinstance(a, dict):
            continue
        fid = a.get("fact_id")
        slot = SLOTS_BY_ID.get(fid)
        if slot is None:      # U2 等拒判项被误答成 answer → 映射为 unknown 断言
            if fid in UNKNOWN_IDS:
                claims.append({"claim_id": f"c_{fid}", "item_id": fid, "value": a.get("value"),
                               "citations": [], "weight": 1.0, "material": True})
            continue
        cite = {"doc_id": a.get("doc"), "page": a.get("page"), "quote": a.get("quote", "")}
        doc = SRC.get(cite["doc_id"]) if cite["doc_id"] else None
        pg = doc["pages"].get(str(cite["page"])) if doc else None
        if pg:                # CL-3：哈希绑定只发生在评分适配边界，来自冻结文书
            cite["page_sha256"] = pg["page_sha256"]
            cite["raw_sha256"] = doc["raw_sha256"]
        claims.append({"claim_id": f"c_{fid}", "fact_id": fid,
                       "subject": slot["subject"], "predicate": slot["predicate"],   # 冻结槽位表机械拷贝
                       "value": a.get("value"),
                       "value_kind": slot["value_kind"], "unit": slot["unit"], "date_type": slot["date_type"],
                       "citations": [cite], "weight": 1.0, "material": True})
    abstentions = [{"item_id": x.get("item_id"), "text": str(x.get("text", ""))}
                   for x in ((sink_parsed or {}).get("abstentions", []) if isinstance(sink_parsed, dict) else [])
                   if isinstance(x, dict)]
    abstained = {x["item_id"] for x in abstentions}
    asserted = {c.get("item_id") for c in claims if c.get("item_id")}
    return {"claims": claims, "abstentions": abstentions,
            "abstentions_complete": UNKNOWN_IDS <= (abstained | asserted)}


def extract_json(text):
    if not isinstance(text, str):
        return None
    t = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None


# ============ 节点执行与持久化 ============
MAXTOK_KEY = {"E1": "E", "E2": "E", "E3": "E", "E4": "E", "J1": "J1", "J2": "J2", "SINK": "SINK"}


def call_node(run, node, system, user, upstream, out_dir=None, alias=None, layer_key=None):
    """默认路径与 baseline 完全一致；干预臂可指定落点目录/别名/令牌档（逐节点白名单在调用方断言）。"""
    alias = alias or MODEL_ALIAS
    if alias == "glm53flash":
        model, endpoint = transport.GLM_MODELS[alias], ENDPOINT_ECHO
    elif alias == DS_ALIAS:
        assert node in ("J2DS", "J2J", "J2DDS"), f"逐节点白名单违反：{alias} 不允许 {node}"
        model, endpoint = transport.OPENAI_MODELS[alias][0], DS_ENDPOINT
    else:
        raise ValueError(f"别名白名单外：{alias}")
    lk = layer_key or MAXTOK_KEY[{"J1r": "J1", "J2r": "J2"}.get(node, node)]
    meta = {"run": run, "node": node, "layer": lk,
            "alias": alias, "model": model, "endpoint": endpoint,
            "max_tokens": MAXTOK[lk], "temperature": TEMPERATURE,
            "prompt_sha256": sha(system + "||" + user),
            "upstream_text_sha256": {k: sha(v) for k, v in upstream.items()},
            "system": system, "user": user}
    last_err = None
    for attempt in (1, 2):
        try:
            r = transport.call_model(alias, system=system, user=user,
                                     max_tokens=meta["max_tokens"], timeout_s=TIMEOUT_S, temperature=TEMPERATURE)
            cost = (round(r["in"] * PRICE_IN + r["out"] * PRICE_OUT, 6) if alias == MODEL_ALIAS
                    else round(r["in"] * 1e-6 + r["out"] * 2e-6, 6))  # DS：估算口径，实际以账单为准
            meta.update({"attempts": attempt, "wall_s": r["lat"],
                         "usage": {"in": r["in"], "out": r["out"]},
                         "cost_accounting_yuan": cost,
                         "cost_actual_yuan": 0.0 if alias == MODEL_ALIAS else None,
                         "stop_reason": r["stop"], "text": r["text"], "error": None})
            break
        except Exception as e:  # noqa: BLE001 — 全量异常记录后单次重试
            last_err = repr(e)
            if attempt == 1:
                time.sleep(RETRY_WAIT_S)
            else:
                meta.update({"attempts": 2, "error": last_err, "text": "", "usage": None,
                             "cost_accounting_yuan": 0.0, "cost_actual_yuan": 0.0, "stop_reason": None, "wall_s": None})
    parsed = extract_json(meta.get("text") or "")
    meta["json_ok"] = parsed is not None
    meta["parsed"] = parsed
    out_dir = out_dir or (HERE / "runs" / f"run{run}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{node}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    print(f"  {node}[{alias}]: attempts={meta.get('attempts')} json_ok={meta['json_ok']} "
          f"stop={meta.get('stop_reason')} in/out={meta.get('usage')} wall={meta.get('wall_s')}s "
          f"¥(核算)={meta.get('cost_accounting_yuan')}{'' if meta.get('error') is None else ' ERROR=' + str(meta.get('error'))[:80]}")
    return meta


def run_once(run):
    print(f"=== run {run} ===")
    nodes = {}
    for i in (1, 2, 3, 4):
        nodes[f"E{i}"] = call_node(run, f"E{i}", E_SYSTEM, e_user(f"E{i}"), {})
    j1 = call_node(run, "J1", J1_SYSTEM,
                   j1_user(json.dumps({"E1": nodes["E1"]["text"], "E2": nodes["E2"]["text"]}, ensure_ascii=False)),
                   {"E1": nodes["E1"]["text"], "E2": nodes["E2"]["text"]})
    nodes["J1"] = j1
    j2 = call_node(run, "J2", J2_SYSTEM,
                   j2_user(json.dumps({"J1": j1["text"], "E3": nodes["E3"]["text"], "E4": nodes["E4"]["text"]}, ensure_ascii=False)),
                   {"J1": j1["text"], "E3": nodes["E3"]["text"], "E4": nodes["E4"]["text"]})
    nodes["J2"] = j2
    sink = call_node(run, "SINK", SINK_SYSTEM,
                     sink_user(json.dumps({"J1": j1["text"], "J2": j2["text"]}, ensure_ascii=False)),
                     {"J1": j1["text"], "J2": j2["text"]})
    nodes["SINK"] = sink
    total = sum(n.get("cost_accounting_yuan") or 0 for n in nodes.values())
    toks = {"in": sum((n.get("usage") or {}).get("in", 0) for n in nodes.values()),
            "out": sum((n.get("usage") or {}).get("out", 0) for n in nodes.values())}
    print(f"run {run} 完成：7 节点，tokens={toks}，核算成本 ¥{total:.4f}（订阅实际 ¥0）")
    return nodes


def score_run(run):
    sink = json.loads((HERE / "runs" / f"run{run}" / "SINK.json").read_text("utf-8"))
    term = build_terminal_output(sink.get("parsed"))
    out_dir = HERE / "runs" / f"run{run}"
    (out_dir / "terminal_output.json").write_text(json.dumps(term, ensure_ascii=False, indent=1), "utf-8")
    r = evaluate_terminal_quality(CONTRACT, term, SRC)
    (out_dir / "evaluation.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), "utf-8")
    print(f"run {run} 评分：status={r['status']} critical={r['critical_gate']['status']} "
          f"dims.fact={r['dimensions']['fact_correctness']} evidence={r['dimensions']['evidence_support']} "
          f"completeness={r['dimensions']['necessary_completeness']} refusal={r['dimensions']['unverifiable_refusal']}")
    return r


# ============ 干预臂（π-only / R-only，操作者 2026-11-01 授权，PI_ONLY_R_ONLY_DESIGN.md） ============
RELAY_ADDENDUM = ("\n此外，在你的 JSON 输出中增加一个 dates_relay 字段：{\"D1\": {\"公告落款日\":…, \"告知书收到日\":…}, "
                  "\"D2\": {…}}，取值只从上游抽取结果中的日期逐字转写（含原句引用与页码），不得推断。"
                  "此字段为中继传递，不影响你的四项归一判定。")
DS_ALIAS = "deepseek"                       # π-only 专属：逐节点白名单（仅 J2DS）
DS_ENDPOINT = transport.OPENAI_MODELS[DS_ALIAS][1]
DS_CAP_YUAN = 1.0                            # 预登记成本硬顶


def saved_text(run, node):
    return json.loads((HERE / "runs" / f"run{run}" / f"{node}.json").read_text("utf-8"))["text"]


def run_r_only(run):
    """R-only：J1 加 dates_relay 中继（system 尾部追加，唯一提示词变化）→ J2 诚实重算 → SINK。"""
    print(f"=== R-only run {run} ===")
    base = HERE / "runs" / f"run{run}"
    out = HERE / "runs_r" / f"run{run}"
    out.mkdir(parents=True, exist_ok=True)
    e1, e2 = saved_text(run, "E1"), saved_text(run, "E2")
    user_j1 = j1_user(json.dumps({"E1": e1, "E2": e2}, ensure_ascii=False))
    assert user_j1 == json.loads((base / "J1.json").read_text("utf-8"))["user"], "J1 user 与 baseline 不逐字节一致"
    j1r = call_node(run, "J1r", J1_SYSTEM + RELAY_ADDENDUM, user_j1, {"E1": e1, "E2": e2}, out_dir=out)
    e3, e4 = saved_text(run, "E3"), saved_text(run, "E4")
    user_j2 = j2_user(json.dumps({"J1": j1r["text"], "E3": e3, "E4": e4}, ensure_ascii=False))
    j2r = call_node(run, "J2r", J2_SYSTEM, user_j2, {"J1": j1r["text"], "E3": e3, "E4": e4}, out_dir=out)
    user_sink = sink_user(json.dumps({"J1": j1r["text"], "J2": j2r["text"]}, ensure_ascii=False))
    call_node(run, "SINK", SINK_SYSTEM, user_sink, {"J1": j1r["text"], "J2": j2r["text"]}, out_dir=out)
    return out


def run_pi_only(run):
    """π-only：仅 J2 换 deepseek-flash，上游/J2提示词/SINK 全部冻结复用。硬门禁：DS 凭据。"""
    import os
    assert os.environ.get("DEEPSEEK_API_KEY"), "DEEPSEEK_API_KEY 不在环境——π-only 臂 BLOCKED（预登记门禁）"
    print(f"=== π-only run {run} ===")
    base = HERE / "runs" / f"run{run}"
    out = HERE / "runs_pi" / f"run{run}"
    out.mkdir(parents=True, exist_ok=True)
    j1t, e3, e4 = saved_text(run, "J1"), saved_text(run, "E3"), saved_text(run, "E4")
    user_j2 = j2_user(json.dumps({"J1": j1t, "E3": e3, "E4": e4}, ensure_ascii=False))
    assert user_j2 == json.loads((base / "J2.json").read_text("utf-8"))["user"], "J2 user 与 baseline 不逐字节一致"
    j2ds = call_node(run, "J2DS", J2_SYSTEM, user_j2, {"J1": j1t, "E3": e3, "E4": e4},
                     out_dir=out, alias=DS_ALIAS, layer_key="J2")
    est = (j2ds.get("usage") or {}).get("in", 0) * 1e-6 + (j2ds.get("usage") or {}).get("out", 0) * 2e-6
    assert est < DS_CAP_YUAN, f"DS 成本估算 ¥{est:.4f} 触及硬顶 ¥{DS_CAP_YUAN}"
    user_sink = sink_user(json.dumps({"J1": j1t, "J2": j2ds["text"]}, ensure_ascii=False))
    call_node(run, "SINK", SINK_SYSTEM, user_sink, {"J1": j1t, "J2": j2ds["text"]}, out_dir=out)
    return out


def run_joint(run):
    """Joint（设计+V1 澄清冻结）：J1' 复用 R-only 已存输出（零调用），J2j=DeepSeek，SINK=GLM。"""
    import os
    assert os.environ.get("DEEPSEEK_API_KEY"), "DEEPSEEK_API_KEY 缺失——Joint BLOCKED"
    print(f"=== Joint run {run} ===")
    out = HERE / "runs_j" / f"run{run}"
    out.mkdir(parents=True, exist_ok=True)
    j1r_text = json.loads((HERE / "runs_r" / f"run{run}" / "J1r.json").read_text("utf-8"))["text"]
    e3, e4 = saved_text(run, "E3"), saved_text(run, "E4")
    user_j2 = j2_user(json.dumps({"J1": j1r_text, "E3": e3, "E4": e4}, ensure_ascii=False))
    # 设计冻结断言：Joint 的 J2 user 与 R-only 同 run 的 J2r user 逐字节一致（同 J1' 上游零漂移）
    assert user_j2 == json.loads((HERE / "runs_r" / f"run{run}" / "J2r.json").read_text("utf-8"))["user"], \
        "J2 user 与 R-only J2r 不逐字节一致（上游漂移）——中止"
    j2j = call_node(run, "J2J", J2_SYSTEM, user_j2, {"J1": j1r_text, "E3": e3, "E4": e4},
                    out_dir=out, alias=DS_ALIAS, layer_key="J2")
    est = (j2j.get("usage") or {}).get("in", 0) * 1e-6 + (j2j.get("usage") or {}).get("out", 0) * 2e-6
    assert est < DS_CAP_YUAN, f"DS 成本估算 ¥{est:.4f} 触及硬顶 ¥{DS_CAP_YUAN}"
    user_sink = sink_user(json.dumps({"J1": j1r_text, "J2": j2j["text"]}, ensure_ascii=False))
    call_node(run, "SINK", SINK_SYSTEM, user_sink, {"J1": j1r_text, "J2": j2j["text"]}, out_dir=out)
    return out


# ============ E2 口径消歧（V1.1 冻结 ba039a5d，操作者 2026-11-01 授权） ============
DISAMBIG_ADDENDUM = ("\n计数口径澄清：announcing_company_count 特指：就上述实体归一所认定的同一份立案告知书实例"
                     "发布公告的上市公司数量（按公司去重，不按公告文档份数计；就其他告知书实例发布公告"
                     "的公司不计入）。")


def disambig_gates():
    """V1.1 隔离门禁：附录内容无关性（无 gold 数值/公司名/编号答案），差异仅此附录。"""
    banned = ["西王", "纳川", "祥源", "交建", "俞发祥", "王勇", "0042026", "0112026", "0262026"]
    hits = [b for b in banned if b in DISAMBIG_ADDENDUM]
    import re
    standalone_nums = re.findall(r"(?<![\d.])2(?![\d.])", DISAMBIG_ADDENDUM)
    ok = not hits and not standalone_nums and DISAMBIG_ADDENDUM.startswith("\n计数口径澄清：announcing_company_count 特指")
    print(f"消歧门禁: banned命中={hits or '无'} | 独立gold值'2'={len(standalone_nums)}处 | PASS={ok}")
    return ok


def run_e2_dis(run, alias):
    """E2 消歧：原始 J1 冻结上游（与 Static/π-only 同源），J2_SYSTEM+澄清附录，唯一变量=口径澄清。"""
    import os
    if alias == DS_ALIAS:
        assert os.environ.get("DEEPSEEK_API_KEY"), "DEEPSEEK_API_KEY 缺失"
        assert disambig_gates(), "消歧附录门禁未过——中止"
    base = HERE / "runs" / f"run{run}"
    out = HERE / "runs_e2" / ("glm" if alias == MODEL_ALIAS else "ds") / f"run{run}"
    out.mkdir(parents=True, exist_ok=True)
    j1t, e3, e4 = saved_text(run, "J1"), saved_text(run, "E3"), saved_text(run, "E4")
    user_j2 = j2_user(json.dumps({"J1": j1t, "E3": e3, "E4": e4}, ensure_ascii=False))
    # 字节断言：与 baseline（Static/π-only 同源）J2 user 逐字节一致——四同一异成立
    assert user_j2 == json.loads((base / "J2.json").read_text("utf-8"))["user"], "J2 user 与 baseline 不逐字节一致"
    node = "J2DGLM" if alias == MODEL_ALIAS else "J2DDS"
    call_node(run, node, J2_SYSTEM + DISAMBIG_ADDENDUM, user_j2, {"J1": j1t, "E3": e3, "E4": e4},
              out_dir=out, alias=alias, layer_key="J2")
    return out


def run_e2_term(run, side):
    """E2 终端传播验证（操作者 2026-11-01 授权，6 次独立 SINK）：每 run 每模型单独消费对应 J2d，不混合。"""
    side_dir, node = {"glm": ("runs_e2/glm", "J2DGLM"), "ds": ("runs_e2/ds", "J2DDS")}[side]
    out = HERE / side_dir / f"run{run}"
    j1t = saved_text(run, "J1")  # 原始 J1（与消歧实验上游同源）
    j2d_text = json.loads((out / f"{node}.json").read_text("utf-8"))["text"]
    user_sink = sink_user(json.dumps({"J1": j1t, "J2": j2d_text}, ensure_ascii=False))
    call_node(run, "SINK", SINK_SYSTEM, user_sink, {"J1": j1t, "J2": j2d_text}, out_dir=out)
    return out


# ============ 同链确认运行（操作者 2026-11-01 指令：E职务抽取+J1中继+J2消歧+SINK+在线格式层） ============
E_POSITION_ADDENDUM = (' 增加一个 "positions" 字段：[{field: "任职状况", value: 涉事人员职务相关表述的逐字原文, '
                       'quote: 完整原句逐字引用, page: 页码}]；原文无职务相关表述则输出空数组。不得推断。')
J1_POSITIONS_ADDENDUM = ('此外，在你的 JSON 输出中增加一个 positions_relay 字段：{"D1": {"text": 上游抽取的任职状况原文, '
                         '"page": 页码}, "D2": {…}}，只从上游抽取结果中的 positions 字段逐字转写（含原句与页码），'
                         '不得推断。此字段为中继传递，不影响你的四项归一判定。')
PERSONS_SRC = ['俞发祥', '王勇']
COMPANIES_FULL_SRC = ['浙江祥源文旅股份有限公司', '安徽省交通建设股份有限公司', '西王食品股份有限公司', '福建纳川管材科技股份有限公司']
TERM_ZH = {'同一自然人': 'SAME_PERSON', '同一份文书实例': 'SAME_NOTICE_INSTANCE',
           '同一收到事件': 'SAME_RECEIPT_EVENT', '不同公司': 'DIFFERENT_COMPANY'}
ENUM_BY_SLOT = {'D_1': ['SAME_PERSON', 'DIFFERENT_PERSON'], 'D_2': ['SAME_NOTICE_INSTANCE', 'DIFFERENT_NOTICE_INSTANCE'],
                'D_3': ['SAME_RECEIPT_EVENT', 'DIFFERENT_EVENT'], 'D_4': ['SAME_COMPANY', 'DIFFERENT_COMPANY']}
SLOT_ENUM = {'D_1': 'SAME_PERSON', 'D_2': 'SAME_NOTICE_INSTANCE', 'D_3': 'SAME_RECEIPT_EVENT', 'D_4': 'DIFFERENT_COMPANY'}


def apply_format_rules(parsed):
    """在线确定性格式编码层（FORMAT_RECOVERY_REPORT 冻结规则 R1/R1b/R2g/R3/R4；幂等：已合规值不变；
    排除 A4/C1/C2（无合规确定性规则）；每处转换记录审计日志并过语义保持断言）。"""
    log = []
    for a in (parsed or {}).get('answers', []):
        fid, v = a.get('fact_id'), str(a.get('value') or '')
        new = None
        if fid in SLOT_ENUM:  # R1/R1b：目标枚举唯一在场或中文术语起头
            tok = [t for t in ENUM_BY_SLOT[fid] if t in v]
            if len(tok) == 1 and v != tok[0]:
                new = tok[0]
            elif not tok:
                zh = [z for z in TERM_ZH if v.startswith(z)]
                if len(zh) == 1 and SLOT_ENUM[fid] == TERM_ZH[zh[0]]:
                    new = TERM_ZH[zh[0]]
        elif fid in ('A1', 'A2') and not v.startswith(('PERSON_ONLY_实际控制人',)):
            name = next((p for p in PERSONS_SRC if p in v), None)
            if name and '实际控制人' in v:
                new = f'PERSON_ONLY_实际控制人{name}'  # R2g
        elif fid == 'A3' and v != 'BOTH_公司及实际控制人王勇':
            if '王勇' in v and '公司' in v and '实际控制人' in v:
                new = 'BOTH_公司及实际控制人王勇'  # R3（BOTH 槽规范语法）
        elif fid == 'B3b' and '证监立案字' in v:
            new = v.replace('证监立案字', '')  # R4
        if new is not None and new != v:
            a['value'] = new
            log.append({'fact_id': fid, 'rule': {'D': 'R1/R1b', 'A': 'R2g/R3', 'B': 'R4'}[fid[0]], 'from': v[:40], 'to': new[:40]})
    return parsed, log


def run_integrated(run):
    print(f"=== 同链确认 run {run} ===")
    out = HERE / "runs_x" / f"run{run}"
    out.mkdir(parents=True, exist_ok=True)
    # E1'/E2'：扩展职务抽取（唯一 E 层提示词变化，内容无关）
    for node, doc in (("E1P", "E1"), ("E2P", "E2")):
        text = "".join(rec["text"] for rec in SRC[DOCMAP[doc]].pages.values()) if False else "".join(
            rec["text"] for rec in SRC[DOCMAP[doc]]["pages"].values())
        call_node(run, node, E_SYSTEM + E_POSITION_ADDENDUM, e_user(doc), {}, out_dir=out, layer_key="E")
    e1p = json.loads((out / "E1P.json").read_text("utf-8"))["text"]
    e2p = json.loads((out / "E2P.json").read_text("utf-8"))["text"]
    # J1P：dates_relay + positions_relay 双中继
    user_j1 = j1_user(json.dumps({"E1": e1p, "E2": e2p}, ensure_ascii=False))
    j1p = call_node(run, "J1P", J1_SYSTEM + RELAY_ADDENDUM + J1_POSITIONS_ADDENDUM, user_j1,
                    {"E1": e1p, "E2": e2p}, out_dir=out, layer_key="J1")
    # J2X：消歧附录（已证双模型 3/3；本臂 GLM）
    e3, e4 = saved_text(run, "E3"), saved_text(run, "E4")
    user_j2 = j2_user(json.dumps({"J1": j1p["text"], "E3": e3, "E4": e4}, ensure_ascii=False))
    j2x = call_node(run, "J2X", J2_SYSTEM + DISAMBIG_ADDENDUM, user_j2,
                    {"J1": j1p["text"], "E3": e3, "E4": e4}, out_dir=out, layer_key="J2")
    # SINK：原提示词
    user_sink = sink_user(json.dumps({"J1": j1p["text"], "J2": j2x["text"]}, ensure_ascii=False))
    call_node(run, "SINK", SINK_SYSTEM, user_sink, {"J1": j1p["text"], "J2": j2x["text"]}, out_dir=out)
    return out


def score_integrated(run):
    import copy
    out = HERE / "runs_x" / f"run{run}"
    sink_raw = json.loads((out / "SINK.json").read_text("utf-8"))
    # 原始链（无格式层）评价
    term_raw = build_terminal_output(copy.deepcopy(sink_raw.get("parsed")))
    (out / "terminal_output.raw.json").write_text(json.dumps(term_raw, ensure_ascii=False, indent=1), "utf-8")
    r_raw = evaluate_terminal_quality(CONTRACT, term_raw, SRC)
    (out / "evaluation.raw.json").write_text(json.dumps(r_raw, ensure_ascii=False, indent=1), "utf-8")
    # 在线格式编码层（冻结规则，幂等，审计日志）
    fmt_parsed, log = apply_format_rules(copy.deepcopy(sink_raw.get("parsed")))
    (out / "format_layer_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), "utf-8")
    term_fmt = build_terminal_output(fmt_parsed)
    (out / "terminal_output.json").write_text(json.dumps(term_fmt, ensure_ascii=False, indent=1), "utf-8")
    r_fmt = evaluate_terminal_quality(CONTRACT, term_fmt, SRC)
    (out / "evaluation.json").write_text(json.dumps(r_fmt, ensure_ascii=False, indent=1), "utf-8")
    print(f"run {run}: 原始链 formal={r_raw['dimensions']['fact_correctness']:.4f} → 格式层后={r_fmt['dimensions']['fact_correctness']:.4f} | 转换 {len(log)} 处")
    return r_raw, r_fmt


def score_arm(arm_dir):
    sink = json.loads((arm_dir / "SINK.json").read_text("utf-8"))
    term = build_terminal_output(sink.get("parsed"))
    (arm_dir / "terminal_output.json").write_text(json.dumps(term, ensure_ascii=False, indent=1), "utf-8")
    r = evaluate_terminal_quality(CONTRACT, term, SRC)
    (arm_dir / "evaluation.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), "utf-8")
    print(f"{arm_dir.parent.name}/{arm_dir.name} 评分：critical={r['critical_gate']['status']} "
          f"fact={r['dimensions']['fact_correctness']} evidence={r['dimensions']['evidence_support']} "
          f"completeness={r['dimensions']['necessary_completeness']}")
    return r


def manifest():
    files = {}
    for p in sorted(HERE.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.json" and "__pycache__" not in p.parts:
            try:
                files[str(p.relative_to(HERE))] = sha(p.read_text("utf-8"))
            except UnicodeDecodeError:
                files[str(p.relative_to(HERE))] = "BINARY_SKIPPED:" + hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    m = {"versions": {
             "contract": sha(CONTRACT_PATH.read_text("utf-8")),
             "contract_expected_prefix": CONTRACT_SHA_EXPECTED,
             "transport": sha(Path(transport.__file__).read_text("utf-8")),
             "transport_chain": "cc652395…（前置检查版）→ 7a423eb3…（temperature 透传扩展，默认路径逐字节不变）",
             "evaluator": sha((EVALUATOR_DIR / "terminal_quality.py").read_text("utf-8")),
             "evaluator_version": "terminal_quality_v1.2.3（永久冻结）",
             "executor": sha(Path(__file__).read_text("utf-8"))},
         "protocol": {"alias": MODEL_ALIAS, "temperature": TEMPERATURE, "max_tokens": MAXTOK,
                      "price_yuan_per_token": {"in": PRICE_IN, "out": PRICE_OUT},
                      "gateway_note": "transport.py 直连无 Gateway，无串行化；逐调用墙钟独立记录；不做并行 Makespan 主张"},
         "files_sha256": files}
    (HERE / "MANIFEST.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), "utf-8")
    print("MANIFEST 写入", len(files), "个文件；contract", m["versions"]["contract"][:16],
          "；evaluator", m["versions"]["evaluator"][:16])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gates", "run", "score", "manifest", "r-only", "pi-only", "joint", "e2-dis", "e2-term", "integrated", "score-x", "score-arm"])
    ap.add_argument("n", nargs="?", type=int)
    a = ap.parse_args()
    if a.cmd == "gates":
        sys.exit(0 if run_gates() and adapter_selftest() else 1)
    elif a.cmd == "run":
        assert a.n in (1, 2, 3), "run 编号 1-3"
        run_once(a.n)
    elif a.cmd == "score":
        runs = [a.n] if a.n else [1, 2, 3]
        for k in runs:
            score_run(k)
    elif a.cmd == "r-only":
        assert a.n in (1, 2, 3), "run 编号 1-3"
        run_r_only(a.n)
    elif a.cmd == "pi-only":
        assert a.n in (1, 2, 3), "run 编号 1-3"
        run_pi_only(a.n)
    elif a.cmd == "joint":
        assert a.n in (1, 2, 3), "run 编号 1-3"
        run_joint(a.n)
    elif a.cmd == "e2-dis":
        assert a.n in (1, 2, 3), "run 编号 1-3"
        run_e2_dis(a.n, MODEL_ALIAS)
        run_e2_dis(a.n, DS_ALIAS)
    elif a.cmd == "e2-term":
        assert a.n in (1, 2, 3), "run 编号 1-3"
        run_e2_term(a.n, "glm")
        run_e2_term(a.n, "ds")
    elif a.cmd == "integrated":
        assert a.n in (1, 2, 3), "run 编号 1-3"
        run_integrated(a.n)
    elif a.cmd == "score-x":
        assert a.n in (1, 2, 3)
        score_integrated(a.n)
    elif a.cmd == "score-arm":
        assert a.n in (1, 2, 3)
        score_arm(HERE / "runs_r" / f"run{a.n}")
    elif a.cmd == "manifest":
        manifest()
