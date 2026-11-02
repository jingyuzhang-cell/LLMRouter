#!/usr/bin/env python3
"""Phase-2 (Gate step-3) fact contracts for E04-zhuoran and E06-huanrui.

Frozen BEFORE any model call (operator ruling 2026-10-31: reference facts may
not be modified based on model outputs). Anchors verified against source text.
E06 signed arithmetic per operator ruling: 归母−扣非 = −12500−(−12300) = −200万
(signed fact) AND the announcement's magnitude wording "约200.00万元" as a
separate text fact — both frozen, no ambiguity.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pymupdf

DOCS = Path("/root/capital_opinion_pilot/benchmark_v1/docs")
OUT = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2")
EFILES = {
    "E04": {"D1": "E04-zhuoran.pdf", "D2": "E04-zhuoran_sup2.pdf", "D3": "E04-zhuoran_sup1.pdf"},
    "E06": {"D1": "E06-huanrui.pdf", "D2": "E06-huanrui_sup2.pdf"},
}


def load_docs(files):
    sources = {}
    for doc_id, fn in files.items():
        raw = hashlib.sha256((DOCS / fn).read_bytes()).hexdigest()
        doc = pymupdf.open(DOCS / fn)
        pages = {}
        for i, page in enumerate(doc, start=1):
            t = page.get_text("text")
            pages[str(i)] = {"text": t, "page_sha256": hashlib.sha256(t.encode()).hexdigest()}
        sources[doc_id] = {"raw_sha256": raw, "pages": pages}
    return sources


def make_locator(sources):
    def norm(s):
        return "".join(ch for ch in str(s) if not ch.isspace())

    def locate(doc_id, quote):
        for page_no, rec in sources[doc_id]["pages"].items():
            n_text = norm(rec["text"])
            q = norm(quote)
            idx = n_text.find(q)
            if idx >= 0:
                # map normalized idx back via cumulative walk
                cnt = -1
                for pos, ch in enumerate(rec["text"]):
                    if not ch.isspace():
                        cnt += 1
                        if cnt == idx:
                            start = pos
                        if cnt == idx + len(q) - 1:
                            end = pos + 1
                            return {"doc_id": doc_id, "page": int(page_no),
                                    "quote": rec["text"][start:end],
                                    "raw_sha256": sources[doc_id]["raw_sha256"],
                                    "page_sha256": rec["page_sha256"],
                                    "start": start, "end": end}
        raise AssertionError(f"anchor not found in {doc_id}: {quote[:36]}")
    return locate


def fact(fid, subject, predicate, value, kind, evid, *, critical=False, unit=None,
         date_type=None, derivation=None, evidence_mode=None, note=""):
    f = {"fact_id": fid, "status": "GOLD_CONFIRMED",
         "gold_provenance": "official_structured_record",
         "gold_source_sha256": evid[0]["raw_sha256"], "weight": 1.0,
         "critical": critical, "evidence_required": True,
         "value_kind": kind, "subject": subject, "predicate": predicate, "value": value,
         "source_evidence": evid, "description": note}
    if unit is not None:
        f["unit"] = unit
    if date_type is not None:
        f["date_type"] = date_type
    if derivation is not None:
        f["derivation"] = derivation
    if evidence_mode is not None:
        f["evidence_mode"] = evidence_mode
    return f


def build_e04():
    src = load_docs(EFILES["E04"])
    loc = make_locator(src)
    facts = []
    # 原文金额带千分位逗号；锚串用逗号形式，事实值用无逗号形式
    matrix = [
        ("M1", "2021", "虚增利润总额", "4383.65", "4,383.65", "12.96"),
        ("M2", "2022", "虚增利润总额", "1372.33", "1,372.33", "6.73"),
        ("M3", "2023", "虚增营业收入", "36256.34", "36,256.34", "12.25"),
        ("M4", "2023", "虚增利润总额", "22429.51", "22,429.51", "148.33"),
        ("M5", "2024", "虚增营业收入", "23142.16", "23,142.16", "8.15"),
        ("M6", "2024", "虚增利润总额", "556.72", "556.72", "5.13"),
    ]
    spans = {}
    for fid, year, pred, val, val_c, pct in matrix:
        spans[fid] = loc("D2", f"虚增{ '营业收入' if '营业收入' in pred else '利润总额'}{val_c}万元")
        spans[fid + "p"] = loc("D2", f"占当期报告记载{ '营业收入' if '营业收入' in pred else '利润总额'}的{pct}%")
    for fid, year, pred, val, val_c, pct in matrix:
        facts.append(fact(fid, f"卓然{year}年年度报告", pred, val, "amount", [spans[fid]],
                          critical=(fid == "M4"), unit="万元",
                          note=f"{year}年报{pred}（来自沪证监处罚字[2026]11号事先告知书认定）"))
        facts.append(fact(fid + "p", f"卓然{year}年年度报告", f"{pred}占当期记载比例", pct, "percent",
                          [spans[fid + "p"]], unit="%", note="占比，percent"))
    facts.append(fact("DV1", "卓然2021-2022年报", "虚增利润总额合计", "5755.98", "amount",
                      [spans["M1"], spans["M2"]], unit="万元",
                      derivation={"op": "add", "inputs": ["M1", "M2"]}, evidence_mode="ALL",
                      note="算术派生：M1+M2（原文未载合计）"))
    facts.append(fact("DV2", "卓然2023-2024年报", "虚增营业收入合计", "59398.50", "amount",
                      [spans["M3"], spans["M5"]], unit="万元",
                      derivation={"op": "add", "inputs": ["M3", "M5"]}, evidence_mode="ALL",
                      note="算术派生：M3+M5"))
    facts.append(fact("DV3", "卓然2021-2024年报", "虚增利润总额合计", "28742.21", "amount",
                      [spans["M1"], spans["M2"], spans["M4"], spans["M6"]], critical=True, unit="万元",
                      derivation={"op": "add", "inputs": ["M1", "M2", "M4", "M6"]}, evidence_mode="ALL",
                      note="算术派生：四年利润之和"))
    facts += [
        fact("T1", "卓然股票", "2026-10-12收盘价", "0.96", "number", [loc("D3", "2026年10月12日收盘价格0.96元/股")],
             critical=True, unit="元/股", note="价格线：首次低于1元"),
        fact("T2", "卓然股票", "2026-10-12总市值", "2.24", "number", [loc("D3", "总市值2.24亿元")],
             critical=True, unit="亿元", note="与T1同日"),
        fact("T3", "卓然股票", "2026-09-23收盘价", "1.16", "number", [loc("D3", "2026年9月23日收盘价格1.16元/股")],
             critical=True, unit="元/股", note="市值线当日股价（注意仍高于1元）"),
        fact("T4", "卓然股票", "2026-09-23总市值", "2.71", "number", [loc("D3", "总市值2.71亿元")],
             critical=True, unit="亿元", note="首次市值低于3亿元当日"),
        fact("T5", "卓然股票", "收盘市值低于3亿元的连续交易日数(截至公告)", "8", "number",
             [loc("D3", "已连续8个交易日每日股票收盘市值低于3亿元")], unit="个交易日"),
        fact("T6", "卓然股票", "交易类强制退市的连续低于阈值交易日数", "20", "number",
             [loc("D3", "连续20个交易日每日股票收盘价格均低于1元")], unit="个交易日",
             note="12.3.1规则阈值（价格线与市值线均为20日）"),
        fact("DT1", "卓然及实控人", "立案告知书收到日期", "2025-12-19", "date",
             [loc("D2", "2025 年12 月19 日收到中国证券监督管理委员会")],
             critical=True, date_type="receipt", note="收到日≠披露日（DT2）"),
        fact("DT2", "卓然", "立案公告披露日期", "2025-12-20", "date",
             [loc("D1", "披露了《关于公司及实际控制人收到立案告知书的公告》（公告编号：2025-053）")],
             critical=True, date_type="publication", note="公告编号2025-053"),
        fact("DT3", "卓然", "行政处罚事先告知书收到日期", "2026-09-11", "date",
             [loc("D2", "2026 年9 月11 日，公司收到上海证监局下发的《行政处罚事先告知书》")], date_type="receipt"),
        fact("DT4", "卓然股票", "收盘价首次低于1元日期", "2026-10-12", "date",
             [loc("D3", "2026年10月12日收盘价格0.96元/股")], date_type="first_below_1yuan"),
        fact("DT5", "卓然股票", "总市值首次低于3亿元日期", "2026-09-23", "date",
             [loc("D3", "2026年9 月23 日首次出现股票收盘市值低于3亿元")], date_type="first_below_300m"),
        fact("ID1", "卓然处罚链", "立案告知书编号一", "证监立案字0032025031号", "text",
             [loc("D2", "证监立案字0032025031 号")], note="双编号对应公司及实控人，归属未分列"),
        fact("ID2", "卓然处罚链", "立案告知书编号二", "证监立案字0032025032号", "text",
             [loc("D2", "证监立案字0032025032 号")]),
        fact("ID3", "卓然处罚链", "行政处罚事先告知书文号", "沪证监处罚字[2026]11号", "text",
             [loc("D2", "沪证监处罚字[2026]11号")], critical=True, note="发文机关=上海证监局（地方局），非证监会本部"),
        fact("S1", "卓然立案", "立案对象", "公司及实际控制人张锦红", "text",
             [loc("D2", "决定对公司及实际控制人张锦红立案")], critical=True),
        fact("S2", "张锦红", "时任职务", "董事长", "text",
             [loc("D2", "实际控制人、时任董事长张锦红两次被监察机关留置")], note="实控人+时任董事长"),
        fact("S3", "卓然立案", "立案涉嫌事项", "信息披露违法违规", "text",
             [loc("D1", "因涉嫌信息披露违法违规等事项")]),
        fact("O1", "卓然信息披露", "重大遗漏事项一", "招股说明书和2021年年度报告未披露关联交易", "text",
             [loc("D2", "公司招股说明书和2021 年年度报告未披露关联交易，存在重大遗漏")]),
        fact("O2", "卓然信息披露", "重大遗漏事项二", "未及时披露非经营性资金占用相关关联交易（2022-2024年报亦未披露）", "text",
             [loc("D2", "未及时披露非经营性资金占用相关关联交易，2022 年至2024 年年度报告亦未披露上述事项")]),
        fact("O3", "卓然信息披露", "重大遗漏事项三", "未及时披露张锦红两次被监察机关留置（2024年报亦未披露）", "text",
             [loc("D2", "未及时披露实际控制人、时任董事长张锦红两次被监察机关留置事项，2024 年年度报告亦未披露该重大事项")]),
        fact("R1", "卓然退市风险", "可能触及的重大违法情形规则", "12.2.1条第一项、12.2.2条第六项", "text",
             [loc("D3", "第12.2.1条第（一）项、第12.2.2条第（六）项规定的重大违法行为")]),
    ]
    question = ("上海卓然：证监会立案的对象与编号？事先告知书文号与收到日期？2021-2024 各年年度报告虚增的营业收入/利润总额"
                "及占比分别是多少？分年与四年合计是多少？股价与市值两条退市线各自的关键日期、价格、市值、连续交易日数与"
                "规则阈值？立案收到日与公告披露日各是哪天？认定了哪些重大遗漏？")
    return {"task_id": "PHASE2_E04_ZHUORAN_v1", "reference_type": "MVR_v1",
            "question": question, "cutoff": "2026-10-31", "min_gold_coverage": 1.0,
            "dimension_weights": {k: 1 for k in ("fact_correctness", "evidence_support", "necessary_completeness",
                                                 "contradiction_handling", "unverifiable_refusal", "question_relevance")},
            "required_facts": facts, "unknown_items": [
                {"item_id": "U1", "description": "事先告知书拟处罚金额（本轮文档未载明）", "expected_status": "UNKNOWN"}],
            "conflict_groups": [], "source_pages": src,
            "provenance": {"nature": "公司公告3份（080/097/098），哈希沿用冻结manifest", "model_calls": 0,
                           "built_by": "ZCode, frozen before step-3 calls per operator ruling 2026-10-31"}}


def build_e06():
    src = load_docs(EFILES["E06"])
    loc = make_locator(src)
    facts = [
        fact("G1", "欢瑞世纪2026半年度", "归母净利润(预告,带符号)", "-12500", "amount",
             [loc("D2", "亏损：12,500.00 万元")], critical=True, unit="万元", note="负值=亏损；本期"),
        fact("G2", "欢瑞世纪2025半年度", "归母净利润(上年同期,带符号)", "-639.38", "amount",
             [loc("D2", "亏损：639.38 万元")], unit="万元", note="上年同期"),
        fact("G3", "欢瑞世纪2026半年度", "扣非净利润(预告,带符号)", "-12300", "amount",
             [loc("D2", "亏损：12,300.00 万元")], unit="万元"),
        fact("G4", "欢瑞世纪2025半年度", "扣非净利润(上年同期,带符号)", "-2187.21", "amount",
             [loc("D2", "亏损：2,187.21 万元")], unit="万元"),
        fact("G5", "欢瑞世纪2026半年度", "基本每股收益(预告,带符号)", "-0.13", "number",
             [loc("D2", "亏损：0.13 元/股")], unit="元/股"),
        fact("G6", "欢瑞世纪2026半年度", "营业收入(预告)", "24500", "amount",
             [loc("D2", "24,500.00 万元")], unit="万元"),
        fact("G7", "欢瑞世纪2025半年度", "营业收入(上年同期)", "19804.88", "amount",
             [loc("D2", "19,804.88 万元")], unit="万元"),
        fact("DV1", "欢瑞世纪2026半年度", "归母净利润−扣非净利润(带符号)", "-200", "amount",
             [loc("D2", "亏损：12,500.00 万元"), loc("D2", "亏损：12,300.00 万元")], critical=True, unit="万元",
             derivation={"op": "subtract", "inputs": ["G1", "G3"]}, evidence_mode="ALL",
             note="带符号口径：−12500−(−12300)=−200（非经常性损益为损失方向）——操作者2026-10-31裁定"),
        fact("DV2", "欢瑞世纪2026半年度", "非经常性损益影响金额（公告原文表述）", "约200.00万元", "text",
             [loc("D2", "影响金额约为200.00 万元")],
             note="原文幅度表述（不带符号）；与DV1带符号口径分立，两事实各自成立"),
        fact("DV3", "欢瑞世纪", "归母亏损扩大倍数(本期/上年同期)", "19.55", "number",
             [loc("D2", "亏损：12,500.00 万元"), loc("D2", "亏损：639.38 万元")], unit="倍",
             derivation={"op": "ratio", "inputs": ["G1", "G2"]}, evidence_mode="ALL",
             note="双负相除=正倍数；tolerance 0.05"),
        fact("DV4", "欢瑞世纪2026半年度", "营业收入同比变化率", "23.70", "percent",
             [loc("D2", "24,500.00 万元"), loc("D2", "19,804.88 万元")], unit="%",
             derivation={"op": "percent_change", "inputs": ["G6", "G7"]}, evidence_mode="ALL",
             note="(24500−19804.88)/19804.88×100；tolerance 0.05"),
        fact("H1", "欢瑞世纪", "立案告知书收到日期", "2026-04-21", "date",
             [loc("D1", "2026年4月21日收到中国证券监督管理委员会对公司的《立案告知书》")],
             critical=True, date_type="receipt", note="收到日≠公告日（H2）"),
        fact("H2", "欢瑞世纪", "立案公告披露日期(落款)", "2026-04-22", "date",
             [loc("D1", "2026 年4 月22 日")], critical=True, date_type="publication"),
        fact("H3", "欢瑞世纪立案", "立案告知书编号", "证监立案字0152026005号", "text",
             [loc("D1", "证监立案字0152026005号")]),
        fact("H4", "欢瑞世纪立案", "涉嫌事项", "2022年计提加计抵减额并确认为其他收益", "text",
             [loc("D1", "本次立案涉及2022年计提加计抵减额并确认为其他收益事项")]),
        fact("H5", "欢瑞世纪立案", "立案对象", "公司（非实际控制人）", "text",
             [loc("D1", "收到中国证券监督管理委员会对公司的《立案告知书》")], note="主体：公司本身"),
        fact("H6", "欢瑞世纪", "业绩预告公告日期(落款)", "2026-07-14", "date",
             [loc("D2", "2026 年7 月14 日")], date_type="publication", note="晚于立案(H1)——时间序核验点"),
    ]
    question = ("欢瑞世纪：2026半年度业绩预告中归母净利润、扣非净利润、基本每股收益、营业收入各为多少（本期与上年同期，"
                "注意符号）？归母与扣非之差（带符号）多少、公告原文对非经常性损益影响金额如何表述？亏损较上年同期扩大"
                "多少倍？营收同比变化率多少？立案告知书何时收到、编号、对象与涉嫌事项？立案公告与业绩预告各于何日披露？")
    return {"task_id": "PHASE2_E06_HUANRUI_v1", "reference_type": "MVR_v1",
            "question": question, "cutoff": "2026-10-31", "min_gold_coverage": 1.0,
            "dimension_weights": {k: 1 for k in ("fact_correctness", "evidence_support", "necessary_completeness",
                                                 "contradiction_handling", "unverifiable_refusal", "question_relevance")},
            "required_facts": facts, "unknown_items": [], "conflict_groups": [], "source_pages": src,
            "provenance": {"nature": "公司公告2份（023立案/041业绩预告），哈希沿用冻结manifest", "model_calls": 0,
                           "built_by": "ZCode, frozen before step-3 calls per operator ruling 2026-10-31"}}


def main():
    from decimal import Decimal as D
    assert D("4383.65") + D("1372.33") == D("5755.98")
    assert D("36256.34") + D("23142.16") == D("59398.50")
    assert D("4383.65") + D("1372.33") + D("22429.51") + D("556.72") == D("28742.21")
    assert D("-12500") - D("-12300") == D("-200")
    assert abs(D("-12500") / D("-639.38") - D("19.55")) < D("0.01")
    assert abs((D("24500") - D("19804.88")) / D("19804.88") * 100 - D("23.70")) < D("0.01")
    OUT.mkdir(parents=True, exist_ok=True)
    for tid, builder in (("E04", build_e04), ("E06", build_e06)):
        c = builder()
        p = OUT / f"TASK_CONTRACT_PHASE2_{tid}_v1.json"
        p.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
        print(tid, "facts:", len(c["required_facts"]),
              "critical:", [f["fact_id"] for f in c["required_facts"] if f["critical"]],
              "sha256:", hashlib.sha256(p.read_bytes()).hexdigest())


if __name__ == "__main__":
    sys.exit(main())
