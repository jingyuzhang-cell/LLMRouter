#!/usr/bin/env python3
"""通用案件构建器(双门禁内置)
用法: python3 case_builder.py <spec.json>
spec 结构:
{"case":"案名","code":"代码","decision":"路径",
 "lines":[["线名","起锚","止锚"],...],
 "slots":[["F01","命题","主体","值","期间","锚点","关系",["flag"...]],...],
 "note":"可选"}
自动: 锚点切片跨度 → 槽位表 → DAG → 门禁1(SPAN) → 门禁2(SEGMENT) → 注入矩阵
"""
import json, re, sys, os, glob, hashlib, importlib.util
sys.path.insert(0, "/root/research_outputs/RQ_DYN_V6_DESIGN")
from extract_decision import extract
spec_in = importlib.util.spec_from_file_location("iac", "/root/research_outputs/RQ_DYN_V6_DESIGN/injection_acceptance_check.py")
iac = importlib.util.module_from_spec(spec_in); spec_in.loader.exec_module(iac)

NORM = lambda s: re.sub(r'[\s,，()（）]', '', s)

def main(spec_path):
    S = json.load(open(spec_path))
    case, code, dec = S["case"], S["code"], S["decision"]
    _, FULL = extract(dec)
    NF = NORM(FULL)
    DOC = hashlib.sha256(open(dec, "rb").read()).hexdigest()
    base = f"/root/research_outputs/RQ_DYN_V6_DESIGN"
    dagdir = f"{base}/gold_dags/{S.get('task', code)}"
    os.makedirs(dagdir, exist_ok=True)

    SPAN_LOG = []   # 记录每次切片: 锚点缩短级别/命中位置/歧义次数
    def slice_span(anchor, n, fid=""):
        na = NORM(anchor)
        for L in (len(na), 24, 16, 12):
            if L < 8: break
            key = na[:L]
            positions = [m.start() for m in re.finditer(re.escape(key), NF)]
            if not positions:
                continue
            ambiguous = len(positions) > 1
            if ambiguous:
                # 短锚点多次命中: 报错要求提供更长锚点,禁止自动取第一处
                raise RuntimeError(
                    f"[{case}] 短锚点歧义({L}字, 命中{len(positions)}处): {anchor[:30]} — 需提供更独特的锚点")
            SPAN_LOG.append(dict(fact_id=fid, anchor_len=L, full_len=len(na),
                                 shortened=(L < len(na)), position=positions[0],
                                 ambiguous=False))
            return NF[positions[0]:positions[0] + n]
        raise RuntimeError(f"[{case}] 锚点未命中: {anchor[:40]}")

    # --- 槽位表 ---
    XT = []
    for it in S["slots"]:
        fid, prop, subj, val, ts, anchor, rel = it[:7]
        flags = it[7] if len(it) > 7 else []
        d = dict(fact_id=fid, proposition=prop, subject=subj, value=val, time_scope=ts,
                 source_id=f"{code}_DEC", evidence_span=slice_span(anchor, S.get("span_len", 240), fid),
                 span_method="anchor_slice", doc_sha256=DOC, relation=rel,
                 status="PASS", review_note="")
        if "AGG" in flags: d["fact_type"] = "REGULATORY_AGGREGATE"
        if "UNK" in flags: d["status"] = "UNKNOWN"
        if "NO" in flags: d["scoring"] = "NO"
        if "ANN" in flags: d["fact_type"] = "MODE_ANNUAL"
        XT.append(d)
    n_score = len([x for x in XT if x.get("fact_type") != "REGULATORY_AGGREGATE" and x.get("scoring") != "NO"])
    pkg = dict(case=case, code=code, slots=XT, version="V1(2026-11-11,双门禁流程)",
               span_log=dict(total=len(SPAN_LOG),
                 shortened=sum(1 for x in SPAN_LOG if x["shortened"]),
                 details=SPAN_LOG),
               doc_sha256=DOC, span_policy="anchor_slice",
               scoring_caliber={"records": len(XT), "scoring_slots": str(n_score)},
               structural_precheck=S.get("precheck", {}), note=S.get("note", ""))
    tf = f"{base}/slot_tables_v1/{S.get('task', code)}_SLOTS_V1.json"
    json.dump(pkg, open(tf, "w"), ensure_ascii=False, indent=1)

    # --- DAG段(双锚点,禁兜底) ---
    docs = {}
    for ln, st, en in S["lines"]:
        p = NF.find(NORM(st))
        if p < 0: raise RuntimeError(f"[{case}] 段起锚未命中 {st[:20]}")
        q = NF.find(NORM(en), p + 50)
        if q < 0: raise RuntimeError(f"[{case}] 段止锚未命中 {en[:20]} (禁兜底)")
        fp = f"{dagdir}/{ln}.txt"
        open(fp, "w").write(NF[p:q])
        docs[ln] = {"path": fp}
    nodes = [{"node": f"A{i+1}", "kind": "extract", "role": f"{ln}提取", "docs": [f"{ln}.txt"]}
             for i, (ln, _, _) in enumerate(S["lines"])]
    nodes += [{"node": "B1", "kind": "verification", "role": S.get("b1", "跨线核验"), "upstream": [x["node"] for x in nodes]},
              {"node": "C1", "kind": "timeline", "role": "事件时序", "upstream": ["B1"]},
              {"node": "D1", "kind": "report", "role": "终端结论", "upstream": ["B1", "C1"]}]
    slots = [{"value": s["value"], "fact_id": s["fact_id"], "proposition": s["proposition"], "status": s["status"]}
             for s in XT if s.get("fact_type") != "REGULATORY_AGGREGATE" and s.get("scoring") != "NO"]
    dpkg = dict(task_id=S.get("task", code), code=code, case=case, dag={"nodes": nodes},
                slots=slots, docs=docs, limitation="value为叙事短语")
    df = f"{dagdir}/V6_GOLD_{S.get('task', code)}.json"
    json.dump(dpkg, open(df, "w"), ensure_ascii=False, indent=1)

    # --- 门禁 ---
    from gold_gates import check_spans, check_segments
    g1 = check_spans(tf, [dec])
    g2 = check_segments(dagdir)
    g = iac.gate_check(dpkg, S.get("task", code))
    rows = [iac.inject_node_for(S.get("task", code), p, "S3" if p <= 2 else "S4", nodes)[0] for p in [1, 2, 3, 4]]
    struct_ok = g["gate_depth_ge3"] and g["gate_middle_nonempty"] and all(r in g["eligible_middle"] for r in rows) and n_score >= 18
    sh=[x for x in SPAN_LOG if x["shortened"]]
    if sh: print(f"  ⚠ [{case}] 锚点缩短{len(sh)}处(已记录位置): " + ", ".join(f"{x['fact_id']}@{x['position']}({x['anchor_len']}字)" for x in sh[:3]))
    print(f"[{case}] 槽{n_score} | SPAN {'✓' if g1['failed']==0 else '✗'+str(g1['bad'][:2])} | "
          f"SEG {'✓' if g2['failed']==0 else '✗'} | 深{g['longest_chain_edges']}边 中间{g['eligible_middle']} "
          f"注入{rows} | 结构{'✓' if struct_ok else '✗'} | 过门{'✓' if (g1['failed']==0 and g2['failed']==0 and struct_ok) else '✗'}")
    return dict(case=case, slots=n_score, span=g1["failed"], seg=g2["failed"],
                depth=g["longest_chain_edges"], struct=struct_ok,
                pass_=(g1["failed"] == 0 and g2["failed"] == 0 and struct_ok),
                table_sha=hashlib.sha256(open(tf, "rb").read()).hexdigest()[:16],
                dag_sha=hashlib.sha256(open(df, "rb").read()).hexdigest()[:16])

if __name__ == "__main__":
    r = main(sys.argv[1])
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r["pass_"] else 1)
