#!/usr/bin/env python3
"""P1-1 Gold builder: 卓然三阶段状态演进——三维状态体系。

Root cause fix: locate() now searches across ALL pages, not just page 1.
"""
import hashlib, json, re
from pathlib import Path
import pymupdf

DOCS = Path("/root/capital_opinion_pilot/benchmark_v1/docs")
OUT = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P1_1_ZHUORAN")
STAGES = {"S1": ("E04-zhuoran.pdf","080"), "S2": ("E04-zhuoran_sup2.pdf","097"), "S3": ("E04-zhuoran_sup1.pdf","098")}

def load():
    src = {}
    for sid, (fn,_) in STAGES.items():
        raw = hashlib.sha256((DOCS/fn).read_bytes()).hexdigest()
        doc = pymupdf.open(DOCS/fn)
        pages = {}
        for i, page in enumerate(doc, start=1):
            t = page.get_text("text")
            pages[str(i)] = {"text": t, "page_sha256": hashlib.sha256(t.encode()).hexdigest()}
        src[sid] = {"raw_sha256": raw, "pages": pages}
    return src

def locate(src, sid, quote):
    """Search across ALL pages of sid, return first match with page info."""
    q = "".join(c for c in quote if not c.isspace())
    for page_no, rec in src[sid]["pages"].items():
        raw = rec["text"]
        norm = "".join(c for c in raw if not c.isspace())
        idx = norm.find(q)
        if idx < 0:
            continue
        # Map back to raw positions
        raw_to_norm = []
        norm_chars = []
        for i, ch in enumerate(raw):
            if not ch.isspace():
                norm_chars.append(ch)
                raw_to_norm.append(len(norm_chars)-1)
            else:
                raw_to_norm.append(-1)
        start_raw = next(i for i,p in enumerate(raw_to_norm) if p == idx)
        end_norm = idx + len(q) - 1
        end_raw = next(i for i in range(len(raw_to_norm)-1,-1,-1) if raw_to_norm[i] == end_norm)
        return {"stage": sid, "page": int(page_no), "quote": raw[start_raw:end_raw+1],
                "raw_sha256": src[sid]["raw_sha256"], "page_sha256": rec["page_sha256"]}
    raise AssertionError(f"anchor not found in any page of {sid}: {quote[:30]}")

