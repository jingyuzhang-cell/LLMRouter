#!/usr/bin/env python3
"""STAGE_B B-4 机制验证 runner（最终冻结协议执行件）。

块：
  B2a 健康 × {A0,A1,A2,A3} × 4 rep（共享 E）
  B2b J1 异常（GLM J1 契约违反注入，持续）× {A0,A1,A2,A3} × 4 rep
  B2c 结构异常（J1 部署无 relay）× {A2,A3} × 4 rep
  B3  {格式异常, 结构异常} × {匹配, 不匹配} × 2 rep（机制探针）

臂时点（冻结）：
  A0 = 不换模；A1 = J1 首次执行结束后无条件一次 DS 重执行并采用其结果；
  A2 = 诊断触发（契约违反/缺 relay）单次 DS 重执行；A3 = A2 + 结构异常时结构修复。
  全臂初始 J1=GLM@8192；E/J2/SINK=DS@4000；同 rep 共享 E；臂序随机（seed 20261104）。

GO 门：STAGE_B_B4_GO=1（real）；--mock 为零调用自测。
"""
import argparse
import hashlib
import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

STAGE_A = Path("/root/research_outputs/static_pi/stage_a")
STAGE_D = Path("/root/research_outputs/static_pi/stage_d")
sys.path.insert(0, str(STAGE_A))
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, "/root/capital_opinion_pilot")
sys.path.insert(0, "/root/r3_own_pool/deadline_reward_v1/quality_v4")

import transport  # noqa: E402
from executor import (E_SYSTEM, E_POSITION_ADDENDUM, J1_SYSTEM, RELAY_ADDENDUM,  # noqa: E402
                      J1_POSITIONS_ADDENDUM, J2_SYSTEM, DISAMBIG_ADDENDUM, SINK_SYSTEM,
                      e_user, j1_user, j2_user, sink_user, extract_json,
                      apply_format_rules, build_terminal_output)
from terminal_quality import evaluate_terminal_quality  # noqa: E402
from stage_d_v3_executor import output_contract_check  # noqa: E402

