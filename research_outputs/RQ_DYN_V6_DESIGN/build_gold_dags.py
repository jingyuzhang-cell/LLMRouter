#!/usr/bin/env python3
"""P1: 48案Gold DAG批量构建器(第一阶段: 15案已有槽位表)
模式: 按案件事实线建并行extract节点(各读自己的文档/段)→B1核验汇合→C1时序/推理→D1报告
结构门禁: 最长链≥3边+真中间节点; 每案12组配对注入矩阵预验
局限声明: 槽位value为叙事短语,精确评分匹配待人工签发阶段细化(executor的数值回退可部分覆盖)
"""
import json, os, re, sys, hashlib, subprocess, glob
sys.path.insert(0, "/root/research_outputs/RQ_DYN_V6_DESIGN")
from extract_decision import extract
import importlib.util
spec = importlib.util.spec_from_file_location("iac", "injection_acceptance_check.py")
iac = importlib.util.module_from_spec(spec); spec.loader.exec_module(iac)

ST = "/root/research_outputs/RQ_DYN_V6_DESIGN/slot_tables_v1/"
RAW = "/root/research_outputs/V6_CANDIDATE_RAW/"
OUT = "/root/research_outputs/RQ_DYN_V6_DESIGN/gold_dags/"
os.makedirs(OUT, exist_ok=True)

def doc_text(path):
    if path.endswith(".html"):
        return extract(path)[1]
    if path.endswith(".pdf"):
        r = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True, timeout=180)
        return re.sub(r'\s+', ' ', r.stdout or "")
    return open(path, encoding="utf-8", errors="ignore").read()

def seg(cont, start_kw, end_kw):
    i = cont.find(start_kw); i = 0 if i < 0 else i
    j = cont.find(end_kw, i+50) if end_kw else -1
    j = min(len(cont), i+25000) if j < 0 else j
    return cont[i:j]

