#!/usr/bin/env python3
"""Phase-2B contract builder: 跨公司主体绑定与实体归一判断 (E10+E10b+E07+E05).

Operator rulings baked in (2026-10-31):
 - three-level identity separation: SAME_PERSON / SAME_NOTICE_INSTANCE / SAME_RECEIT_EVENT
 - E07 UNKNOWN localized field-by-field (number-subject binding UNKNOWN; both-subject
   and two-numbers judgeable; receipt date only '近日' -> UNKNOWN)
 - five evaluation buckets kept separate: 主体识别 / 文书归属 / 事由特定性 /
   实体归一 / 事件计数
 - descriptions stay INTERNAL to the contract (runner slots strip them; no leak)
Frozen BEFORE any model call; all anchors verbatim-verified against source pages.
"""
import hashlib
import json
import sys
from pathlib import Path

import pymupdf

DOCS = Path("/root/capital_opinion_pilot/benchmark_v1/docs")
OUT = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B")
FILES = {"D1": "E10-xiangyuan.pdf", "D2": "E10b-jiaojian.pdf", "D3": "E07-xiwang.pdf", "D4": "E05-nachuan.pdf"}
RAW_SHA = {"D1": "4c930d1536ed4728", "D2": "168f72a8ce646217", "D3": "dd764d9fc43f2b36", "D4": "0c62e50f6e6b567f"}


def load():
    src = {}
    for doc_id, fn in FILES.items():
        raw = hashlib.sha256((DOCS / fn).read_bytes()).hexdigest()
        assert raw.startswith(RAW_SHA[doc_id]), f"{doc_id} hash drift"
        doc = pymupdf.open(DOCS / fn)
        pages = {}
        for i, page in enumerate(doc, start=1):
            t = page.get_text("text")
            pages[str(i)] = {"text": t, "page_sha256": hashlib.sha256(t.encode()).hexdigest()}
        src[doc_id] = {"raw_sha256": raw, "pages": pages}
    return src


def locator(src):
    def norm(s):
        return "".join(ch for ch in str(s) if not ch.isspace())

    def locate(doc_id, quote):
        rec = src[doc_id]["pages"]["1"]
        q = norm(quote)
        idx = norm(rec["text"]).find(q)
        assert idx >= 0, f"anchor miss {doc_id}: {quote[:30]}"
        cnt = -1
        for pos, ch in enumerate(rec["text"]):
            if not ch.isspace():
                cnt += 1
                if cnt == idx:
                    start = pos
                if cnt == idx + len(q) - 1:
                    return {"doc_id": doc_id, "page": 1, "quote": rec["text"][start:pos + 1],
                            "raw_sha256": src[doc_id]["raw_sha256"], "page_sha256": rec["page_sha256"],
                            "start": start, "end": pos + 1}
    return locate


def fact(fid, subject, predicate, value, evid, *, critical=False, bucket="", kind="text", note=""):
    return {"fact_id": fid, "status": "GOLD_CONFIRMED", "gold_provenance": "official_structured_record",
            "gold_source_sha256": evid[0]["raw_sha256"], "weight": 1.0, "critical": critical,
            "evidence_required": True, "value_kind": kind, "subject": subject, "predicate": predicate,
            "value": value, "source_evidence": evid, "bucket": bucket, "description": note}


