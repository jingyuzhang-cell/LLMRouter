#!/usr/bin/env python3
"""Build the MVR-2 task contract: 元道通信 penalty/delisting chain (three announcements).

Route B baseline artifact #2 (operator approval 2026-10-30: MVR-2 to test
mechanism transfer to a second independent event). Zero model calls.

  Da E03-yuandao.pdf      公告2026-088 收到《行政处罚决定书》(处罚字【2026】42号, 终罚+分项+虚增明细+禁入)
  Db E03-yuandao_sup2.pdf 公告2026-031 收到《行政处罚事先告知书》(处罚字【2026】14号, 拟罚)
  Dc E03-yuandao_sup1.pdf 公告2026-090 收到深交所《事先告知书》(创业板函〔2026〕第122号, 拟终止上市)

MVR-2's distinctive deterministic structure (absent from MVR-1): a REAL
拟→终 difference — 曹亚蕾 fine 750万(拟) → 600万(终, 申辩部分采纳), 市场禁入
5年(拟) → 4年(终) — plus itemized fines that sum exactly into the combined
fines, a four-year inflated-revenue total, and THREE distinct document numbers
from two authorities (CSRC ×2, SZSE ×1).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pymupdf

DOCS = Path("/root/capital_opinion_pilot/benchmark_v1/docs")
OUT = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR2_yuandao")
FILES = {
    "Da": "E03-yuandao.pdf",
    "Db": "E03-yuandao_sup2.pdf",
    "Dc": "E03-yuandao_sup1.pdf",
}


def norm_pair(s: str):
    out, mapping = [], []
    for i, ch in enumerate(s):
        if ch.isspace():
            continue
        out.append(ch)
        mapping.append(i)
    return "".join(out), mapping


def build() -> dict:
    sources = {}
    for doc_id, filename in FILES.items():
        raw = hashlib.sha256((DOCS / filename).read_bytes()).hexdigest()
        doc = pymupdf.open(DOCS / filename)
        pages = {}
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text")
            pages[str(i)] = {"text": text, "page_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        sources[doc_id] = {"raw_sha256": raw, "pages": pages}

    def locate(doc_id: str, quote: str):
        for page_no, record in sources[doc_id]["pages"].items():
            n_text, m_text = norm_pair(record["text"])
            n_quote, _ = norm_pair(quote)
            idx = n_text.find(n_quote)
            if idx >= 0:
                start, end = m_text[idx], m_text[idx + len(n_quote) - 1] + 1
                return {"doc_id": doc_id, "page": int(page_no), "quote": record["text"][start:end],
                        "raw_sha256": sources[doc_id]["raw_sha256"],
                        "page_sha256": record["page_sha256"], "start": start, "end": end}
        raise AssertionError(f"quote not found in {doc_id}: {quote[:36]}")

    def fact(fid, subject, predicate, value, kind, evid, *, critical=False, unit=None,
             date_type=None, derivation=None, evidence_mode=None, note=""):
        f = {
            "fact_id": fid, "status": "GOLD_CONFIRMED",
            "gold_provenance": "official_structured_record",
            "gold_source_sha256": evid[0]["raw_sha256"],
            "weight": 1.0, "critical": critical, "evidence_required": True,
            "value_kind": kind, "subject": subject, "predicate": predicate, "value": value,
            "source_evidence": evid, "description": note,
        }
        if unit is not None:
            f["unit"] = unit
        if date_type is not None:
            f["date_type"] = date_type
        if derivation is not None:
            f["derivation"] = derivation
        if evidence_mode is not None:
            f["evidence_mode"] = evidence_mode
        return f

    span_company_fraud = locate("Da", "对元道通信股份有限公司处以非法所募资金金额百分之二十的罚款，即处以233,836,800 元罚款")
    span_company_disc = locate("Da", "对元道通信股份有限公司责令改正，给予警告，并处以500 万元罚款")
    span_company_total = locate("Da", "一、对元道通信股份有限公司责令改正，给予警告，并处以238,836,800")
    span_cao_fraud = locate("Da", "对曹亚蕾处以400 万元罚款")
    span_cao_disc = locate("Da", "对曹亚蕾给予警告，并处以200 万元罚款")
    span_cao_total = locate("Da", "对曹亚蕾给予警告，并处以600 万元罚款")
    span_cao_proposed = locate("Db", "对曹亚蕾给予警告，并处以750 万元罚款")
    span_inflate_3y = locate("Da", "虚增营业\n收入65,902,640.59 元、160,688,291.80 元、263,632,076.14 元")
    span_inflate_2022 = locate("Da", "虚增营业收入\n166,218,396.33 元")
    span_raise_a = locate("Da", "发行募集资金总额为1,169,184,000 元")
    span_raise_b = locate("Db", "发行募集资金总额为116,918.40 万元")

    facts = [
        fact("FA1", "元道通信股份有限公司", "欺诈发行违法行为罚款金额", "233836800", "amount",
             [span_company_fraud], critical=True, unit="元",
             note="非法所募资金金额的20%（1,169,184,000×20%）；决定书欺诈发行项"),
        fact("FA2", "元道通信股份有限公司", "信息披露违法行为罚款金额", "5000000", "amount",
             [span_company_disc], unit="元", note="决定书信披项 500 万元"),
        fact("FA3", "元道通信股份有限公司", "行政处罚综合罚款金额", "238836800", "amount",
             [span_company_total], critical=True, unit="元",
             derivation={"op": "add", "inputs": ["FA1", "FA2"]}, evidence_mode="ALL",
             note="算术派生：欺诈发行项+信披项；与决定书综合段明载值一致"),
        fact("FB1", "李晋", "行政处罚综合罚款金额", "7500000", "amount",
             [locate("Da", "对李晋给予警告，并处以750 万元罚款")], unit="元", note="=欺诈500万+信披250万"),
        fact("FB2", "曹亚蕾", "欺诈发行违法行为罚款金额", "4000000", "amount", [span_cao_fraud], unit="元"),
        fact("FB3", "曹亚蕾", "信息披露违法行为罚款金额", "2000000", "amount", [span_cao_disc], unit="元"),
        fact("FB4", "曹亚蕾", "行政处罚综合罚款金额", "6000000", "amount", [span_cao_total],
             critical=True, unit="元",
             derivation={"op": "add", "inputs": ["FB2", "FB3"]}, evidence_mode="ALL",
             note="终罚 600 万；告知书拟罚 750 万被下调（见 FC2）——拟≠终的真实案例"),
        fact("FB5", "吴志锋", "行政处罚综合罚款金额", "3000000", "amount",
             [locate("Da", "对吴志锋给予警告，并处以300 万元罚款")], unit="元", note="=欺诈200万+信披100万"),
        fact("FB6", "燕某", "行政处罚结果", "免予处罚（已故）", "text",
             [locate("Da", "对燕某(已故)免予处罚")], note="主体状态：已故，免予处罚——既非罚款也非禁入"),
        fact("FC1", "曹亚蕾", "事先告知书拟处罚金额", "7500000", "amount", [span_cao_proposed], unit="元",
             note="拟罚 750 万（Db）"),
        fact("FC2", "曹亚蕾", "拟处罚与终处罚金额差异", "1500000", "amount",
             [span_cao_proposed, span_cao_total], critical=True, unit="元",
             derivation={"op": "subtract", "inputs": ["FC1", "FB4"]}, evidence_mode="ALL",
             note="算术派生：拟750万−终600万=150万；下调原因=决定书对曹亚蕾部分申辩意见予以采纳（原因在 Da 明载）"),
        fact("FD1", "李晋", "证券市场禁入年限（决定书）", "5", "number",
             [locate("Da", "对李晋采取5 年证券市场禁入措施")], unit="年"),
        fact("FD2", "曹亚蕾", "证券市场禁入年限（决定书）", "4", "number",
             [locate("Da", "对曹亚蕾采取4 年证券市场禁入措施")], unit="年",
             note="终罚禁入 4 年；拟为 5 年（FD3），申辩采纳后下调"),
        fact("FD3", "曹亚蕾", "证券市场禁入年限（事先告知书拟）", "5", "number",
             [locate("Db", "对曹亚蕾采取5 年证券市场禁入措施")], unit="年"),
        fact("FE1", "元道通信处罚链", "行政处罚事先告知书文号", "处罚字【2026】14号", "text",
             [locate("Db", "处罚字【2026】\n14 号")], note="证监会告知书文号"),
        fact("FE2", "元道通信处罚链", "行政处罚决定书文号", "处罚字【2026】42号", "text",
             [locate("Da", "处罚字【2026】42 号")], critical=True,
             note="与告知书14号、深交所函122号严格区分；混淆即事实失败"),
        fact("FE3", "元道退市程序", "深交所事先告知书文号", "创业板函〔2026〕第122号", "text",
             [locate("Dc", "创业板函〔2026〕第122\n号")], note="深交所拟终止上市函（另一机关）"),
        fact("FF1", "元道通信", "立案告知书公告披露日期", "2025-07-11", "date",
             [locate("Da", "2025 年\n7 月11 日")], date_type="publication",
             note="date_type=publication（公告披露日），非收到日"),
        fact("FF2", "元道通信及相关当事人", "行政处罚事先告知书收到日期", "2026-05-08", "date",
             [locate("Db", "2026 年5 月8 日")], date_type="receipt"),
        fact("FF3", "元道通信及相关当事人", "行政处罚决定书收到日期", "2026-08-28", "date",
             [locate("Da", "2026 年8 月28 日")], date_type="receipt",
             note="深交所函（Dc）同日送达并引用该决定书"),
        fact("FF4", "元道通信", "股票停牌日期", "2026-08-31", "date",
             [locate("Da", "公司股票将于2026 年8 月31 日(星期一)开市起停牌")], date_type="trading_halt"),
        fact("FG1", "元道通信2019年度", "虚增营业收入", "65902640.59", "amount", [span_inflate_3y], unit="元"),
        fact("FG2", "元道通信2020年度", "虚增营业收入", "160688291.80", "amount", [span_inflate_3y], unit="元"),
        fact("FG3", "元道通信2021年度", "虚增营业收入", "263632076.14", "amount", [span_inflate_3y], unit="元"),
        fact("FG4", "元道通信2022年度（年报）", "虚增营业收入", "166218396.33", "amount", [span_inflate_2022], unit="元"),
        fact("FG5", "元道通信2019-2022", "虚增营业收入合计", "656441404.86", "amount",
             [span_inflate_3y, span_inflate_2022], unit="元",
             derivation={"op": "add", "inputs": ["FG1", "FG2", "FG3", "FG4"]}, evidence_mode="ALL",
             note="纯 MVR 算术：四年度之和（原文未直接给出合计）"),
        fact("FH1", "元道通信IPO", "发行募集资金总额", "1169184000", "amount",
             [span_raise_a, span_raise_b], unit="元",
             note="Da 记 1,169,184,000 元；Db 记 116,918.40 万元——双源同值不同单位表述，跨文档一致性"),
    ]

    question = (
        "元道通信欺诈发行及信息披露违法案：事先告知书拟对各当事人处罚多少？行政处罚决定书最终对公司和"
        "李晋、燕某、曹亚蕾、吴志锋分别处罚多少？曹亚蕾拟罚与终罚差多少、为何不同？对李晋、曹亚蕾的市场禁入"
        "分别几年（拟与终）？三份文书的文号分别是什么？立案公告、告知书、决定书、停牌各是何日期？"
        "2019-2022 各年虚增营业收入及四年合计是多少？IPO 募集资金总额多少？"
    )
    return {
        "task_id": "MVR2_YUANDAO_PENALTY_DELISTING_v1",
        "reference_type": "MVR_v1",
        "governance": (
            "Machine-Verifiable Reference (Route B). NOT human Gold; results reported as "
            "Q_MVR observables (dimensions + critical gate + fact metrics); Q_final "
            "deliberately NULL (relevance unassessed). No LLM on the reference side."
        ),
        "question": question,
        "cutoff": "2026-10-30",
        "min_gold_coverage": 1.0,
        "dimension_weights": {
            "fact_correctness": 1, "evidence_support": 1, "necessary_completeness": 1,
            "contradiction_handling": 1, "unverifiable_refusal": 1, "question_relevance": 1,
        },
        "required_facts": facts,
        "optional_facts": [],
        "unknown_items": [
            {"item_id": "U1", "description": "曹亚蕾被采纳申辩意见的具体采纳范围与内部权衡（决定书仅结论性表述）",
             "expected_status": "UNKNOWN"},
            {"item_id": "U2", "description": "燕某（已故）免予处罚的程序处理细节",
             "expected_status": "UNKNOWN"},
        ],
        "conflict_groups": [],
        "source_pages": sources,
        "provenance": {
            "Da": {"file": FILES["Da"], "sha256": sources["Da"]["raw_sha256"],
                    "nature": "公司公告 2026-088：收到《行政处罚决定书》（处罚字【2026】42号）全文转载"},
            "Db": {"file": FILES["Db"], "sha256": sources["Db"]["raw_sha256"],
                    "nature": "公司公告 2026-031：收到《行政处罚事先告知书》（处罚字【2026】14号）全文转载"},
            "Dc": {"file": FILES["Dc"], "sha256": sources["Dc"]["raw_sha256"],
                    "nature": "公司公告 2026-090：收到深交所《事先告知书》（创业板函〔2026〕第122号，拟终止上市）"},
            "extraction": "pymupdf 1.28.2 page.get_text('text'), multi-page anchoring",
            "deterministic": True,
            "model_calls": 0,
            "built_by": "ZCode (machine-anchored), 2026-10-30, per Route B approval",
        },
    }


def main() -> int:
    contract = build()
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "TASK_CONTRACT_MVR2_v1.json"
    target.write_text(json.dumps(contract, ensure_ascii=False, indent=1), encoding="utf-8")
    print("WROTE", target)
    print("facts:", len(contract["required_facts"]),
          "| critical:", [f["fact_id"] for f in contract["required_facts"] if f["critical"]])
    print("sha256:", hashlib.sha256(target.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