# 每案: 槽位表 / 文档(名→(路径,None=全文|起始锚,结束锚)) / 事实线(名,文档,起锚,止锚)
RB1 = RAW + "revise_batch1/"
B3, B4 = RAW + "batch3_new36/", RAW + "batch4_new25/"
CASES = {
 "GAOSHENG": dict(table="GAOSHENG_000971_SLOTS_V2_1.json", code="000971",
   docs={"DEC": (RB1+"gaosheng_000971/decision_2019_5.html", None, None),
         "ANNC": (RB1+"gaosheng_000971/announcement_2018_127.pdf", None, None)},
   lines=[("共同借款线","DEC","（一）高升控股作为共同借款人","（二）高升控股直接为关联方提供担保"),
          ("直接担保线","DEC","（二）高升控股直接为关联方提供担保","（三）高升控股拆借资金"),
          ("拆借与占用线","ANNC",None,None)]),
 "XINWEI": dict(table="XINWEI_600485_SLOTS_V2_1.json", code="600485",
   docs={"DEC": (RB1+"xinwei_600485/decision_2023_10.html", None, None),
         "AR15": (RB1+"xinwei_600485/annual_2015.pdf", None, None),
         "INQ": (RB1+"xinwei_600485/inquiry_2016_086.pdf", None, None)},
   lines=[("柬埔寨线","DEC","控制柬埔寨项目采购商","（二）"),
          ("尼加拉瓜线","DEC","控制尼加拉瓜项目","（三）"),
          ("坦桑尼亚线","DEC","控制坦桑尼亚项目","（四）"),
          ("巴拿马乌克兰线","DEC","控制巴拿马项目","二、信威集团"),
          ("年报项目披露线","AR15","海外公网项目建设情况","十四、"),
          ("问询指标线","INQ",None,None)]),
 "YISHITE": dict(table="YISHITE_300376_SLOTS_V2_1.json", code="300376",
   docs={"DEC": (RB1+"yishite_300376/decision_2024_147.html", None, None),
         "AR18": (RB1+"yishite_300376/annual_2018.pdf", None, None)},
   lines=[("虚假贸易线","DEC","一、易事特通过开展虚假贸易业务","二、易事特通过开展具有融资性质的代采"),
          ("代采代理线","DEC","二、易事特通过开展具有融资性质的代采业务","三、易事特通过开展具有融资性质的数据中心"),
          ("数据中心线","DEC","三、易事特通过开展具有融资性质的数据中心集成业务","综上,易事特通过上述"),
          ("披露对照线","AR18",None,None)]),
 "XINLUN": dict(table="XINLUN_002341_SLOTS_V2_2.json", code="002341",
   docs={"DEC": (RB1+"xinlun_002341/decision_2020_21.html", None, None),
         "NOTES": (RB1+"xinlun_002341/notes_2019.pdf", None, None),
         "CORR": (RB1+"xinlun_002341/correction_2020_035.pdf", None, None)},
   lines=[("贸易链线","DEC","一、 虚构贸易业务虚增收入及利润","二、未按规定披露关联交易"),
          ("关联担保线","DEC","二、未按规定披露关联交易","三、未按规定披露对外担保"),
          ("追溯更正线","CORR",None,None),
          ("附注会计线","NOTES",None,None)]),
 "CHANGYUAN": dict(table="CHANGYUAN_600525_SLOTS_V1.json", code="600525",
   docs={"DEC": (RB1+"changyuan_600525/decision_2026_13.html", None, None),
         "CORR": (RB1+"changyuan_600525/correction_2025030.pdf", None, None),
         "AR24": (RB1+"changyuan_600525/annual_2024.pdf", None, None)},
   lines=[("占用认定线","DEC","经查明","上述违法事实"),
          ("年报明细线","AR24",None,None),
          ("更正调整线","CORR",None,None)]),
 "SANTE": dict(table="SANTE_002159_SLOTS_V1_1.json", code="002159",
   docs={"DEC": (B3+"sante_002159/decision.html", None, None),
         "INQ": (RAW+"supplements/sante/inquiry_reply_2022_22.pdf", None, None)},
   lines=[("占用时间线","DEC","经查明","三特索道时任实际控制人艾路明"),
          ("责任指令链","DEC","三特索道时任实际控制人艾路明","根据当事人违法行为"),
          ("问询回复线","INQ",None,None)]),
 "TIANSHAN": dict(table="TIANSHAN_300313_SLOTS_V1_1.json", code="300313",
   docs={"DEC": (B3+"tianshan_300313/decision.html", None, None),
         "IMPL": (RAW+"supplements/tianshan/impl_report_20180519.html", None, None),
         "Q3": (RAW+"supplements/tianshan/q3_2018.html", None, None)},
   lines=[("重组流程线","DEC","一、天山生物与大象广告重大资产重组情况","二、大象广告和天山生物"),
          ("资金往来线","DEC","（二）大象广告关联交易情况","（三）大象广告为关联方提供担保"),
          ("担保线","DEC","（三）大象广告为关联方提供担保情况","（四）大象广告涉及重大诉讼"),
          ("诉讼线","DEC","（四）大象广告涉及重大诉讼情况","以上事实"),
          ("实施对照线","IMPL",None,None)]),
 "SHENGLI": dict(table="SHENGLI_002426_SLOTS_V1_1.json", code="002426",
   docs={"DEC": (B3+"shenglil_002426/decision.html", None, None)},
   lines=[("重组对赌线","DEC","一、胜利精密与智诚光学重大资产重组","二、胜利精密2016"),
          ("年度虚增线","DEC","二、胜利精密2016年至2018年年度报告存在虚假记载","上述违法事实"),
          ("责任复核线","DEC","郭文杰作为智诚光学时任财务总监","根据当事人违法行为")]),
 "ZHONGAN": dict(table="ZHONGAN_600654_SLOTS_V1.json", code="600654",
   docs={"DEC": (B3+"zhongan_600654/decision.html", None, None)},
   lines=[("班班通线","DEC","（一）中安消技术将","（二）中安消技术"),
          ("智慧石拐线","DEC","（二）中安消技术","（三）中安消技术对以BT方式"),
          ("BT线","DEC","（三）中安消技术对以BT方式","综上,中安消技术"),
          ("重组与责任线","DEC","一、中安消技术有限公司与中安科重大资产重组的情况","二、中安消技术及中安科信息披露违法")]),
 "SHENWU": dict(table="SHENWU_000820_SLOTS_V1_1.json", code="000820",
   docs={"DEC": (B4+"shenwu_000820/decision.html", None, None)},
   lines=[("金川一期线","DEC","一、2016年年报存在虚假记载","二、2017年年报存在虚假记载"),
          ("金川二期线","DEC","二、2017年年报存在虚假记载","（二）广西景昇隆项目"),
          ("景昇隆线","DEC","（二）广西景昇隆项目","上述违法事实")]),
 "YINGFANGWEI": dict(table="YINGFANGWEI_000670_SLOTS_V1_1.json", code="000670",
   docs={"DEC": (B3+"yingfangwei_000670/decision.html", None, None)},
   lines=[("合同义务线","DEC","一、盈方微未实际履行相关义务","二、盈方微披露的"),
          ("虚假记载与金额线","DEC","二、盈方微披露的信息存在虚假记载","上述违法事实"),
          ("责任复核线","DEC","陈志成、赵海峰、史浩樑","根据当事人违法行为")]),
 "JINYA": dict(table="JINYA_300028_SLOTS_V1_1.json", code="300028",
   docs={"DEC": (B3+"jinya_300028/decision.html", None, None)},
   lines=[("造假组织线","DEC","一、金亚科技2014年伪造财务数据情况","二、2014年年度报告虚增利润总额"),
          ("利润线","DEC","二、2014年年度报告虚增利润总额","三、2014年年度报告虚增银行存款"),
          ("资产线","DEC","三、2014年年度报告虚增银行存款","五、2014年年度报告签署情况"),
          ("签署与申辩线","DEC","五、2014年年度报告签署情况","以上事实")]),
 "WANFU": dict(table="WANFU_300268_SLOTS_V1_1.json", code="300268",
   docs={"DEC": (B3+"wanfu_300268/decision.html", None, None)},
   lines=[("IPO线","DEC","一、万福生科《首次公开发行股票并在创业板上市招股说明书》","二、万福生科《2011"),
          ("2011年报与停产线","DEC","二、万福生科《2011年年度报告》存在虚假记载","四、万福生科《2012"),
          ("半年报与认定线","DEC","四、万福生科《2012年半年度报告》存在虚假记载","以上事实")]),
 "ZHONGCHAO": dict(table="ZHONGCHAO_002471_SLOTS_V1_1.json", code="002471",
   docs={"DEC": (B3+"zhongchao_002471/decision.html", None, None)},
   lines=[("控制权转让线","DEC","一、中超控股未依法披露控制权转让进展情况","二、中超控股未依法及时披露重大诉讼"),
          ("诉讼线","DEC","二、中超控股未依法及时披露重大诉讼情况","三、中超控股2018年年度报告"),
          ("占用线","DEC","三、中超控股2018年年度报告存在重大遗漏","以上违法违规事实")]),
}

