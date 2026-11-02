#!/usr/bin/env python3
"""Build the MVR-1 task contract: 江苏舜天 penalty chain (four authoritative documents).

Route B (MVR) baseline artifact per operator approval 2026-10-30 (Route B elevated
to the priority implementation path). Zero model calls; deterministic extraction
and hash binding; facts verified against authoritative originals only:

  D1 st_advance_notice_2023.html  公司《收到行政处罚及市场禁入事先告知书的公告》〔2023〕37号(拟处罚)
  D2 csrc_penalty_2024_41.html    证监会《行政处罚决定书》〔2024〕41号原文(终罚+虚增明细+程序日期)
  D3 st_announce_2024_020.pdf     公司公告 临2024-020(收到决定书+市场禁入; 立案日期/编号)
  D4 st_announce_2024_021.pdf     公司公告(进展, 引用〔2024〕41号)

Governance label: reference_type=MVR_v1 — this is a machine-verifiable reference,
NOT human Gold. In-contract status uses the evaluator's GOLD_CONFIRMED semantics
(provenance=official_structured_record); reported results are Q_MVR observables
(dimensions + critical gate + fact metrics) and Q_final stays NULL by design
because question relevance is deliberately left unassessed in MVR mode.
"""
from __future__ import annotations

import hashlib
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

import pymupdf

RAW = Path("/root/capital_opinion_pilot/evidence/raw")
OUT = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR1_shuntian")

EXTRACTION_NOTE = (
    "D1/D2: python html.parser text extraction (deterministic, single page); "
    "D3/D4: pymupdf 1.28.2 page.get_text('text')"
)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def html_text(path: Path) -> str:
    parser = _Text()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return "".join(parser.parts)


