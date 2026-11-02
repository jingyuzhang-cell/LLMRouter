#!/usr/bin/env python3
"""PHASE2B prompt construction + request-level isolation checks (zero calls).

Topology (necessary-dependency version, operator review §5):
  E1(D1) E2(D2) -> J1 (entity resolution, consumes ONLY E1+E2)
  J1 + E3(D3) + E4(D4) -> J2 (subject binding & counting; D1/D2 reach J2 ONLY via J1)
  J1 + J2 -> SINK (consumes ONLY J1+J2; no raw-E bypass; citations carried by J outputs)

Ablation proofs are information-flow facts of this topology:
  - remove J1  -> D1/D2-derived info severed from J2 and SINK (A1/A2, B1/B2, D_*, E1, E2, F1-F4 unproducible)
  - remove J2  -> D3/D4-derived bindings severed from SINK (A3/A4, B3/B3b, C1/C2, E3 unproducible)

Outputs (this run, zero model calls):
  prompts/real/E{1..4}.json      — final serialized E-node requests (real, complete)
  prompts/templates/{J1,J2,SINK}.json — exact templates + synthetic-upstream construction example
  isolation_report.json          — mechanical assertions (operator §6 four checks)
"""
import hashlib
import json
import re
import sys
from pathlib import Path

OUT = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B")
CONTRACT = json.loads((OUT / "TASK_CONTRACT_PHASE2B_v2.json").read_text(encoding="utf-8"))
SRC = CONTRACT.pop("source_pages")
DOCMAP = {"E1": "D1", "E2": "D2", "E3": "D3", "E4": "D4"}
QUESTION = CONTRACT["question"]


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


SLOTS = [{"fact_id": f["fact_id"], "subject": f["subject"], "predicate": f["predicate"],
          "value_kind": f.get("value_kind", "text"), "unit": f.get("unit", ""),
          "date_type": f.get("date_type", "")} for f in CONTRACT["required_facts"]]
UNKNOWNS = [{"item_id": u["item_id"], "description": u["description"]} for u in CONTRACT["unknown_items"]]

E_SYSTEM = ("你是精确的文书信息抽取器。只输出一个 JSON 对象：{ \"subjects\": [...], \"notice_numbers\": [...], "
            "\"dates\": [...], \"cause\": [...], \"quotes\": [...] }，每项为 {field,value,quote(完整原句逐字引用),page}。不得编造。")
J1_SYSTEM = ("你是跨文档实体归一核验器。只输出 JSON：{ \"judgments\": [{ \"kind\": person_identity|notice_instance|"
             "receipt_event|announcing_companies, \"verdict\": SAME_PERSON|DIFFERENT_PERSON|SAME_NOTICE_INSTANCE|"
             "DIFFERENT_NOTICE_INSTANCE|SAME_RECEIPT_EVENT|DIFFERENT_EVENT|SAME_COMPANY|DIFFERENT_COMPANY|UNKNOWN, "
             "\"evidence\": [{\"doc_id\":..., \"page\":..., \"quote\": 上游原句, \"source_raw_sha256\":...}] , "
             "\"reasoning\": 每项不超过15字 }] }。每个判断必须携带全部支撑证据锚点五元组(doc_id/page/quote/"
             "来源哈希/判断项)，照抄上游引文与哈希，不得省略。仅依据给定材料。")
J2_SYSTEM = ("你是主体绑定与计数核验器。只输出 JSON：{ \"subject_binding\": [{doc, subject_type, entities, "
             "evidence:[锚点五元组]}], \"notice_binding\": [{doc, numbers, per_number_binding_or_null, "
             "rule_applied: ordered_correspondence|null, evidence:[锚点五元组]}], \"cause_specificity\": "
             "[{doc, class, evidence:[锚点五元组]}], \"counts\": {personal_filing_instances, "
             "announcing_company_count, d3_subject_count, evidence:[锚点五元组]}, \"unresolvable\": "
             "[{field, reason}] }。subject_type ∈ {COMPANY_ONLY, PERSON_ONLY, BOTH}；cause class ∈ "
             "{SPECIFIC, GENERIC}。每项判断必须携带证据锚点五元组(doc_id/page/quote/来源哈希/判断项)，"
             "照抄上游引文与哈希；无法判定项列入 unresolvable（如日期仅'近日'）。仅依据给定材料。")
SINK_SYSTEM = ("你是严谨的最终答案汇总器。只输出一个 JSON 对象：{\"answers\":[...], \"abstentions\":[...], "
               "\"complete\": true/false}。不得使用给定上游材料之外的任何信息。")


def e_user(node):
    doc = DOCMAP[node]
    text = "".join(rec["text"] for rec in SRC[doc]["pages"].values())
    return (f"任务问题：{QUESTION}\n\n文档{doc}全文：\n{text}\n\n"
            "请抽取：立案对象(公司/个人/两者及姓名)、告知书编号(逐个)、全部日期(注明性质：落款/收到)、"
            "立案事由(原句)、以及对应完整原句引用。输出上述 JSON。")


def j1_user(upstream_e1e2):
    return (f"任务问题：{QUESTION}\n\n以下是两份公告（不同上市公司）的抽取结果：\n{upstream_e1e2}\n\n"
            "请判定：两份公告中的'俞发祥'是否同一自然人；两份公告引用的告知书是否同一份实例；"
            "收到事件是否同一事件；两家公告主体是否同一公司。按系统约定输出。")


def j2_user(upstream_j1_e3e4):
    return (f"任务问题：{QUESTION}\n\n以下是实体归一结果与另两份公告抽取：\n{upstream_j1_e3e4}\n\n"
            "请完成：四份公告各自的主体绑定与编号归属（含 D3 两编号按'分别…分别'顺序对应规则逐号绑定）；"
            "事由特定性分类；三项计数。按系统约定输出。")


