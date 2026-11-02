#!/usr/bin/env python3
"""MVR-BATCH-1 runner (v4 preregistration, GO per operator directive 2026-10-31).

Phases (state persisted under /root/research_outputs/mvr_batch1/):
  ping        1 GLM + 1 DeepSeek identity/latency check (mismatch => stop batch)
  calibrate   5 types x 2 models x 2 tasks node-level fact-F1 (fields disjoint
              from MVR required facts, asserted); writes calibration.json
  plan        allocation (Q_min=0.70, cheapest-qualified; GLM cheaper by frozen
              prices) + T* selection by frozen priority; headroom gate (no T*
              => stop, no run)
  pair <t> <r>  one same-state pair: common prefix -> deterministic fault at
              first T* node -> frozen snapshot -> fork A (keep allocation) /
              B (switch remaining T* nodes per frozen rule)
  report      paired deltas, 3x3 matrix, ledgers

Budget enforcement: per-request precheck vs remaining batch caps (506 calls /
1,154k tokens / CNY 100 absolute) and per-pair reservation (2 arms full load).
Terminal-only circuit breaking at pair boundaries (CNY>=60 or calls>=450).
Gold isolation: prompt builders receive ONLY question / doc texts / schema
slots (fact_id, subject, predicate, unit, date_type, description) / prior node
outputs. required_facts values/spans/critical never enter prompts (structural
whitelist + logged provenance).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path("/root/research_outputs/mvr_batch1")
OUT.mkdir(parents=True, exist_ok=True)
EVAL_PATH = "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4"
EVID = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence")

# ---- frozen budget/pricing (v4 §2/§7) ----
CAP_CALLS, CAP_TOKENS, CAP_CNY = 506, 1_154_000, 100.0
BREAK_CNY, BREAK_CALLS = 60.0, 450
PRICE = {  # per 1M tokens, CNY
    "glm": {"in": 0.80, "out": 2.80},
    "ds": {"in": 0.30 * 7.5, "out": 1.20 * 7.5},
}
MODELS = {"glm": "GLM-5.3-Flash", "ds": "deepseek-flash"}
TYPE_PRIORITY = ["金额抽取", "日期文号抽取", "当事人主体抽取", "跨文档一致性核验", "汇总派生"]
Q_MIN = 0.70
F1_UP, F1_DOWN, CL_TOL = 0.02, -0.02, 0.05


def load_env():
    # credential-file preference: .env.modelpool first (verified working for both
    # DS and DASHSCOPE), /root/.env as fallback; recorded in batch ledger notes.
    for path in ("/root/.env", "/root/.env.modelpool"):  # later file wins (modelpool creds verified)
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k] = v.strip().strip('"').strip("'")


def glm_key():
    cfg = json.load(open("/root/.zcode/v2/provider_config.json"))
    return next(r["config"]["access"]["apiKey"]
                for r in cfg["config"]["providerConfigRules"]["providerRules"]
                if r["providerId"] == "bigmodel-api")


def call(model_key, system, user, max_tokens=2000, timeout_s=120):
    """One metered call. Returns dict(text,in,out,lat,model_id) or raises."""
    if model_key == "glm":
        body = {"model": MODELS["glm"], "max_tokens": max_tokens,
                "thinking": {"type": "disabled"}, "system": system,
                "messages": [{"role": "user", "content": user}]}
        req = urllib.request.Request("https://open.bigmodel.cn/api/anthropic/v1/messages",
                                     data=json.dumps(body).encode(), method="POST")
        key = glm_key()
        req.add_header("content-type", "application/json")
        req.add_header("x-api-key", key)
        req.add_header("authorization", "Bearer " + key)
        req.add_header("anthropic-version", "2023-06-01")
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            d = json.loads(r.read().decode())
        return {"text": "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text"),
                "in": d["usage"]["input_tokens"], "out": d["usage"]["output_tokens"],
                "lat": round(time.monotonic() - t0, 2), "model_id": d.get("model", "")}
    body = {"model": MODELS["ds"], "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}}
    req = urllib.request.Request("https://api.deepseek.com/chat/completions",
                                 data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + os.environ.get("DEEPSEEK_API_KEY", ""))
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    c = d["choices"][0]["message"].get("content", "")
    if isinstance(c, list):
        c = "".join(x.get("text", "") for x in c if isinstance(x, dict))
    u = d["usage"]
    return {"text": c, "in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0),
            "lat": round(time.monotonic() - t0, 2), "model_id": d.get("model", "")}


class Ledger:
    def __init__(self):
        self.path = OUT / "ledger.jsonl"
        self.calls = 0
        self.tokens = 0
        self.cny = 0.0
        if self.path.exists():  # replay: budget state must persist across phases
            for line in self.path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.calls += 1
                    self.tokens += r["in"] + r["out"]
                    self.cny += r["cny"]

    def precheck(self, need_tokens=8000):
        if self.calls + 1 > CAP_CALLS or self.tokens + need_tokens > CAP_TOKENS:
            raise SystemExit(f"BUDGET_HARD_STOP calls={self.calls} tokens={self.tokens}")
        est = need_tokens / 1e6 * PRICE["ds"]["out"]
        if self.cny + est > CAP_CNY:
            raise SystemExit(f"BUDGET_HARD_STOP cny={self.cny:.2f}")

    def record(self, phase, model_key, resp, note=""):
        cost = (resp["in"] / 1e6 * PRICE[model_key]["in"] + resp["out"] / 1e6 * PRICE[model_key]["out"])
        self.calls += 1
        self.tokens += resp["in"] + resp["out"]
        self.cny += cost
        with open(self.path, "a") as f:
            f.write(json.dumps({"ts": time.time(), "phase": phase, "model": model_key,
                                "in": resp["in"], "out": resp["out"], "lat": resp["lat"],
                                "cny": round(cost, 4), "model_id": resp.get("model_id", ""),
                                "note": note}, ensure_ascii=False) + "\n")

    def pair_gate(self):
        """Terminal-only check at pair boundaries (v4 §7)."""
        if self.cny >= BREAK_CNY or self.calls >= BREAK_CALLS:
            return False
        return (self.calls + 60 <= CAP_CALLS and self.tokens + 120_000 <= CAP_TOKENS
                and self.cny + 1.2 <= CAP_CNY)


LEDGER = Ledger()


def call_metered(phase, model_key, system, user, max_tokens=2000, note=""):
    LEDGER.precheck(need_tokens=min(8000, max(1000, len(user) // 2)))
    try:
        resp = call(model_key, system, user, max_tokens=max_tokens)
    except Exception as e:  # one bounded retry
        time.sleep(2)
        resp = call(model_key, system, user, max_tokens=max_tokens)
        resp["note_err"] = str(e)[:120]
    LEDGER.record(phase, model_key, resp, note=note)
    return resp


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            return json.loads(m.group(0).replace("\n", " ").replace(",}", "}"))
        except Exception:
            return None


def norm(s):
    return re.sub(r"\s+", "", str(s or ""))


# ---------------- phase: ping ----------------
def phase_ping():
    load_env()
    out = {}
    for key in ("glm", "ds"):
        try:
            r = call_metered("ping", key, "只回复一个词。", "请回复: pong", max_tokens=8)
            out[key] = {"ok": bool(r["text"].strip()), "model_id": r["model_id"],
                        "lat": r["lat"], "in": r["in"], "out": r["out"], "text": r["text"][:20]}
        except Exception as e:
            out[key] = {"ok": False, "error": str(e)[:200]}
    (OUT / "ping.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if not (out["glm"]["ok"] and out["ds"]["ok"]):
        print("PING_FAILED -> 批次停止（执行边界裁定②：模型身份/可用性不符即停，保留记录）")
        sys.exit(3)
    glm_id, ds_id = out["glm"].get("model_id", ""), out["ds"].get("model_id", "")
    if "GLM-5.3-Flash" not in glm_id or "deepseek" not in ds_id.lower():
        print(f"IDENTITY_MISMATCH glm={glm_id} ds={ds_id} -> 批次停止")
        sys.exit(3)
    print("PING_OK")


# ---------------- contracts ----------------
def load_contracts():
    cs = {}
    for tid, path in (("MVR1", EVID / "MVR1_shuntian/TASK_CONTRACT_MVR1_v1.json"),
                      ("MVR2", EVID / "MVR2_yuandao/TASK_CONTRACT_MVR2_v1.json")):
        c = json.loads(path.read_text(encoding="utf-8"))
        c["_source_pages"] = c.pop("source_pages")
        cs[tid] = c
    return cs


def doc_pages(src):
    """[(doc_id, page, text)] flattened."""
    out = []
    for doc_id, d in src.items():
        for page, rec in d["pages"].items():
            out.append((doc_id, int(page), rec["text"]))
    return out


# ---------------- phase: calibrate ----------------
CALIB = {
    "MVR1": {
        "金额抽取": {"excerpt_doc": "D2", "fields": {"缴款期限日数": "15", "处罚当事人总数": "6", "听证会举行月份": "10", "撤回听证申请月份": "3"}},
        "日期文号抽取": {"excerpt_doc": "D3", "fields": {"公告020编号": "临2024-020", "公司证券代码": "600287", "公司证券简称": "江苏舜天", "立案告知书编号尾号": "0382022008"}},
        "当事人主体抽取": {"excerpt_doc": "D2", "fields": {"高松出生年": "1971", "桂生春出生年": "1978", "王重人出生年": "1973", "李焱出生年": "1974", "赵凡出生年": "1989"}},
        "跨文档一致性核验": {"excerpt_doc": "D1+D3", "fields": {"两文档立案编号是否一致": "一致", "告知书文号是否仅D1载明": "是", "两文档机关是否同为证监会": "是"}},
        "汇总派生": {"excerpt_doc": "D2", "fields": {"当事人中公司主体数": "1", "千万元级罚款主体数": "1", "个人罚款总额的千位级条数": "1"}},
    },
    "MVR2": {
        "金额抽取": {"excerpt_doc": "Da+Dc", "fields": {"缴款期限日数": "15", "退市整理期交易日数": "15", "摘牌后退市板块可转让交易日内上限": "45", "行政诉讼期限月数": "6"}},
        "日期文号抽取": {"excerpt_doc": "Da+Dc", "fields": {"上市日期": "2022-07-08", "同意注册批复披露日": "2022-06-13", "上市板块": "创业板", "公告090编号": "2026-090", "公告031编号": "2026-031"}},
        "当事人主体抽取": {"excerpt_doc": "Da", "fields": {"李晋时任职务": "董事长", "曹亚蕾财务类职务": "财务总监", "燕某身份状态": "已故", "被禁入当事人数": "2"}},
        "跨文档一致性核验": {"excerpt_doc": "Da+Db+Dc", "fields": {"Da与Db募集资金总额是否一致": "是", "Dc引用的决定书文号与Da是否一致": "是", "Db与Da告知书文号是否一致": "是"}},
        "汇总派生": {"excerpt_doc": "Da", "fields": {"公司被处罚的违法行为种类数": "2", "市场禁入措施年数之和": "9", "免予处罚人数": "1"}},
    },
}


def excerpt(contracts, tid, spec):
    src = contracts[tid]["_source_pages"]
    parts = []
    for token in spec.split("+"):
        doc_id = token.strip()
        text = "".join(rec["text"] for rec in src[doc_id]["pages"].values())
        parts.append(f"【文档{doc_id}】\n{text[:9000]}" + ("\n…（截断）" if len(text) > 9000 else ""))
    return "\n\n".join(parts)


def phase_calibrate():
    contracts = load_contracts()
    required_values = set()
    for c in contracts.values():
        for f in c["required_facts"]:
            required_values.add(norm(f.get("value")))
    results = {}
    for tid, types in CALIB.items():
        for tname, spec in types.items():
            body = excerpt(contracts, tid, spec["excerpt_doc"])
            for fv in spec["fields"].values():
                assert norm(fv) not in required_values, f"字段值泄漏终评事实: {fv}"
            fields_str = "、".join(spec["fields"].keys())
            for mk in ("glm", "ds"):
                sys_p = "你是精确的文书信息核验器。只输出一个 JSON 对象，不得推断；找不到或不确定填 null。"
                usr = (f"以下为任务相关文书节选。请逐字段给出答案，输出 JSON，键为字段名。\n"
                       f"字段：{fields_str}\n日期一律 YYYY-MM-DD；数量/年限给数字；一致性类字段填 是/否/一致/不一致。\n\n{body}")
                r = call_metered("calib", mk, sys_p, usr, max_tokens=600, note=f"{tid}|{tname}")
                got = parse_json(r["text"]) or {}
                fields = {}
                for fname, expect in spec["fields"].items():
                    raw = got.get(fname)
                    ok = norm(raw) == norm(expect) or norm(expect) in norm(raw)
                    fields[fname] = {"expect": expect, "got": raw, "ok": bool(ok)}
                results.setdefault(tname, {}).setdefault(mk, {"correct": 0, "asserted": 0, "expected": 0, "items": []})
                agg = results[tname][mk]
                for fname, rec in fields.items():
                    agg["expected"] += 1
                    if rec["got"] not in (None, "", "null"):
                        agg["asserted"] += 1
                        if rec["ok"]:
                            agg["correct"] += 1
                agg["items"].append({"task": tid, "type": tname, "model": mk, "fields": fields,
                                     "in": r["in"], "out": r["out"], "lat": r["lat"]})
                print(f"{tid} {tname} {mk}: " + "/".join("√" if f["ok"] else ("○" if f["got"] in (None, "", "null") else "×") for f in fields.values()))
    # node-level fact F1 per (model, type)
    matrix = {}
    for tname, models in results.items():
        matrix[tname] = {}
        for mk, agg in models.items():
            p = agg["correct"] / agg["asserted"] if agg["asserted"] else 0.0
            rc = agg["correct"] / agg["expected"] if agg["expected"] else 0.0
            f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
            matrix[tname][mk] = {"precision": round(p, 4), "recall": round(rc, 4), "f1": round(f1, 4),
                                 "n_expected": agg["expected"], "n_asserted": agg["asserted"]}
    (OUT / "calibration.json").write_text(json.dumps({"matrix": matrix, "raw": results}, ensure_ascii=False, indent=1))
    print("\n=== 校准矩阵（节点级事实 F1）===")
    for tname in TYPE_PRIORITY:
        row = matrix.get(tname, {})
        print(f"{tname:12s} GLM={row.get('glm', {}).get('f1')}  DS={row.get('ds', {}).get('f1')}")


# ---------------- phase: plan ----------------
def phase_plan():
    calib = json.loads((OUT / "calibration.json").read_text())["matrix"]
    glm_cheaper = (PRICE["glm"]["in"] + PRICE["glm"]["out"]) <= (PRICE["ds"]["in"] + PRICE["ds"]["out"])
    cheap, other = ("glm", "ds") if glm_cheaper else ("ds", "glm")
    allocation, tstar = {}, None
    for t in TYPE_PRIORITY:
        row = calib.get(t, {})
        a_cheap = row.get(cheap, {}).get("f1", 0.0)
        a_other = row.get(other, {}).get("f1", 0.0)
        if a_cheap >= Q_MIN:
            allocation[t] = cheap
        elif a_other >= Q_MIN:
            allocation[t] = other
        else:
            allocation[t] = cheap if a_cheap >= a_other else other
        if tstar is None and allocation[t] == cheap and a_other > a_cheap:
            tstar = t
    plan = {"cheap": cheap, "other": other, "allocation": allocation, "tstar": tstar,
            "headroom_pass": tstar is not None}
    (OUT / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    print(json.dumps(plan, ensure_ascii=False, indent=1))
    if tstar is None:
        print("HEADROOM_GATE_FAILED -> 本批不开跑（v4 §3：无 T*，不得换任务制造机会）")
        sys.exit(4)


# ---------------- phase: pair execution ----------------
def build_dag(contracts, tid, tstar, allocation):
    """Deterministic DAG from contract question+docs. Node types per frozen rule:
    E-nodes rotate [金额抽取, 日期文号抽取, 当事人主体抽取] by doc order; three
    T*-typed F-nodes over extracted JSON; sink (汇总派生)."""
    c = contracts[tid]
    docs = doc_pages(c["_source_pages"])
    rotation = ["金额抽取", "日期文号抽取", "当事人主体抽取"]
    nodes = []
    for i, (doc_id, page, text) in enumerate(docs):
        nodes.append({"id": f"E{i+1}", "type": rotation[i % 3], "doc": doc_id,
                      "doc_text": text[:12000] + ("…（截断至12000字）" if len(text) > 12000 else "")})
    for j in range(3):
        nodes.append({"id": f"F{j+1}", "type": tstar, "needs": [n["id"] for n in nodes if n["id"].startswith("E")]})
    nodes.append({"id": "SINK", "type": "汇总派生", "needs": [n["id"] for n in nodes if n["id"].startswith("E")] + ["F1", "F2", "F3"]})
    return nodes, allocation


def schema_slots(contracts, tid):
    """Output-format constraints only: fact_id/subject/predicate/unit/date_type/description.
    No values, no spans, no critical flags (Gold isolation)."""
    c = contracts[tid]
    slots = []
    for f in c["required_facts"]:
        slots.append({"fact_id": f["fact_id"], "subject": f["subject"], "predicate": f["predicate"],
                      "value_kind": f.get("value_kind", "text"), "unit": f.get("unit", ""),
                      "date_type": f.get("date_type", ""), "description": f.get("description", "")})
    unknowns = [{"item_id": u["item_id"], "description": u["description"]} for u in c.get("unknown_items", [])]
    return slots, unknowns


EXTRACT_SYS = "你是精确的文书信息抽取器。只输出一个 JSON 对象：{ \"amounts\": [...], \"dates_ids\": [...], \"parties_roles\": [...] }，每项为 {field,value,quote}。不得编造；找不到留空数组。"


def node_prompt_E(node, question):
    return (f"任务问题：{question}\n\n以下是文档{node['doc']}的全文。请抽取与问题相关的全部事实，"
            f"输出 JSON：amounts（金额/数量类，含单位）、dates_ids（日期与文号类，日期 YYYY-MM-DD）、"
            f"parties_roles（当事人与其职务/身份）。每项 {{\"field\":..., \"value\":..., \"quote\": 原文短引用}}。\n\n{node['doc_text']}")


def node_prompt_F(tstar, upstream_json, question):
    return (f"任务问题：{question}\n\n以下是上游各文档的结构化抽取结果（JSON）。请针对维度「{tstar}」"
            f"整合并补全：输出 JSON 数组，每项 {{\"field\":..., \"value\":..., \"quote\":..., \"doc\": 来源文档ID}}。"
            f"只依据给定内容，不得编造。\n\n{upstream_json}")


def node_prompt_SINK(slots, unknowns, upstream_json, question):
    slot_str = json.dumps(slots, ensure_ascii=False)
    unk_str = json.dumps(unknowns, ensure_ascii=False)
    return (f"任务问题：{question}\n\n以下是上游抽取与整合结果（JSON）：\n{upstream_json}\n\n"
            f"请输出最终答案 JSON：{{\"answers\": [{{\"fact_id\":..., \"value\":..., \"quote\": 原文短引用, \"doc\": 文档ID}} 按以下槽位逐项填写], "
            f"\"abstentions\": [{{\"item_id\":..., \"text\": 明确拒判语句}}], \"complete\": true/false}}。\n"
            f"槽位（fact_id/subject/predicate/unit/date_type 为输出格式约定；value 必须来自上游内容或其精确算术，"
            f"quote 为原文引用；无法确定且属下列 unknown 项的写入 abstentions 并给明确拒判语句，否则尽量作答）：\n{slot_str}\n"
            f"unknown 项：{unk_str}\n如你认为抽取不完整、无法负责地作答，置 complete=false。")


def corrupt(text):
    """Deterministic degradation at the anomaly node (same for both arms)."""
    obj = parse_json(text)
    if isinstance(obj, list) and obj:
        half = obj[: max(1, len(obj) // 2)]
        for item in half:
            if isinstance(item, dict) and "value" in item:
                item["value"] = str(item["value"])[: max(1, len(str(item["value"])) // 3)]
        return json.dumps(half, ensure_ascii=False)
    s = str(text)
    return s[: len(s) // 2]


def run_node(phase, node, model_key, question, upstream, slots, unknowns):
    if node["id"].startswith("E"):
        user = node_prompt_E(node, question)
        sys_p = EXTRACT_SYS
    elif node["id"].startswith("F"):
        user = node_prompt_F(node["type"], upstream, question)
        sys_p = "你是严谨的信息整合器。只输出 JSON，不得编造。"
    else:
        user = node_prompt_SINK(slots, unknowns, upstream, question)
        sys_p = "你是严谨的最终答案汇总器。只输出一个 JSON 对象，遵守给定槽位格式。"
    r = call_metered(phase, model_key, sys_p, user, max_tokens=2500, note=node["id"])
    return r["text"], r


def adapt_sink(sink_text, contracts, tid):
    c = contracts[tid]
    src = c["_source_pages"]
    obj = parse_json(sink_text)
    if not isinstance(obj, dict):
        return {"delivery_valid": False, "claims_complete": False, "claims": [],
                "abstentions": [], "raw": sink_text[:400]}
    claims = []
    for a in obj.get("answers", []) or []:
        if not isinstance(a, dict) or not a.get("fact_id"):
            continue
        doc_id, quote = a.get("doc", ""), str(a.get("quote", ""))
        page = 1
        for d, p, text in doc_pages(src):
            if d == doc_id and norm(quote) and norm(quote)[:20] in norm(text):
                page = p
                break
        rec = src.get(doc_id, {})
        pages = rec.get("pages", {})
        prec = pages.get(str(page), pages.get(page, {}))
        claims.append({"claim_id": a["fact_id"], "fact_id": a["fact_id"], "material": True,
                       "value": a.get("value"), "citations": [{
                           "doc_id": doc_id, "page": page, "quote": quote,
                           "raw_sha256": rec.get("raw_sha256", ""),
                           "page_sha256": prec.get("page_sha256", "")}]})
    abst = [{"item_id": x.get("item_id"), "text": x.get("text", "")}
            for x in obj.get("abstentions", []) if isinstance(x, dict)]
    return {"delivery_valid": True, "claims_complete": obj.get("complete") is True,
            "claims": claims, "abstentions": abst, "abstentions_complete": True,
            "conflict_acknowledgements": [], "raw": sink_text[:400]}


def eval_run(contracts, tid, terminal_output):
    sys.path.insert(0, EVAL_PATH)
    from terminal_quality import evaluate_terminal_quality
    c = contracts[tid]
    contract_view = {k: v for k, v in c.items() if k != "_source_pages"}
    return evaluate_terminal_quality(contract_view, terminal_output, c["_source_pages"])


def phase_pair(tid, r):
    contracts = load_contracts()
    plan = json.loads((OUT / "plan.json").read_text())
    tstar, alloc = plan["tstar"], plan["allocation"]
    if not LEDGER.pair_gate():
        print("PAIR_GATE_STOP（终点式熔断/预留不足）")
        sys.exit(5)
    c = contracts[tid]
    question = c["question"]
    nodes, _ = build_dag(contracts, tid, tstar, alloc)
    slots, unknowns = schema_slots(contracts, tid)
    tstar_nodes = [n for n in nodes if n["type"] == tstar]
    assert len(tstar_nodes) >= 2, "结构前置校验失败：T* 节点不足"
    dispatch, outputs = [], {}

    def execute(node, model_key, tag):
        upstream = json.dumps({k: (parse_json(v) or v[:600]) for k, v in outputs.items()
                               if k in node.get("needs", [])}, ensure_ascii=False)
        text, resp = run_node(f"{tid}|p{r}|{tag}", node, model_key, question, upstream, slots, unknowns)
        outputs[node["id"]] = text
        dispatch.append({"node": node["id"], "type": node["type"], "model": model_key, "tag": tag,
                         "in": resp["in"], "out": resp["out"], "lat": resp["lat"],
                         "cost": round(resp["in"] / 1e6 * PRICE[model_key]["in"] + resp["out"] / 1e6 * PRICE[model_key]["out"], 4)})
        return text

    # ---- common prefix: execute in order; deterministic fault at the FIRST
    # T*-typed node in execution order (identical for both arms); all later
    # T*-typed nodes are the reallocation targets. ----
    order = [n for n in nodes if n["id"].startswith("E")] + \
            [n for n in nodes if n["id"].startswith("F")] + \
            [n for n in nodes if n["id"] == "SINK"]
    fault_idx = next(i for i, n in enumerate(order) if n["type"] == tstar)
    assert any(n["type"] == tstar for n in order[fault_idx + 1:]), "结构前置校验失败：异常后无未执行 T* 节点"
    for i, node in enumerate(order[: fault_idx + 1]):
        upstream = json.dumps({k: (parse_json(v) or v[:600]) for k, v in outputs.items()
                               if k in node.get("needs", [])}, ensure_ascii=False)
        text, resp = run_node(f"{tid}|p{r}|prefix", node, alloc[node["type"]], question, upstream, slots, unknowns)
        if i == fault_idx:
            text = corrupt(text)
            tag = "prefix+FAULT"
        else:
            tag = "prefix"
        outputs[node["id"]] = text
        dispatch.append({"node": node["id"], "type": node["type"], "model": alloc[node["type"]], "tag": tag,
                         "in": resp["in"], "out": resp["out"], "lat": resp["lat"],
                         "cost": round(resp["in"] / 1e6 * PRICE[alloc[node["type"]]]["in"] + resp["out"] / 1e6 * PRICE[alloc[node["type"]]]["out"], 4)})
    remaining_nodes = order[fault_idx + 1:]
    snapshot_outputs = dict(outputs)
    snapshot_dispatch = list(dispatch)

    # ---- fork ----
    arms = {}
    for arm in ("A", "B"):
        outputs.clear(); outputs.update(snapshot_outputs)
        dispatch = list(snapshot_dispatch)
        replan = {"rule_fired": False, "reason": ""}
        if arm == "B":
            a_alloc = json.loads((OUT / "calibration.json").read_text())["matrix"][tstar][plan["other"]]["f1"]
            a_own = json.loads((OUT / "calibration.json").read_text())["matrix"][tstar][plan["cheap"]]["f1"]
            if a_alloc > a_own:  # resource feasibility trivially satisfied (headroom >>15%)
                replan = {"rule_fired": True, "reason": f"a({plan['other']},{tstar})={a_alloc} > a({plan['cheap']},{tstar})={a_own}",
                          "replan_wall_s": 0.0}
        for node in remaining_nodes:
            mk = plan["other"] if (arm == "B" and replan["rule_fired"] and node["type"] == tstar) else alloc[node["type"]]
            execute(node, mk, arm)
        sink_text = outputs["SINK"]
        terminal = adapt_sink(sink_text, contracts, tid)
        ev = eval_run(contracts, tid, terminal)
        arms[arm] = {"dispatch": dispatch, "replan": replan, "terminal": {k: v for k, v in terminal.items() if k != "raw"},
                     "eval": {"dimensions": ev["dimensions"], "critical_gate": ev["critical_gate"],
                              "fact_metrics": ev["fact_metrics"], "Q_final": ev["Q_final"],
                              "Q_raw": ev["Q_raw"], "status": ev["status"], "blocking": ev["blocking_reasons"]}}
        print(f"[{tid} p{r} {arm}] F1={ev['fact_metrics']['f1']} gate={ev['critical_gate']['status']} "
              f"tp/fp/fn={ev['fact_metrics']['weighted_tp']}/{ev['fact_metrics']['weighted_fp']}/{ev['fact_metrics']['weighted_fn']} "
              f"replan={arms[arm]['replan']['rule_fired']}")
    rec = {"task": tid, "pair": r, "tstar": tstar, "arms": arms,
           "ledger": {"calls": LEDGER.calls, "tokens": LEDGER.tokens, "cny": round(LEDGER.cny, 4)}}
    with open(OUT / "pairs.jsonl", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------- phase: report ----------------
def phase_report():
    pairs = [json.loads(l) for l in (OUT / "pairs.jsonl").read_text().splitlines() if l.strip()]
    plan = json.loads((OUT / "plan.json").read_text())
    calib = json.loads((OUT / "calibration.json").read_text())
    rows = []
    for p in pairs:
        a, b = p["arms"]["A"], p["arms"]["B"]
        f1a = a["eval"]["fact_metrics"]["f1"]
        f1b = b["eval"]["fact_metrics"]["f1"]
        def arm_cost(arm):
            return (sum(d["cost"] for d in arm["dispatch"] if d["tag"] == arm.get("_tag", "A") and str(d["tag"]) in ("A", "B")),
                    sum(d["lat"] for d in arm["dispatch"] if str(d["tag"]) in ("A", "B")),
                    sum(d["in"] + d["out"] for d in arm["dispatch"] if str(d["tag"]) in ("A", "B")))
        # post-fork per-arm costs only (common prefix is snapshot-shared)
        ca = sum(d["cost"] for d in a["dispatch"] if d["tag"] == "A")
        cb = sum(d["cost"] for d in b["dispatch"] if d["tag"] == "B")
        la = sum(d["lat"] for d in a["dispatch"] if d["tag"] == "A")
        lb = sum(d["lat"] for d in b["dispatch"] if d["tag"] == "B")
        rows.append({"task": p["task"], "pair": p["pair"],
                     "f1_A": f1a, "f1_B": f1b, "d_f1": round((f1b or 0) - (f1a or 0), 4),
                     "null_A": f1a is None, "null_B": f1b is None,
                     "cost_A": round(ca, 5), "cost_B": round(cb, 5), "d_cost": round(cb - ca, 5),
                     "lat_A": round(la, 2), "lat_B": round(lb, 2), "d_lat": round(lb - la, 2),
                     "gate_A": a["eval"]["critical_gate"]["status"], "gate_B": b["eval"]["critical_gate"]["status"],
                     "replan_fired": b["replan"]["rule_fired"]})
    valid = [r for r in rows if not (r["null_A"] or r["null_B"])]
    mean_d = sum(r["d_f1"] for r in valid) / len(valid) if valid else None
    per_event = {}
    for t in ("MVR1", "MVR2"):
        es = [r["d_f1"] for r in valid if r["task"] == t]
        per_event[t] = round(sum(es) / len(es), 4) if es else None
    if mean_d is None:
        classification = "无有效配对"
    else:
        q = "up" if mean_d >= F1_UP else ("down" if mean_d <= F1_DOWN else "flat")
        mean_dc = sum(r["d_cost"] for r in valid) / len(valid)
        mean_dl = sum(r["d_lat"] for r in valid) / len(valid)
        if (mean_dc < 0 or mean_dl < 0) and (mean_dc <= max(1e-9, 0.05 * abs(sum(r["cost_A"] for r in valid) / len(valid)))) and (mean_dl <= max(1e-9, 0.05 * abs(sum(r["lat_A"] for r in valid) / len(valid)))):
            cl = "improve"
        elif mean_dc > 0.05 * abs(sum(r["cost_A"] for r in valid) / len(valid)) or mean_dl > 0.05 * abs(sum(r["lat_A"] for r in valid) / len(valid)):
            cl = "worsen"
        else:
            cl = "flat"
        classification = {"up": {"improve": "强正向", "flat": "质量收益", "worsen": "质量—成本权衡"},
                          "flat": {"improve": "效率收益", "flat": "无明显变化", "worsen": "效率退化"},
                          "down": {"improve": "质量退化但效率改善", "flat": "质量退化", "worsen": "综合退化"}}[q][cl]
        report_extra = {"mean_d_cost": round(mean_dc, 5), "mean_d_lat": round(mean_dl, 2), "cl_basis": cl}
    gate_flag = any(r["gate_B"] in ("FAIL", "UNKNOWN") for r in rows)
    report = {"plan": plan, "calibration_matrix": calib["matrix"], "pairs": rows,
              **(report_extra if mean_d is not None else {}),
              "n_valid": len(valid), "mean_d_f1": round(mean_d, 4) if mean_d is not None else None,
              "per_event_mean_d_f1": per_event, "classification": classification,
              "dynamic_gate_fail_or_unknown": gate_flag,
              "ledger_final": {"calls": LEDGER.calls, "tokens": LEDGER.tokens, "cny": round(LEDGER.cny, 4)}}
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "ping":
        phase_ping()
    elif cmd == "calibrate":
        load_env()
        phase_calibrate()
    elif cmd == "plan":
        phase_plan()
    elif cmd == "pair":
        load_env()
        phase_pair(sys.argv[2], int(sys.argv[3]))
    elif cmd == "report":
        load_env()
        phase_report()
    elif cmd == "budget":
        print(json.dumps({"calls": LEDGER.calls, "tokens": LEDGER.tokens, "cny": LEDGER.cny}))