def build():
    src = load()
    loc = locator(src)
    F = []

    # ---- bucket A 主体识别 (SUBJECT per doc) ----
    F.append(fact("A1", "祥源文旅公告(D1)", "立案对象", "PERSON_ONLY_实际控制人俞发祥",
                  [loc("D1", "实际控制人俞发祥先生通知")], critical=True, bucket="主体识别",
                  note="公告主体=祥源文旅(公司)；立案对象=俞发祥个人。两概念必须分离"))
    F.append(fact("A2", "交建股份公告(D2)", "立案对象", "PERSON_ONLY_实际控制人俞发祥",
                  [loc("D2", "实际控制人俞发祥先生通知")], critical=True, bucket="主体识别"))
    F.append(fact("A3", "西王食品公告(D3)", "立案对象", "BOTH_公司及实际控制人王勇",
                  [loc("D3", "对公司、实际控制人王勇先生下发的《立案告知书》")], critical=True, bucket="主体识别"))
    F.append(fact("A4", "纳川公告(D4)", "立案对象", "COMPANY_ONLY_纳川公司",
                  [loc("D4", "决定对公司立案")], critical=True, bucket="主体识别"))
    F.append(fact("A5", "俞发祥", "在两家上市公司的职务", "均无职务(仅实际控制人)",
                  [loc("D1", "除为公司实际控制人外，未在公司担任任何职务"),
                   loc("D2", "除为公司实际控制人外，未在公司担任任何职务")],
                  bucket="主体识别", note="D1与D2均明示；两文档交叉验证"))

    # ---- bucket B 文书归属 (NOTICE ownership) ----
    F.append(fact("B1", "D1立案告知书", "编号", "证监立案字01120260037号",
                  [loc("D1", "证监立案字01120260037 号")], bucket="文书归属", kind="text"))
    F.append(fact("B2", "D2立案告知书", "编号", "证监立案字01120260037号",
                  [loc("D2", "证监立案字01120260037 号")], bucket="文书归属"))
    F.append(fact("B3", "D3立案告知书", "编号数量与结构", "两个编号存在、两主体(公司与王勇)均被立案",
                  [loc("D3", "告知书编号分别为：证监立案字0042026002 号、证监立案字0042026003 号")],
                  critical=True, bucket="文书归属"))
    F.append(fact("B3b", "D3两编号与两主体", "逐号绑定(按原文'分别…分别'顺序对应规则)",
                  "0042026002号→公司(西王食品)；0042026003号→王勇",
                  [loc("D3", "分别对公司、实际控制人王勇先生下发的《立案告知书》（告知书编号分别为：证监立案字0042026002 号、证监立案字0042026003 号")],
                  critical=True, bucket="文书归属",
                  note="操作者2026-10-31裁定：原文两处'分别'构成有序列表对应规则，Gold复核者已确认该规则——由UNKNOWN改为可判；规则文本入annotation_rules"))
    F.append(fact("B4", "D4立案告知书", "编号", "证监立案字0262026012号",
                  [loc("D4", "证监立案字0262026012 号")], bucket="文书归属"))

    # ---- bucket C 事由特定性 ----
    F.append(fact("C1", "D4纳川立案", "事由特定性", "SPECIFIC_因公司2023年年报涉嫌信息披露违法违规",
                  [loc("D4", "因公司2023 年年报涉嫌信息披露违法违规")], bucket="事由特定性",
                  note="唯一明确到具体年报的立案事由"))
    F.append(fact("C2", "D1/D2/D3立案", "事由特定性", "GENERIC_涉嫌信息披露违法违规(未指明具体报告)",
                  [loc("D1", "因俞发祥先生个人涉嫌信息披露违法违规"),
                   loc("D3", "因涉嫌信息披露违法违规")], bucket="事由特定性"))

    # ---- bucket D 实体归一 (三级分离 per operator) ----
    F.append(fact("D_1", "俞发祥(D1)与俞发祥(D2)", "自然人身份", "SAME_PERSON",
                  [loc("D1", "俞发祥"), loc("D2", "俞发祥")], critical=True, bucket="实体归一",
                  note="同名+同编号+同日→同一自然人"))
    F.append(fact("D_2", "D1文书与D2文书", "监管文书实例", "SAME_NOTICE_INSTANCE",
                  [loc("D1", "证监立案字01120260037 号"), loc("D2", "证监立案字01120260037 号")],
                  critical=True, bucket="实体归一", note="同编号→同一份告知书（非两份）"))
    F.append(fact("D_3", "D1事件与D2事件", "收到文书事件", "SAME_RECEIPT_EVENT",
                  [loc("D1", "于2026 年10 月9 日收到"), loc("D2", "于2026 年10 月9 日收到")],
                  bucket="实体归一", note="同一人同日收到同一份文书→同一事件"))
    F.append(fact("D_4", "D1公告主体与D2公告主体", "公告主体关系", "DIFFERENT_COMPANY",
                  [loc("D1", "浙江祥源文旅股份有限公司"), loc("D2", "安徽省交通建设股份有限公司")],
                  critical=True, bucket="实体归一", note="俞发祥同时为两家公司实控人；公告主体不同"))

    # ---- bucket E 事件计数 ----
    F.append(fact("E1", "俞发祥个人", "立案文书实例数(跨D1/D2)", "1",
                  [loc("D1", "证监立案字01120260037 号"), loc("D2", "证监立案字01120260037 号")],
                  critical=True, bucket="事件计数", kind="number",
                  note="两公告指向同一份文书→1，非2"))
    F.append(fact("E2", "涉及公告的上市公司数量", "公告主体数", "2",
                  [loc("D1", "浙江祥源文旅股份有限公司"), loc("D2", "安徽省交通建设股份有限公司")],
                  critical=True, bucket="事件计数", kind="number"))
    F.append(fact("E3", "D3西王", "立案对象主体数", "2(公司+自然人王勇)",
                  [loc("D3", "对公司、实际控制人王勇先生")], bucket="事件计数", kind="number"))

    # ---- 日期（操作者裁定：落款日与披露日双口径分离，不得混同）----
    F.append(fact("F1", "D1祥源文旅", "公告落款日(document_signature_date)", "2026-10-09",
                  [loc("D1", "2026 年10 月9 日")], bucket="日期", kind="date", note="落款，非披露日"))
    F.append(fact("F2", "D2交建股份", "公告落款日(document_signature_date)", "2026-10-10",
                  [loc("D2", "2026 年10 月10 日")], bucket="日期", kind="date",
                  note="与D1落款差一日；披露日相同（见外部注记）"))
    F.append(fact("F3", "俞发祥", "告知书收到日(D1与D2均载)", "2026-10-09",
                  [loc("D1", "其于同日收到"), loc("D2", "其于同日收到")], bucket="日期", kind="date"))
    F.append(fact("F4", "D1与D2的落款日与收到日关系", "落款日差与收到事件关系",
                  "落款日不同(10-09 vs 10-10)且收到日相同(10-09)——落款日差不构成收到事件差",
                  [loc("D1", "2026 年10 月9 日"), loc("D2", "2026 年10 月10 日"),
                   loc("D1", "其于同日收到"), loc("D2", "其于同日收到")],
                  critical=True, bucket="日期",
                  note="判断点：同一收到事件、不同落款日、相同披露日（披露日见外部注记块，非计分事实）"))

    question = ("四份公告各自：谁被立案（公司/实控人/两者）？告知书编号是什么？D1与D2是否指向同一个俞发祥、同一份立案告知书、"
                "同一收到事件？两家公告主体是否为同一公司？俞发祥个人被立案的文书实例数与公告公司数各是多少？"
                "D3的两个编号能否逐号对应到公司与王勇？各公告的立案事由是特定还是泛称？公告日与收到日分别是什么？")

    contract = {"task_id": "PHASE2B_ENTITY_RESOLUTION_v2_1", "reference_type": "MVR_v1",
                "question": question, "cutoff": "2026-10-31", "min_gold_coverage": 1.0,
                "dimension_weights": {k: 1 for k in ("fact_correctness", "evidence_support", "necessary_completeness",
                                                     "contradiction_handling", "unverifiable_refusal", "question_relevance")},
                "required_facts": F,
                "unknown_items": [
                    {"item_id": "U2", "description": "D3收到告知书的具体日期——原文仅'近日'，不可判定（独立槽位：非任何既有事实的局部字段；D3公告落款日2026-04-28另行独立记录于日期桶，不与收到日混同）",
                     "expected_status": "UNKNOWN"}],
                "verified_external_annotations": {
                    "_说明": "操作者以上交所公告目录核验，属冻结语料外证据——如实记录、不作为计分事实（无文档内锚点）",
                    "scoreable": False,
                    "prompt_visible": False,
                    "参与23项事实评分": False,
                    "作为模型对错判定依据": False,
                    "如需改为计分事实的前置条件": "须将交易所披露记录作为正式证据源单独冻结哈希",
                    "D1披露日": "2026-10-10（落款10-09）",
                    "D2披露日": "2026-10-10（落款10-10）",
                    "判断含义": "同一收到事件+不同落款日+相同正式披露日"},
                "annotation_rules": [
                    "有序列表对应规则（操作者确认）：原文'分别对A、B下发…（编号分别为：N1、N2）'中两处'分别'构成 N1→A、N2→B 的顺序对应，可判定绑定",
                    "落款日(document_signature_date)与披露日(disclosure_date)为不同日期类型，禁止混同；冻结语料外的披露日仅记录于外部注记块",
                    "收到日'近日'→该字段UNKNOWN；公告落款日独立记录，两者不得互推"],
                "critical_fact_ids": [],
                "conflict_groups": [], "source_pages": src,
                "provenance": {"nature": "四份公司公告（E10/E10b/E07/E05），哈希沿用冻结manifest并逐文件复核",
                               "model_calls": 0, "built_by": "ZCode, frozen before any call, operator review fixes applied (date dual-type/U1 rule/E3 term/critical list)"},
                "_critical_ids_fill": True}
    contract["critical_fact_ids"] = [f["fact_id"] for f in F if f["critical"]]
    contract.pop("_critical_ids_fill")
    return contract


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    c = build()
    p = OUT / "TASK_CONTRACT_PHASE2B_v2_1.json"
    p.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    print("facts:", len(c["required_facts"]), "| critical:", [f["fact_id"] for f in c["required_facts"] if f["critical"]])
    from collections import Counter
    print("buckets:", dict(Counter(f["bucket"] for f in c["required_facts"])))
    print("sha256:", hashlib.sha256(p.read_bytes()).hexdigest())