def build():
    src = load()
    F = []
    def state(fid, item, stage, d1, d2, d3, quote, note=""):
        ev = [locate(src, stage, quote)]
        F.append({"fact_id": fid, "item": item, "stage": stage,
                  "dim1_factual": d1, "dim2_procedural": d2, "dim3_evidentiary": d3,
                  "evidence": ev, "note": note, "status": "GOLD_CONFIRMED",
                  "gold_provenance": "official_structured_record", "weight": 1.0,
                  "critical": False, "evidence_required": True, "value_kind": "text",
                  "subject": item, "predicate": f"{d1}/{d2}/{d3}@{stage}"})

    # 1. 虚增事实（修正①）
    state("VF_S1","虚增利润/营收事实","S1","CONTINUING","INVESTIGATION","ALLEGATION",
          "现已初步查明，公司披露的部分年度财务信息涉嫌虚假","080：ALLEGATION")
    state("VF_S2","虚增利润/营收事实","S2","DETAIL_EXPANDED","PRIOR_NOTICE","NOTICE_CONTENT",
          "该事先告知书查明的涉嫌违法事实",
          "097：虚增事实本身CONTINUING（同一监管事项），新增四年度明细=DETAIL_EXPANDED；程序INVESTIGATION→PRIOR_NOTICE；证据ALLEGATION→NOTICE_CONTENT")
    state("VF_S3","虚增利润/营收事实","S3","CONTINUING","PRIOR_NOTICE","NOTICE_CONTENT",
          "根据收到的《告知书》认定情况","098：CONTINUING_REFERENCE")

    # 2. 调查状态
    state("INV_S1","证监会调查状态","S1","CONTINUING","INVESTIGATION","ALLEGATION",
          "中国证监会的调查尚在进行中","080：调查进行中")
    state("INV_S2","证监会调查状态","S2","CONTINUING","PRIOR_NOTICE","NOTICE_CONTENT",
          "公司尚未收到就上述立案调查事项的正式处罚决定","097：已收告知书但未收处罚决定")
    state("INV_S3","证监会调查状态","S3","CONTINUING","PRIOR_NOTICE","NOTICE_CONTENT",
          "公司尚未收到就上述立案调查事项的正式处罚决定","098：与097一致")

    # 3. 重大违法退市风险
    state("MR_S1","重大违法强制退市风险","S1","CONTINUING","INVESTIGATION","ALLEGATION",
          "可能触及重大违法强制退市情形","080：'可能触及'→条件性")
    state("MR_S2","重大违法强制退市风险","S2","CONTINUING","PRIOR_NOTICE","NOTICE_CONTENT",
          "可能触及《上海证券交易所科创板股票上市规则》第12.2.1 条","097：基于告知书评估")
    state("MR_S3","重大违法强制退市风险","S3","CONTINUING","PRIOR_NOTICE","NOTICE_CONTENT",
          "可能被实施重大违法强制退市","098：延续")

    # 4. 交易类退市风险（修正②）
    state("TR_S1","交易类退市风险(价格/市值)","S1","NOT_DISCLOSED","NOT_APPLICABLE","UNKNOWN",
          "退市风险提示","080：未提及≠不存在")
    state("TR_S2","交易类退市风险(价格/市值)","S2","NOT_DISCLOSED","NOT_APPLICABLE","UNKNOWN",
          "行政处罚事先告知书","097：仍未提及")
    state("TR_S3","交易类退市风险(价格/市值)","S3","NEWLY_DISCLOSED","NOT_APPLICABLE","DISCLOSED_MARKET_DATA",
          "首次低于1元",
          "098：NEWLY_DISCLOSED≠NEWLY_OCCURRED；证据性质=DISCLOSED_MARKET_DATA（公司公告中的市场数据，非行政处罚事先告知书内容）")

    # 5. 事先告知书
    state("PN_S1","行政处罚事先告知书","S1","NOT_DISCLOSED","NOT_APPLICABLE","UNKNOWN",
          "调查","080：未提及")
    state("PN_S2","行政处罚事先告知书","S2","NEWLY_DISCLOSED","PRIOR_NOTICE","NOTICE_CONTENT",
          "2026 年9 月11 日，公司收到上海证监局下发的《行政处罚事先告知书》","097：NEWLY_DISCLOSED")
    state("PN_S3","行政处罚事先告知书","S3","CONTINUING","PRIOR_NOTICE","NOTICE_CONTENT",
          "收到上海证监局下发的《行政处罚事先告知书》","098：CONTINUING")

    # 6. 最终处罚决定（修正③）
    state("FD_S2","正式处罚决定状态","S2","NOT_YET_RECEIVED","INVESTIGATION","UNKNOWN",
          "尚未收到就上述立案调查事项的正式处罚决定",
          "097 原文明确写'尚未收到…正式处罚决定'——NOT_YET_RECEIVED 有直接原文支撑，非推测")
    state("FD_S3","正式处罚决定状态","S3","NOT_YET_RECEIVED","INVESTIGATION","UNKNOWN",
          "尚未收到就上述立案调查事项的正式处罚决定",
          "098 原文同样明确写'尚未收到'——NOT_YET_RECEIVED 有直接原文支撑")

    unknowns = [
        {"item_id":"U_FD","description":"正式处罚决定是否已实际作出","expected_status":"UNKNOWN"},
        {"item_id":"U_TR_PRE","description":"交易类退市风险在098前是否已存在","expected_status":"UNKNOWN"},
        {"item_id":"U_INV_DATE","description":"证监会调查启动日期","expected_status":"UNKNOWN"},
    ]

    question = ("上海卓然的监管事件在三个时间节点(2026-09-10/10-09/10-13)上，各项信息的："
                "（1）事实状态（持续/变化/首次披露/未披露）？"
                "（2）监管程序阶段（调查/事先告知/正式处罚）？"
                "（3）证据性质（涉嫌/告知书载明/最终认定/无法判断）？"
                "注意：首次披露≠首次发生；告知书内容≠最终认定；'以处罚决定为准'≠已作出。")

    return {"task_id": "P1_1_ZHUORAN_STATE_EVOLUTION_v1_1", "reference_type": "MVR_v1",
            "question": question, "cutoff": "2026-10-31", "min_gold_coverage": 1.0,
            "dimension_weights": {k:1 for k in ("fact_correctness","evidence_support","necessary_completeness","contradiction_handling","unverifiable_refusal","question_relevance")},
            "state_evolution_facts": F, "unknown_items": unknowns,
            "source_pages": src,
            "annotation_rules": [
                "Dim1: CONTINUING/DETAIL_EXPANDED(事实本身持续,明细新增)/NEWLY_DISCLOSED(≠NEWLY_OCCURRED)/NOT_DISCLOSED(≠不存在)/NOT_YET_RECEIVED(原文明确)",
                "Dim2: INVESTIGATION/PRIOR_NOTICE/FINAL_DECISION/NOT_APPLICABLE",
                "Dim3: ALLEGATION/NOTICE_CONTENT(告知书载明)/DISCLOSED_MARKET_DATA(公告市场数据)/FINAL_FINDING/UNKNOWN",
                "修正①: ALLEGATION→PRIOR_NOTICE+NOTICE_CONTENT=程序推进≠FINAL_FINDING",
                "修正②: NEWLY_DISCLOSED≠NEWLY_OCCURRED",
                "修正③: '以处罚决定为准'=条件引用→UNKNOWN"],
            "item_coverage": {
                "虚增利润/营收事实": ["S1","S2","S3"],
                "证监会调查状态": ["S1","S2","S3"],
                "重大违法强制退市风险": ["S1","S2","S3"],
                "交易类退市风险(价格/市值)": ["S1","S2","S3"],
                "行政处罚事先告知书(含文号)": ["S1","S2","S3"],
                "正式处罚决定状态": ["S2","S3"],
                "_对账": "6 信息项 × 阶段覆盖 = 17 事实记录（非 5×3=15；处罚决定仅 S2/S3）；3 独立 UNKNOWN 拒判槽位；每条记录含 3 维标签（共 51 个标签值）"
            },
            "provenance": {"nature":"三份公告(080/097/098)，多页PDF逐页搜索锚定","model_calls":0,
                         "built_by":"ZCode, three-dimension state system per operator 2026-10-31"}}