OUT = STAGE_D / "b4_runs"
GLM_URL = "https://open.bigmodel.cn/api/anthropic/v1/messages"
J1_HEALTHY = J1_SYSTEM + RELAY_ADDENDUM + J1_POSITIONS_ADDENDUM
J1_STRUCT_FAULT = J1_SYSTEM                       # 结构异常：部署无 relay（S3 式）
J1_REPAIR = J1_SYSTEM + RELAY_ADDENDUM + J1_POSITIONS_ADDENDUM
CONTRACTS = {}
for _lab, _f in (("old", "TASK_CONTRACT_PHASE2B_v2_1.json"), ("v3", "TASK_CONTRACT_PHASE2B_v3_DRAFT.json")):
    _c = json.loads((Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/") / _f).read_text("utf-8"))
    _src = _c.pop("source_pages")
    CONTRACTS[_lab] = (_c, _src)
MAP = {"E1": "D1", "E2": "D2", "E3": "D3", "E4": "D4"}
MOCK = False


# ---------------- transports ----------------
def glm_call(system, user, max_tokens=8192, timeout_s=300):
    if MOCK:
        has_relay = "dates_relay" in (system or "")
        d = {"judgments": []}
        if has_relay:
            d["dates_relay"] = {"D1": {"公告落款日": "2026-10-09"}}
            d["positions_relay"] = [{"field": "任职状况", "value": "x"}]
        return {"text": json.dumps(d, ensure_ascii=False), "in": 100, "out": 50,
                "stop": "end_turn", "lat": 0.01}
    key = os.environ.get("STAGE_D_GLM_KEY", "").strip()
    body = {"model": "GLM-5.3-Flash", "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}], "reasoning_effort": "low"}
    req = urllib.request.Request(GLM_URL, data=json.dumps(body, ensure_ascii=False).encode(), method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", key)
    req.add_header("authorization", "Bearer " + key)
    req.add_header("anthropic-version", "2023-06-01")
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    return {"text": "".join(b.get("text", "") for b in d.get("content", [])
                            if isinstance(b, dict) and b.get("type") == "text"),
            "in": d["usage"]["input_tokens"], "out": d["usage"]["output_tokens"],
            "stop": d.get("stop_reason"), "lat": round(time.monotonic() - t0, 2)}


def ds_call(system, user, max_tokens=4000, timeout_s=300):
    if MOCK:
        return {"text": '{"answers": [{"fact_id": "D_1", "value": "SAME_PERSON", "doc": "E1", "page": 1, '
                        '"quote": "q"}], "abstentions": []}' if "最终" in (system or "") or "answers" in (system or "")
                else '{"judgments": [], "dates_relay": {"D1": {}}}',
                "in": 100, "out": 50, "stop": "stop", "lat": 0.01}
    t0 = time.monotonic()
    r = transport.openai_call("deepseek", system, user, max_tokens, timeout_s, 0)
    r["lat"] = round(time.monotonic() - t0, 2)
    return r


# ---------------- scoring（Stage A 对齐管线） ----------------
def score_final(sink_parsed, fmt_bypassed):
    if sink_parsed is None:
        return {"old_tp": 0, "v3_tp": 0, "a1_full": 0.0}
    pf = json.loads(json.dumps(sink_parsed))
    if not fmt_bypassed:
        pf = apply_format_rules(pf)[0]
    out = {}
    for lab in ("old", "v3"):
        c, src = CONTRACTS[lab]
        import copy
        q = evaluate_terminal_quality(copy.deepcopy(c), build_terminal_output(json.loads(json.dumps(pf))), src)
        out[f"{lab}_tp"] = sum(1 for x in q["claim_results"] if x["status"].startswith("CORRECT"))
    a1 = json.loads(json.dumps(pf))
    for a in a1.get("answers", []):
        if str(a.get("doc")) in MAP:
            a["doc"] = MAP[str(a.get("doc"))]
    import copy
    q = evaluate_terminal_quality(copy.deepcopy(CONTRACTS["old"][0]), build_terminal_output(a1), CONTRACTS["old"][1])
    full = sum(1 for x in q["claim_results"] if x["status"] == "CORRECT_GOLD")
    out["a1_full"] = round(full / max(len(q["claim_results"]), 1), 4)
    return out


# ---------------- execution ----------------
def run_arm(arm, cond, rep, E, extra=None):
    """extra: B-3 覆盖（matched/mismatched 动作）。返回记录。"""
    t0 = time.monotonic()
    calls, guard, actions = [], [], []
    acct = 0.0

    def call(node, backend, system, user, tag):
        nonlocal acct
        r = glm_call(system, user) if backend == "glm" else ds_call(system, user)
        c = {"node": node, "backend": backend, "tag": tag, "in": r.get("in"), "out": r.get("out"),
             "stop": r.get("stop"), "lat": r.get("lat"), "text": r.get("text")}
        calls.append(c)
        acct += (r.get("in") or 0) * 0.8e-6 + (r.get("out") or 0) * 2.8e-6
        return r

    j1_sys = J1_STRUCT_FAULT if cond in ("struct", "struct_b3") else J1_HEALTHY
    j1u = j1_user(json.dumps({"E1": E["E1"], "E2": E["E2"]}, ensure_ascii=False))
    r1 = call("J1", "glm", j1_sys, j1u, "first")
    j1_text = r1.get("text") or ""
    if cond == "j1anom":
        j1_text = ""                       # 持续契约违反注入（守卫 reason=empty_text）
    parsed1 = extract_json(j1_text)
    g1 = output_contract_check("J1", {"text": j1_text, "in": r1.get("in"), "out": r1.get("out")}, parsed1)
    if g1:
        guard.append({"node": "J1", "reason": g1, "phase": "first"})
    final_j1, j1_model = j1_text, "glm53flash"
    struct_sig = (cond in ("struct", "struct_b3")) and ("dates_relay" not in (parsed1 or {}))

    if arm == "A0":
        if g1:
            actions.append({"kind": "none", "note": "A0 no action"})
            return _rec(arm, cond, rep, calls, guard, actions, None, t0, acct,
                        status="INCOMPLETE_NO_RECOVERY", fmt_bypassed=False)
    elif arm == "A1":
        rd = call("J1", "ds", J1_HEALTHY, j1u, "blind_swap")
        actions.append({"kind": "unconditional_swap", "node": "J1"})
        final_j1, j1_model = rd.get("text") or "", "deepseek"
    elif arm in ("A2", "A3"):
        if g1:
            rd = call("J1", "ds", J1_HEALTHY, j1u, "diagnosed_swap")
            actions.append({"kind": "diagnosed_swap", "node": "J1"})
            final_j1, j1_model = rd.get("text") or "", "deepseek"

    if (arm == "A3" or (arm == "B3" and extra == "matched" and cond == "struct_b3")) and struct_sig:
        actions.append({"kind": "structure_repair", "node": "J1"})
        rr = call("J1", "glm", J1_REPAIR, j1u, "structure_repair")
        final_j1, j1_model = rr.get("text") or "", "glm53flash"

    # B-3 覆盖
    if extra == "mismatched" and cond in ("struct", "struct_b3"):
        actions.append({"kind": "format_repair_only(mismatched)"})
    if extra == "matched" and cond == "struct_b3":
        pass  # 匹配=结构修复，已在 A3 路径；B-3 struct 匹配臂复用 A3 逻辑

    pj1 = extract_json(final_j1)
    if pj1 is None:
        return _rec(arm, cond, rep, calls, guard, actions, None, t0, acct,
                    status="INCOMPLETE_J1_UNPARSEABLE", fmt_bypassed=False)
    j2u = j2_user(json.dumps({"J1": final_j1, "E3": E["E3"], "E4": E["E4"]}, ensure_ascii=False))
    r2 = call("J2", "ds", J2_SYSTEM + DISAMBIG_ADDENDUM, j2u, "main")
    p2 = extract_json(r2.get("text") or "")
    if p2 is None:
        return _rec(arm, cond, rep, calls, guard, actions, None, t0, acct,
                    status="INCOMPLETE_J2", fmt_bypassed=False)
    su = sink_user(json.dumps({"J1": final_j1, "J2": r2.get("text")}, ensure_ascii=False))
    r3 = call("SINK", "ds", SINK_SYSTEM, su, "main")
    ps = extract_json(r3.get("text") or "")
    fmt_bypassed = (cond == "fmt_b3" and extra != "matched")
    if extra == "matched" and cond == "fmt_b3":
        actions.append({"kind": "format_repair(matched)"})
    if extra == "mismatched" and cond == "fmt_b3":
        actions.append({"kind": "structure_repair_only(mismatched)"})
        # 不匹配：重跑 J1（结构动作）但不修格式
        rr = call("J1", "glm", J1_REPAIR, j1u, "mismatched_action")
        final_j1 = rr.get("text") or ""
        j2u2 = j2_user(json.dumps({"J1": final_j1, "E3": E["E3"], "E4": E["E4"]}, ensure_ascii=False))
        r2 = call("J2", "ds", J2_SYSTEM + DISAMBIG_ADDENDUM, j2u2, "rerun")
        su = sink_user(json.dumps({"J1": final_j1, "J2": r2.get("text")}, ensure_ascii=False))
        r3 = call("SINK", "ds", SINK_SYSTEM, su, "rerun")
        ps = extract_json(r3.get("text") or "")
    sc = score_final(ps, fmt_bypassed)
    return _rec(arm, cond, rep, calls, guard, actions, sc, t0, acct,
                status="COMPLETE", fmt_bypassed=fmt_bypassed, j1_model=j1_model)


def _rec(arm, cond, rep, calls, guard, actions, sc, t0, acct, status, fmt_bypassed, j1_model=None):
    return {"arm": arm, "cond": cond, "rep": rep, "status": status,
            "wall_s": round(time.monotonic() - t0, 1),
            "n_calls": len(calls), "accounting_yuan": round(acct, 6),
            "guard": guard, "actions": actions, "j1_final_model": j1_model,
            "fmt_bypassed": fmt_bypassed,
            "score": sc or {"old_tp": 0, "v3_tp": 0, "a1_full": 0.0},
            "calls": [{k: c[k] for k in ("node", "backend", "tag", "in", "out", "stop", "lat")} for c in calls],
            "texts_sha": None}


def run_block(name, conds_arms, reps, shared_E):
    rng = random.Random(20261104 + reps)
    recs = []
    for rep in range(1, reps + 1):
        order = list(conds_arms)
        rng.shuffle(order)
        for arm, cond in order:
            r = run_arm(arm, cond, rep, shared_E)
            recs.append(r)
            print(f"[{name}] rep{rep} {arm}({cond}): {r['status']} calls={r['n_calls']} "
                  f"TP={r['score']['old_tp']}/{r['score']['v3_tp']} guard={[g['reason'] for g in r['guard']]}",
                  flush=True)
    return recs


def main():
    global MOCK
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    MOCK = a.mock
    if not MOCK:
        if os.environ.get("STAGE_B_B4_GO") != "1":
            raise SystemExit("REFUSED: real mode requires STAGE_B_B4_GO=1")
        if not os.environ.get("DEEPSEEK_API_KEY"):
            raise SystemExit("REFUSED: DEEPSEEK_API_KEY not set")
    OUT.mkdir(parents=True, exist_ok=True)
    # 每 rep 共享 E：B2a/B2b 各自一套（4 rep × 2 块）+ B2c/B3 各自
    all_recs = {"B2a": [], "B2b": [], "B2c": [], "B3": []}
    rng = random.Random(20261104)
    for blk, conds, reps in (
            ("B2a", [("A0", "healthy"), ("A1", "healthy"), ("A2", "healthy"), ("A3", "healthy")], 4),
            ("B2b", [("A0", "j1anom"), ("A1", "j1anom"), ("A2", "j1anom"), ("A3", "j1anom")], 4),
            ("B2c", [("A2", "struct"), ("A3", "struct")], 4)):
        for rep in range(1, reps + 1):
            E = {}
            for n in ("E1", "E2", "E3", "E4"):
                sys_ = E_SYSTEM + (E_POSITION_ADDENDUM if n in ("E1", "E2") else "")
                r = ds_call(sys_, e_user(n))
                E[n] = r.get("text") or ""
            order = list(conds)
            random.Random(20261104 + hash(blk) % 100 + rep).shuffle(order)
            for arm, cond in order:
                rec = run_arm(arm, cond, rep, E)
                rec["E_shared_sha"] = hashlib.sha256(
                    json.dumps(E, ensure_ascii=False).encode()).hexdigest()[:12]
                all_recs[blk].append(rec)
                print(f"[{blk}] rep{rep} {arm}: {rec['status']} calls={rec['n_calls']} "
                      f"TP={rec['score']['old_tp']}/{rec['score']['v3_tp']}", flush=True)
    # B-3：2 条件 × 2 动作 × 2 rep（机制探针）
    for rep in (1, 2):
        E = {}
        for n in ("E1", "E2", "E3", "E4"):
            sys_ = E_SYSTEM + (E_POSITION_ADDENDUM if n in ("E1", "E2") else "")
            E[n] = ds_call(sys_, e_user(n)).get("text") or ""
        for cond, arms in (("fmt_b3", [("A3x", "matched"), ("A3x", "mismatched")]),
                           ("struct_b3", [("A3x", "matched"), ("A3x", "mismatched")])):
            for _, extra in arms:
                rec = run_arm("B3", cond, rep, E, extra=extra)
                # struct_b3 matched → 复用 A3 结构修复路径
                all_recs["B3"].append(rec)
                print(f"[B3] rep{rep} {cond}/{extra}: {rec['status']} calls={rec['n_calls']} "
                      f"TP={rec['score']['old_tp']}/{rec['score']['v3_tp']}", flush=True)
    total_calls = sum(r["n_calls"] for rs in all_recs.values() for r in rs)
    summary = {k: len(v) for k, v in all_recs.items()}
    summary["total_calls"] = total_calls
    (OUT / "B4_ALL_RECORDS.json").write_text(json.dumps(all_recs, ensure_ascii=False, indent=1), "utf-8")
    (OUT / "B4_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
