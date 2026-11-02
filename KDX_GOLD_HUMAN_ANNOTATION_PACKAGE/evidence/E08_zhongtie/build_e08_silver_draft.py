#!/usr/bin/env python3
"""Build the first SILVER draft task contract for Track B (capital-market fact-level Gold).

Deterministic, zero model calls. Extracts E08-zhongtie.pdf page text (pymupdf),
verifies raw sha256 against the frozen benchmark manifest, locates each fact's
quote span by exact substring match, and emits:
  - source_pages.json            (hash-bound page texts for the evaluator)
  - TASK_CONTRACT_E08_SILVER_DRAFT.json  (SILVER facts, pending dual human review)
  - FACT_SHEET_E08.md            (human-reviewer-facing verification sheet)

All facts are SILVER_SOURCE_ANCHORED. No GOLD is claimed anywhere: per the Q
Foundation governance plan, GOLD requires two independent blind human reviewers
plus adjudication. `critical` flags are PROPOSALS frozen only at contract freeze.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pymupdf

REPO = Path("/root")
DOCS = REPO / "capital_opinion_pilot/benchmark_v1/docs"
MANIFEST = REPO / "capital_opinion_pilot/benchmark_v1/verified_docs_manifest.json"
OUT = REPO / "KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/E08_zhongtie"
DOC_ID = "E08-zhongtie"
PDF = DOCS / "E08-zhongtie.pdf"

CUTOFF = "2026-10-30"
EXTRACTION_TOOL = "pymupdf 1.28.2 page.get_text('text')"


def main() -> int:
    raw_sha = hashlib.sha256(PDF.read_bytes()).hexdigest()
    manifest = json.loads(MANIFEST.read_text())
    # pool_id is NOT unique in the manifest (a company contributes several
    # announcements); identify the entry by the file hash itself.
    matches = [d for d in manifest if d.get("sha256") == raw_sha]
    assert len(matches) == 1, f"expected exactly one manifest entry for sha256, got {len(matches)}"
    entry = matches[0]
    assert "立案告知书" in entry["title"], f"unexpected document: {entry['title']}"

    doc = pymupdf.open(PDF)
    pages = {}
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        pages[str(i)] = {"text": text, "page_sha256": hashlib.sha256(text.encode()).hexdigest()}

    page1 = pages["1"]["text"]

    def locate(quote: str):
        # Whitespace-flexible search mapped back to exact raw offsets: PDF line
        # breaks fall inside sentences, and the evaluator's _norm_text strips
        # whitespace on both sides, so store the raw substring at raw offsets.
        def norm_with_map(s: str):
            out, mapping = [], []
            for i, ch in enumerate(s):
                if ch.isspace():
                    continue
                out.append(ch)
                mapping.append(i)
            return "".join(out), mapping

        n_page, m_page = norm_with_map(page1)
        n_quote, _ = norm_with_map(quote)
        idx = n_page.find(n_quote)
        assert idx >= 0, f"quote not found (normalized): {quote[:30]}"
        start = m_page[idx]
        end = m_page[idx + len(n_quote) - 1] + 1
        return {"doc_id": DOC_ID, "page": 1, "quote": page1[start:end],
                "raw_sha256": raw_sha, "page_sha256": pages["1"]["page_sha256"],
                "start": start, "end": end}

    silver = "SILVER_SOURCE_ANCHORED"
    review_pending = {
        "status": "PENDING_DUAL_BLIND_REVIEW",
        "independent_reviewers_required": 2,
        "reviewer_ids": [],
        "blind_to_model": True,
        "blind_to_strategy": True,
        "adjudication_rule": "C9-human-judge-calibration-v1: third adjudicator after >1 disagreement; <=1 rounded mean, halves toward conservative lower",
    }

    def fact(fid, subject, predicate, value, kind, quote, critical=False, note="", **extra):
        f = {
            "fact_id": fid, "status": silver, "gold_provenance": "official_structured_record",
            "gold_source_sha256": raw_sha, "review": dict(review_pending),
            "weight": 1.0, "critical_proposed": critical, "critical": False,
            "value_kind": kind, "subject": subject, "predicate": predicate, "value": value,
            "description": note,
            "source_evidence": [locate(quote)],
        }
        f.update(extra)
        return f

    facts = [
        fact("F1", "中铁装配式建筑股份有限公司", "证券代码", "300374", "text",
             "证券代码：300374", note="公司主体证券代码（六位数字字符串，按文本核验）"),
        fact("F2", "中铁装配式建筑股份有限公司", "证券简称", "中铁装配", "text",
             "证券简称：中铁装配", note="简称与全称的主体绑定；回答仅用简称须能唯一指代全称主体"),
        fact("F3", "中铁装配式建筑股份有限公司", "本公告编号", "2026-037", "text",
             "公告编号：2026-037", note="公告编号，非处罚文书编号"),
        fact("F4", "中铁装配式建筑股份有限公司", "收到立案告知书日期", "2026-09-18", "date",
             "于2026 年9 月18 日收\n到中国证券监督管理委员会", critical=True,
             unit="date", date_type="receipt",
             note="收件日（receipt），不是公告日、不是发文日、更不是处罚决定日"),
        fact("F5", "中铁装配式建筑股份有限公司", "立案告知书发文机关", "中国证券监督管理委员会", "text",
             "中国证券监督管理委员会（以下简称“中国证监会”）下发的《立案告知书》",
             note="发文机关为证监会本部（告知书编号前缀'证监立案字'佐证），非地方证监局"),
        fact("F6", "中铁装配式建筑股份有限公司", "立案告知书编号", "证监立案字0142026049号", "text",
             "（编号：证监立案字0142026049 号）", critical=True,
             note="告知书唯一标识；注意PDF提取文本中'0142026049 号'含空格属版式，归一化后无空格"),
        fact("F7", "中铁装配式建筑股份有限公司", "立案原因（涉嫌事项）", "涉嫌信息披露违法违规", "text",
             "因公司涉嫌信息披露违法违规", critical=True,
             note="立案时点为'涉嫌'，不构成违法违规的最终认定；不得表述为'因信息披露违法违规被处罚'"),
        fact("F8", "中铁装配式建筑股份有限公司", "立案对象", "中铁装配式建筑股份有限公司（公司本身）", "text",
             "中国证监会\n决定对公司立案", critical=True,
             note="主体关系核验点：立案对象是公司本身，不是实际控制人、不是董监高个人（对照E10/E10b为实控人收告知书）"),
        fact("F9", "中铁装配式建筑股份有限公司", "自查所述立案涉及业务时点", "实际控制人变更前开展的相关业务（公司自查表述为'可能涉及'）", "text",
             "本次立案可能涉及公司实际控制人变更前开展的相关业务",
             note=" Hedged 主张：原文为'可能涉及'，回答不得去掉不确定性限定词"),
        fact("F10", "中铁装配式建筑股份有限公司", "最终调查结论收取状态（截至公告日）", "尚未收到", "text",
             "目前，公司尚未收到中国证监\n会的最终调查结论",
             note="立案调查≠已处罚；截至公告日无最终结论"),
    ]

    contract = {
        "task_id": "CM_E08_001_SILVER_DRAFT",
        "status": "SILVER_DRAFT_PENDING_HUMAN_CONFIRMATION",
        "question": "中铁装配是否收到中国证监会立案告知书？何时收到？告知书编号是多少？因何种原因对公司立案？立案对象是谁？截至公告日是否已有最终调查结论？",
        "cutoff": CUTOFF,
        "doc_pool_id": DOC_ID,
        "company": entry["company"],
        "min_gold_coverage": 1.0,
        "dimension_weights": {
            "fact_correctness": 1, "evidence_support": 1, "necessary_completeness": 1,
            "contradiction_handling": 1, "unverifiable_refusal": 1, "question_relevance": 1,
        },
        "required_facts": facts,
        "optional_facts": [
            {"fact_id": "O1", "description": "实际控制人变更后公司已停止该类业务并改革治理（公告第2条）",
             "source_evidence": [locate("变更后，公司已按相关规定停止开展该类业务")]},
        ],
        "unknown_items": [
            {"item_id": "U1", "description": "最终调查/处罚结论及其金额、责任认定（截至 cutoff 证据无法确认；立案≠处罚）",
             "expected_status": "UNKNOWN"},
        ],
        "conflict_groups": [],
        "source_pages": {DOC_ID: {"raw_sha256": raw_sha, "pages": pages}},
        "provenance": {
            "source_url": entry["url"],
            "source_title": entry["title"],
            "source_date": entry["date"],
            "frozen_manifest": "capital_opinion_pilot/benchmark_v1/verified_docs_manifest.json",
            "raw_sha256_verified_against_manifest": True,
            "extraction_tool": EXTRACTION_TOOL,
            "extraction_is_deterministic": True,
            "model_calls": 0,
            "drafted_by": "ZCode (machine-located), 2026-10-30",
            "human_confirmation": "NONE_YET — GOLD only after two independent blind reviewers + adjudication per Q Foundation governance",
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "source_pages.json").write_text(
        json.dumps({DOC_ID: {"raw_sha256": raw_sha, "pages": pages}}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (OUT / "TASK_CONTRACT_E08_SILVER_DRAFT.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [
        "# E08-中铁装配 事实核验单（SILVER 草案 · 待双人盲审）",
        "",
        f"- 来源公告：{entry['title']}（{entry['date']}，cninfo {entry['url']}）",
        f"- 原始文件 sha256：`{raw_sha}`（已对冻结 manifest 核验一致）",
        f"- 页1文本 sha256：`{pages['1']['page_sha256']}`（{EXTRACTION_TOOL}，确定性提取，0 模型调用）",
        f"- 状态：**SILVER_SOURCE_ANCHORED / PENDING_DUAL_BLIND_REVIEW**——人工双人确认前不得记为 GOLD。",
        "",
        "## 逐事实核验（评审者逐项核对原文跨度）",
        "",
        "| fact_id | 关键性(拟) | 主体 | 谓词 | 值 | 原文跨度（页1起止） |",
        "|---|---|---|---|---|---|",
    ]
    for f in facts:
        ev = f["source_evidence"][0]
        lines.append(f"| {f['fact_id']} | {'**是**' if f['critical_proposed'] else '否'} | {f['subject']} | {f['predicate']} | {f['value']} | [{ev['start']}:{ev['end']}] {ev['quote'][:40]}… |")
    lines += [
        "",
        "## 评审注意事项（易错点）",
        "- F4 收件日 ≠ 公告日 ≠ 处罚决定日；公告落款同为 2026-09-18，但谓词口径必须区分。",
        "- F6 编号按归一化文本核验（PDF 版式空格不影响）。",
        "- F7 '涉嫌'不得升级为认定；F9 '可能涉及'必须保留不确定性限定。",
        "- F8 立案对象是公司本身（对照 E10/E10b：实控人收告知书，主体不同）。",
        "- U1 为 UNKNOWN：任何对'最终处罚/金额'的确定性断言都按 UNKNOWN 错误断言处理。",
        "",
        "## 确认流程",
        "1. 两名评审者独立（盲模型、盲策略）逐项核对事实与跨度，填写 reviewer_ids 与逐事实结论；",
        "2. 分歧 >1 个事实点由第三裁决；",
        "3. 全部通过后：status→GOLD_CONFIRMED、critical 按 critical_proposed 冻结、合同版本冻结；",
        "4. 任何一项不通过：修正或降级为 UNKNOWN，不得带病转 GOLD。",
    ]
    (OUT / "FACT_SHEET_E08.md").write_text("\n".join(lines), encoding="utf-8")

    print("OK wrote:", OUT)
    for name in ("source_pages.json", "TASK_CONTRACT_E08_SILVER_DRAFT.json", "FACT_SHEET_E08.md"):
        p = OUT / name
        print(f"  {name}: {p.stat().st_size} bytes, sha256={hashlib.sha256(p.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