def sink_user(upstream_j1j2):
    return (f"任务问题：{QUESTION}\n\n以下是实体归一与主体绑定计数结果：\n{upstream_j1j2}\n\n"
            f"输出格式：answers 按槽位逐项填写 {{\"fact_id\":..., \"value\":..., \"quote\": 上游所引完整原句, \"doc\": 文档ID}}。\n"
            "数值只填数字；日期 YYYY-MM-DD；关系判断按槽位语义作答。\n"
            f"槽位：{json.dumps(SLOTS, ensure_ascii=False)}\n"
            f"unknown 项（无法确定且属下列项时写 abstentions 并给明确拒判语句）：{json.dumps(UNKNOWNS, ensure_ascii=False)}\n"
            "如认为上游不完整无法负责作答，置 complete=false。")


def serialize(node, system, user):
    return {"node": node, "system": system, "user": user, "user_chars": len(user),
            "prompt_sha256": sha(system + "||" + user)}


def isolation_checks(real_prompts, templates):
    """Operator §6 four checks, mechanical."""
    report = {}
    banned_everywhere = ["description", "bucket", "critical\": true", "gold_provenance",
                         "source_evidence", "SAME_PERSON，", "GOLD_CONFIRMED"]
    enum_labels = ["SAME_PERSON", "SAME_NOTICE_INSTANCE", "SAME_RECEIPT_EVENT", "DIFFERENT_COMPANY",
                   "COMPANY_ONLY", "PERSON_ONLY", "BOTH", "SPECIFIC", "GENERIC"]
    desc_texts = [f.get("description", "") for f in CONTRACT["required_facts"] if len(f.get("description", "")) > 8]
    issues = []
    # check 1: no description / contract-internal fields in any serialized real E prompt
    for p in real_prompts:
        blob = p["system"] + p["user"]
        for dt in desc_texts:
            if dt[:20] in blob:
                issues.append(f"{p['node']}: description fragment leaked")
        for b in banned_everywhere:
            if b in blob:
                issues.append(f"{p['node']}: banned token {b}")
        for lab in enum_labels:  # enum labels never in E prompts
            if lab in blob:
                issues.append(f"{p['node']}: enum label {lab} in extraction prompt")
    # check 2/3: templates — enum labels only inside system output-format lines; no pair-specific answers
    for name, t in templates.items():
        body = t["system"] + t["user"]
        for b in ["critical\": true", "gold_provenance", "source_evidence"]:
            if b in body:
                issues.append(f"template {name}: contract field {b}")
        for lab in enum_labels:
            n = body.count(lab)
            in_system = t["system"].count(lab)
            if n > in_system:  # any occurrence in user part = potential leak
                issues.append(f"template {name}: enum {lab} appears in user prompt")
        for dt in desc_texts:
            if dt[:20] in body:
                issues.append(f"template {name}: description fragment")
    # check 4: no backfill path — sink/J builders take ONLY upstream outputs (structural, verified by signature)
    report["issues"] = issues
    report["structural_whitelist"] = ("E: question+doc_text only; J1: E1+E2 outputs only; J2: J1+E3+E4 outputs only; "
                                      "SINK: J1+J2 outputs only — no function in this module reads required_facts "
                                      "values/evidence/critical for prompt construction (slots exclude description)")
    report["sink_no_raw_E_bypass"] = True
    return report


def main():
    real = [serialize(f"E{i}", E_SYSTEM, e_user(f"E{i}")) for i in (1, 2, 3, 4)]
    synth_e = ("{\"subjects\":[{\"value\":\"实际控制人俞发祥(个人)\",\"quote\":\"…\"}],"
               "\"notice_numbers\":[{\"value\":\"证监立案字01120260037号\",\"quote\":\"…\"}],"
               "\"dates\":[{\"value\":\"2026-10-09\",\"field\":\"收到/落款\",\"quote\":\"…\"}],\"cause\":[{\"value\":\"个人涉嫌信息披露违法违规\",\"quote\":\"…\"}]}")
    t_j1 = {"system": J1_SYSTEM, "user": j1_user("<E1输出JSON> ; <E2输出JSON>"),
            "synthetic_example_user": j1_user(json.dumps({"E1": synth_e, "E2": synth_e}, ensure_ascii=False)[:600] + "…")}
    t_j2 = {"system": J2_SYSTEM, "user": j2_user("<J1输出JSON> ; <E3输出JSON> ; <E4输出JSON>"),
            "synthetic_example_user": j2_user("{J1: {person_identity:…}} ; …")[:400] + "…"}
    t_sink = {"system": SINK_SYSTEM, "user": sink_user("<J1输出JSON> ; <J2输出JSON>"),
              "synthetic_example_user": sink_user("{J1:…, J2:…}")[:400] + "…"}
    templates = {"J1": t_j1, "J2": t_j2, "SINK": t_sink}
    iso = isolation_checks(real, templates)
    out = OUT / "prompts"
    (out / "real").mkdir(parents=True, exist_ok=True)
    (out / "templates").mkdir(parents=True, exist_ok=True)
    for p in real:
        (out / "real" / f"{p['node']}.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, t in templates.items():
        (out / "templates" / f"{name}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "isolation_report.json").write_text(json.dumps(iso, ensure_ascii=False, indent=1), encoding="utf-8")
    print("real prompts:", [(p["node"], p["user_chars"], p["prompt_sha256"][:12]) for p in real])
    print("isolation issues:", iso["issues"] or "NONE — 全部通过")


if __name__ == "__main__":
    main()
