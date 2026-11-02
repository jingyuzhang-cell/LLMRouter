#!/usr/bin/env python3
"""Tier 3 在线抽验（TIER3_PREREGISTRATION 冻结执行，≤15 调用，硬顶 ¥0.50）。"""
import json, os, sys
from pathlib import Path
SA = Path("/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, str(SA))
sys.path.insert(0, str(SA.parent / "stage_c"))
from executor import (call_node, j1_user, j2_user, sink_user, J1_SYSTEM, RELAY_ADDENDUM,
                      J1_POSITIONS_ADDENDUM, J2_SYSTEM, DISAMBIG_ADDENDUM, SINK_SYSTEM,
                      build_terminal_output, apply_format_rules, CONTRACT, SRC, MODEL_ALIAS, DS_ALIAS)
from terminal_quality import evaluate_terminal_quality
import importlib
sys.path.insert(0, str(SA))
executor = importlib.import_module("executor")
HERE = Path(__file__).parent
OUT = HERE / "runs_t3"
SPENT = [0.0]
CAP = 0.50

def spend(c):
    SPENT[0] += c
    assert SPENT[0] < CAP, f"成本硬顶 ¥{CAP} 触及——中止"

def rec(node, meta):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{node}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    spend(meta.get("cost_accounting_yuan") or 0)
    return meta

def evaluate_online(sink_parsed, tag):
    parsed, log = apply_format_rules(json.loads(json.dumps(sink_parsed)))
    term = build_terminal_output(parsed)
    r = evaluate_terminal_quality(CONTRACT, term, SRC)
    (OUT / f"{tag}.term.json").write_text(json.dumps(term, ensure_ascii=False, indent=1), "utf-8")
    (OUT / f"{tag}.eval.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), "utf-8")
    (OUT / f"{tag}.fmtlog.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), "utf-8")
    return r

X1 = SA / "runs_x" / "run1"
e1p = json.loads((X1 / "E1P.json").read_text("utf-8"))["text"]
e2p = json.loads((X1 / "E2P.json").read_text("utf-8"))["text"]
e3 = json.loads((SA / "runs" / "run1" / "E3.json").read_text("utf-8"))["text"]
e4 = json.loads((SA / "runs" / "run1" / "E4.json").read_text("utf-8"))["text"]

# ---------- T3-1 结构修复在线传递（切断态 → 在线重跑 J1P+J2X+SINK） ----------
print("=== T3-1 结构修复（3 调用）===")
u1 = j1_user(json.dumps({"E1": e1p, "E2": e2p}, ensure_ascii=False))
assert u1 == json.loads((X1 / "J1P.json").read_text("utf-8"))["user"], "T3-1 J1P user 漂移"
j1p = rec("T31_J1P", call_node(1, "J1P", J1_SYSTEM + RELAY_ADDENDUM + J1_POSITIONS_ADDENDUM, u1,
                               {"E1": e1p, "E2": e2p}, out_dir=OUT, layer_key="J1"))
u2 = j2_user(json.dumps({"J1": j1p["text"], "E3": e3, "E4": e4}, ensure_ascii=False))
j2x = rec("T31_J2X", call_node(1, "J2X", J2_SYSTEM + DISAMBIG_ADDENDUM, u2,
                               {"J1": j1p["text"], "E3": e3, "E4": e4}, out_dir=OUT, layer_key="J2"))
us = sink_user(json.dumps({"J1": j1p["text"], "J2": j2x["text"]}, ensure_ascii=False))
sink1 = rec("T31_SINK", call_node(1, "SINK", SINK_SYSTEM, us, {"J1": j1p["text"], "J2": j2x["text"]}, out_dir=OUT, layer_key="SINK"))
r1 = evaluate_online(sink1["parsed"], "T31")
f1 = {c.get("fact_id"): c["status"] for c in r1["claim_results"]}
print(f"  C1 在线 F1={f1.get('F1','')[:14]} F2={f1.get('F2','')[:14]} | relay在位={'dates_relay' in (j1p['parsed'] or {})}")

# ---------- T3-2 口径修复在线（J1P 冻结态 → 在线消歧 J2+SINK） ----------
print("=== T3-2 口径修复（2 调用）===")
j1p_x = json.loads((X1 / "J1P.json").read_text("utf-8"))["text"]
u2b = j2_user(json.dumps({"J1": j1p_x, "E3": e3, "E4": e4}, ensure_ascii=False))
assert u2b == json.loads((X1 / "J2X.json").read_text("utf-8"))["user"], "T3-2 J2 user 漂移"
j2x2 = rec("T32_J2X", call_node(1, "J2X", J2_SYSTEM + DISAMBIG_ADDENDUM, u2b,
                                {"J1": j1p_x, "E3": e3, "E4": e4}, out_dir=OUT, layer_key="J2"))
us2 = sink_user(json.dumps({"J1": j1p_x, "J2": j2x2["text"]}, ensure_ascii=False))
sink2 = rec("T32_SINK", call_node(1, "SINK", SINK_SYSTEM, us2, {"J1": j1p_x, "J2": j2x2["text"]}, out_dir=OUT, layer_key="SINK"))
cnt2 = (j2x2["parsed"].get("counts") or {}).get("announcing_company_count")
r2 = evaluate_online(sink2["parsed"], "T32")
e2v = next((str(a.get("value")) for a in sink2["parsed"].get("answers", []) if a.get("fact_id") == "E2"), None)
st2 = {c.get("fact_id"): c["status"] for c in r2["claim_results"]}.get("E2", "")
print(f"  C2 节点计数={cnt2} 终端E2={e2v!r} formal={st2[:14]}")

# ---------- T3-3 模型换模在线（Joint J2J 态 → 在线 DS-J2+SINK，单样本） ----------
print("=== T3-3 模型换模（2 调用，单样本不判分布）===")
assert os.environ.get("DEEPSEEK_API_KEY"), "DS 凭据缺失 → T3-3 BLOCKED"
j1r = json.loads((SA / "runs_r" / "run1" / "J1r.json").read_text("utf-8"))["text"]
u3 = j2_user(json.dumps({"J1": j1r, "E3": e3, "E4": e4}, ensure_ascii=False))
assert u3 == json.loads((SA / "runs_j" / "run1" / "J2J.json").read_text("utf-8"))["user"], "T3-3 J2 user 漂移（应与 Joint J2J 同上游）"
j2ds = rec("T33_J2DS", call_node(1, "J2DS", J2_SYSTEM, u3, {"J1": j1r, "E3": e3, "E4": e4},
                                 out_dir=OUT, alias=DS_ALIAS, layer_key="J2"))
us3 = sink_user(json.dumps({"J1": j1r, "J2": j2ds["text"]}, ensure_ascii=False))
sink3 = rec("T33_SINK", call_node(1, "SINK", SINK_SYSTEM, us3, {"J1": j1r, "J2": j2ds["text"]}, out_dir=OUT, layer_key="SINK"))
cnt3 = (j2ds["parsed"].get("counts") or {}).get("announcing_company_count")
e2v3 = next((str(a.get("value")) for a in sink3["parsed"].get("answers", []) if a.get("fact_id") == "E2"), None)
print(f"  C3 DS-J2 json_ok={j2ds['json_ok']} 节点计数={cnt3} 终端E2={e2v3!r}（∈{{2,4}}: {e2v3 in ('2','4')}）")

print(f"\n调用成本累计（核算口径）: ¥{SPENT[0]:.4f} / 硬顶 ¥{CAP}")