def pdf_pages(path: Path) -> dict:
    doc = pymupdf.open(path)
    pages = {}
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        pages[str(i)] = {"text": text, "page_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return pages


def build() -> dict:
    sources, raw_sha = {}, {}
    for doc_id, filename, loader in (
        ("D1", "st_advance_notice_2023.html", html_text),
        ("D2", "csrc_penalty_2024_41.html", html_text),
    ):
        raw = hashlib.sha256((RAW / filename).read_bytes()).hexdigest()
        text = loader(RAW / filename)
        sources[doc_id] = {"raw_sha256": raw, "pages": {
            "1": {"text": text, "page_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}}}
        raw_sha[doc_id] = raw
    for doc_id, filename in (("D3", "st_announce_2024_020.pdf"), ("D4", "st_announce_2024_021.pdf")):
        raw = hashlib.sha256((RAW / filename).read_bytes()).hexdigest()
        sources[doc_id] = {"raw_sha256": raw, "pages": pdf_pages(RAW / filename)}
        raw_sha[doc_id] = raw

    def norm_map(s: str):
        out, mapping = [], []
        for i, ch in enumerate(s):
            if ch.isspace():
                continue
            out.append(ch)
            mapping.append(i)
        return "".join(out), mapping

    def locate(doc_id: str, quote: str):
        page_no = "1"
        text = sources[doc_id]["pages"][page_no]["text"]
        n_text, m_text = norm_map(text)
        n_quote, _ = norm_map(quote)
        idx = n_text.find(n_quote)
        assert idx >= 0, f"quote not found in {doc_id}: {quote[:36]}"
        start, end = m_text[idx], m_text[idx + len(n_quote) - 1] + 1
        return {"doc_id": doc_id, "page": 1, "quote": text[start:end],
                "raw_sha256": sources[doc_id]["raw_sha256"],
                "page_sha256": sources[doc_id]["pages"][page_no]["page_sha256"],
                "start": start, "end": end}

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

    dec_pen = locate("D2", "一、对江苏舜天股份有限公司责令改正,给予警告,并处以1,000万元罚款;二、对高松给予警告,并处以150万元罚款;三、对桂生春给予警告,并处以100万元罚款;四、对王重人、李焱、赵凡给予警告,并分别处以60万元罚款")
    adv_pen = locate("D1", "处以1,000万元罚款")
    infl = locate("D2", "虚增营业收入10,333,448,392.98元,虚增营业成本9,398,996,635.72元,虚增利润总额934,451,757.26元")
    notice_no = locate("D1", "处罚字〔2023〕37号")
    decision_no = locate("D2", "〔2024〕41号")
    filing = locate("D3", "于 2022 年 11 月4 日收到中国证券监督管理委员会下发的《立案告知书》（编号：证监立案字0382022008 号）")
    hearing = locate("D2", "我会于2023年10月17日举行了听证会")
    withdraw = locate("D2", "2024年3月22日,上述当事人申请撤回听证和陈述申辩")
    ban = locate("D1", "对高松作出证券市场禁入")
    ban_final = locate("D3", "《市场禁入决定书》")

    facts = [
        fact("F1", "江苏舜天股份有限公司", "行政处罚罚款金额", "1000", "amount", [dec_pen],
             critical=True, unit="万元", note="决定书终罚；告知书拟罚同额（D1 跨文档一致）"),
        fact("F2", "高松", "行政处罚罚款金额", "150", "amount", [locate("D2", "对高松给予警告,并处以150万元罚款")],
             critical=True, unit="万元", note="个人责任，与公司罚款分立"),
        fact("F3", "桂生春", "行政处罚罚款金额", "100", "amount", [locate("D2", "对桂生春给予警告,并处以100万元罚款")],
             unit="万元", note="个人责任"),
        fact("F4", "王重人", "行政处罚罚款金额", "60", "amount", [locate("D2", "对王重人、李焱、赵凡给予警告,并分别处以60万元罚款")],
             unit="万元", note="个人责任"),
        fact("F5", "李焱", "行政处罚罚款金额", "60", "amount", [locate("D2", "对王重人、李焱、赵凡给予警告,并分别处以60万元罚款")],
             unit="万元", note="个人责任"),
        fact("F6", "赵凡", "行政处罚罚款金额", "60", "amount", [locate("D2", "对王重人、李焱、赵凡给予警告,并分别处以60万元罚款")],
             unit="万元", note="个人责任"),
        fact("F7", "江苏舜天处罚链", "全部当事人罚款合计", "1430", "amount",
             [dec_pen, adv_pen], critical=True, unit="万元",
             derivation={"op": "add", "inputs": ["F1", "F2", "F3", "F4", "F5", "F6"]},
             evidence_mode="ALL", note="算术派生：六主体之和；D1/D2 双源锚定"),
        fact("F8", "江苏舜天2009-2021年度报告", "虚增营业收入总额", "10333448392.98", "amount", [infl],
             unit="元", note="决定书原文精确值"),
        fact("F9", "江苏舜天2009-2021年度报告", "虚增营业成本总额", "9398996635.72", "amount", [infl],
             unit="元", note="决定书原文精确值"),
        fact("F10", "江苏舜天2009-2021年度报告", "虚增利润总额", "934451757.26", "amount", [infl],
             critical=True, unit="元",
             derivation={"op": "subtract", "inputs": ["F8", "F9"]},
             evidence_mode="ALL",
             note="算术派生：F8−F9，已数值复核精确到分；同时为决定书原文明载值"),
        fact("F11", "江苏舜天处罚链", "行政处罚决定书文号", "〔2024〕41号", "text", [decision_no],
             critical=True, note="决定书文号；与告知书〔2023〕37号严格区分，混淆即事实失败"),
        fact("F12", "江苏舜天处罚链", "事先告知书文号", "〔2023〕37号", "text", [notice_no],
             note="拟处罚阶段文号，date 语义=2023 年告知"),
        fact("F13", "江苏舜天", "立案告知书收到日期", "2022-11-04", "date", [filing],
             date_type="receipt", note="date_type=receipt，非公告日非决定日；含编号 0382022008"),
        fact("F14", "江苏舜天处罚案", "听证会举行日期", "2023-10-17", "date", [hearing],
             date_type="hearing", note="程序日期类型：听证"),
        fact("F15", "江苏舜天处罚案", "当事人撤回听证及陈述申辩日期", "2024-03-22", "date", [withdraw],
             date_type="withdrawal", note="程序日期类型：撤回"),
        fact("F16", "高松", "市场禁入（拟）", "证券市场禁入", "text", [ban, ban_final],
             evidence_mode="ALL", note="告知书拟对高松市场禁入；公司公告确认收到《市场禁入决定书》——D1/D3 跨文档汇合"),
    ]

    question = (
        "江苏舜天信息披露违法违规案：各当事人（公司与个人）分别被处以多少罚款？合计多少？"
        "2009-2021 年年度报告虚增的营业收入、营业成本、利润总额各是多少？"
        "行政处罚决定书与事先告知书的文号分别是什么？立案、听证、撤回申辩各发生在什么日期？"
        "是否对高松实施市场禁入？"
    )
    contract = {
        "task_id": "MVR1_SHUNTIAN_PENALTY_CHAIN_v1",
        "reference_type": "MVR_v1",
        "governance": (
            "Machine-Verifiable Reference (Route B, operator approval 2026-10-30). "
            "NOT human Gold; results are reported as Q_MVR observables (dimensions + "
            "critical gate + fact metrics); Q_final deliberately NULL (relevance "
            "unassessed). No LLM participates in the reference side."
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
            {"item_id": "U1",
             "description": "当事人陈述申辩意见的具体内容（决定书仅载程序，未载意见细节）",
             "expected_status": "UNKNOWN"},
            {"item_id": "U2",
             "description": "2009-2021 逐年度虚增明细（本合同不要求，如答案展开则以原文为准核验）",
             "expected_status": "UNKNOWN"},
        ],
        "conflict_groups": [],
        "source_pages": sources,
        "provenance": {
            "D1": {"file": "st_advance_notice_2023.html", "sha256": raw_sha["D1"],
                    "nature": "公司公告（上海证券交易所披露）转发《行政处罚及市场禁入事先告知书》〔2023〕37号主要内容"},
            "D2": {"file": "csrc_penalty_2024_41.html", "sha256": raw_sha["D2"],
                    "nature": "中国证监会《行政处罚决定书》〔2024〕41号原文（证监会官网）"},
            "D3": {"file": "st_announce_2024_020.pdf", "sha256": raw_sha["D3"],
                    "nature": "公司公告 临2024-020：收到《行政处罚决定书》及《市场禁入决定书》"},
            "D4": {"file": "st_announce_2024_021.pdf", "sha256": raw_sha["D4"],
                    "nature": "公司公告：处罚进展/缴纳等（引用〔2024〕41号）"},
            "extraction": EXTRACTION_NOTE,
            "deterministic": True,
            "model_calls": 0,
            "built_by": "ZCode (machine-anchored), 2026-10-30, per Route B approval",
        },
    }
    return contract


def main() -> int:
    contract = build()
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "TASK_CONTRACT_MVR1_v1.json"
    target.write_text(json.dumps(contract, ensure_ascii=False, indent=1), encoding="utf-8")
    print("WROTE", target)
    print("facts:", len(contract["required_facts"]),
          "| critical:", [f["fact_id"] for f in contract["required_facts"] if f["critical"]])
    print("sha256:", hashlib.sha256(target.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