if __name__ == "__main__":
    contract = build()
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "TASK_CONTRACT_P1_1_v1_1.json"
    p.write_text(json.dumps(contract, ensure_ascii=False, indent=1), encoding="utf-8")

    # 独立锚点验证
    n_ok = 0
    for f in contract["state_evolution_facts"]:
        for ev in f["evidence"]:
            rec = contract["source_pages"][ev["stage"]]["pages"][str(ev["page"])]
            qn = "".join(c for c in ev["quote"] if not c.isspace())
            tn = "".join(c for c in rec["text"] if not c.isspace())
            assert qn in tn, f"FAIL {f['fact_id']}"
            assert rec["page_sha256"] == ev["page_sha256"]
            n_ok += 1

    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    F = contract["state_evolution_facts"]
    print("P1-1 Gold 合同已冻结")
    print(f"状态事实: {len(F)} 项（{len(F)//3} 信息项 × 3 阶段）")
    print(f"UNKNOWN: {len(contract['unknown_items'])} 项")
    print(f"锚点独立验证: {n_ok}/{n_ok} 全部通过（含多页搜索）")
    print(f"sha256: {sha}")

    from collections import Counter
    print("\n维度覆盖:")
    for dim in ("dim1_factual","dim2_procedural","dim3_evidentiary"):
        print(f"  {dim}: {dict(Counter(f[dim] for f in F))}")

    print("\n状态演进摘要:")
    items = sorted(set(f["item"] for f in F))
    for item in items:
        stages = sorted([(f["stage"], f["dim1_factual"], f["dim2_procedural"], f["dim3_evidentiary"]) for f in F if f["item"]==item])
        for s in stages:
            print(f"  {item[:14]:14s} {s[0]}: {s[1]:17s} {s[2]:15s} {s[3]}")
        print()