manifest = []
for name, cfg in CASES.items():
    table = json.load(open(ST + cfg["table"]))
    # 1. 文档段文件
    doc_dir = os.path.join(OUT, name); os.makedirs(doc_dir, exist_ok=True)
    docs_map = {}
    cont_cache = {}
    for dn, (path, s, e) in cfg["docs"].items():
        if (s, e) == (None, None) and dn not in [l[1] for l in cfg["lines"]]:
            pass
    for line_name, dn, s_kw, e_kw in cfg["lines"]:
        path = dict(cfg["docs"])[dn][0]
        if path not in cont_cache:
            cont_cache[path] = doc_text(path)
        cont = cont_cache[path]
        txt = seg(cont, s_kw, e_kw) if (s_kw or e_kw) else cont[:25000]
        fp = os.path.join(doc_dir, f"{line_name}.txt")
        open(fp, "w").write(txt)
        docs_map[line_name] = {"path": fp}
    # 2. DAG
    lines = cfg["lines"]
    nodes = [{"node": f"A{i+1}", "kind": "extract", "role": f"{ln}事实提取", "docs": [f"{ln}.txt"]}
             for i, (ln, _, _, _) in enumerate(lines)]
    nodes.append({"node": "B1", "kind": "verification", "role": "跨线事实交叉核验(金额/口径/关系比对)",
                  "upstream": [n["node"] for n in nodes]})
    nodes.append({"node": "C1", "kind": "timeline", "role": "事件时序构建", "upstream": ["B1"]})
    nodes.append({"node": "D1", "kind": "report", "role": "终端综合结论", "upstream": ["B1", "C1"]})
    # 3. 计分槽(排除汇总/关系边/UNKNOWN边界)
    slots = []
    for s in table["slots"]:
        if s.get("scoring") == "NO" or s.get("fact_type") == "REGULATORY_AGGREGATE":
            continue
        slots.append({"value": s["value"], "fact_id": s["fact_id"],
                      "proposition": s["proposition"], "status": s["status"]})
    pkg = {"task_id": name, "code": cfg["code"], "case": table["case"],
           "dag": {"nodes": nodes}, "slots": slots, "docs": docs_map,
           "slot_source": cfg["table"],
           "limitation": "value为叙事短语;精确匹配表达式待人工签发阶段细化"}
    fp = os.path.join(doc_dir, f"V6_GOLD_{name}.json")
    json.dump(pkg, open(fp, "w"), ensure_ascii=False, indent=1)
    # 4. 结构门禁+注入矩阵
    g = iac.gate_check(pkg, name)
    rows = []
    ok_inj = True
    for pair in [1, 2, 3, 4]:
        sc = "S3" if pair <= 2 else "S4"
        n, _ = iac.inject_node_for(name, pair, sc, nodes)
        ok_inj &= (n in g["eligible_middle"])
        rows.append((pair, sc, n))
    passed = g["gate_depth_ge3"] and g["gate_middle_nonempty"] and ok_inj and len(slots) >= 18
    h = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    manifest.append(dict(case=table["case"], code=cfg["code"], task=name, n_slots=len(slots),
                         n_extract=len(lines), depth=g["longest_chain_edges"],
                         middle=g["eligible_middle"], inject=rows, gate=passed, sha256=h))
    print(f"{'✓' if passed else '✗'} {name:12s} {table['case']:6s} 槽{len(slots):3d} 线{len(lines)} 深{g['longest_chain_edges']}边 中间{g['eligible_middle']} 注入{[r[2] for r in rows]}")

json.dump(manifest, open(OUT + "GOLD_DAG_MANIFEST_V1.json", "w"), ensure_ascii=False, indent=1)
n_ok = sum(1 for m in manifest if m["gate"])
print(f"\n{len(manifest)}案DAG包生成 | 过门{n_ok} | → GOLD_DAG_MANIFEST_V1.json")
for m in manifest:
    if not m["gate"]:
        print(f"  未过门: {m['task']} 槽{m['n_slots']} 深{m['depth']}")
