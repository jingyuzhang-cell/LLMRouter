#!/usr/bin/env python3
"""Stage D V2.0 pilot（P1–P4；授权 2026-11-03；4 次调用）。

P1 案A J2→DeepSeek thinking-disabled@4000（冻结 J2 提示词）
P2 SINK→GLM-5.3-Flash low@8192（冻结 run3 SINK 提示词，最大输入 4750）——当前最大未知
P3 案B J2→GLM-5.3 low@8192（对照）
P4 GLM max_tokens=16384 参数接受性（最小提示词）

GO 门：STAGE_D_V2_PILOT_GO=1；凭据仅环境变量（STAGE_D_GLM_KEY / DEEPSEEK_API_KEY）。
停止规则：每调用独立判定；HTTP 错误/超时记录为 FAIL，不重试、不换配置。
通过判据：stop ∈ {end_turn, stop, None} 且 JSON 可解析（P4 仅要求 HTTP 200）。
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

STAGE = Path("/root/research_outputs/static_pi/stage_d")
sys.path.insert(0, str(STAGE))
sys.path.insert(0, "/root/capital_opinion_pilot")
import transport  # noqa: E402  冻结共享件（deepseek 分支）

OUT = STAGE / "v2_pilot"
GLM_URL = "https://open.bigmodel.cn/api/anthropic/v1/messages"


def _glm_call(model, system, user, max_tokens, timeout_s=240):
    key = os.environ.get("STAGE_D_GLM_KEY", "").strip()
    if not key:
        raise RuntimeError("STAGE_D_GLM_KEY not set")
    body = {"model": model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}],
            "reasoning_effort": "low"}
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


def _extract_json(text):
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        try:
            v = json.loads(text[i:j + 1])
            return v if isinstance(v, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def run_pilot(pid, fn):
    print(f"=== {pid} ===", flush=True)
    t0 = time.monotonic()
    try:
        r = fn()
        parsed = _extract_json(r.get("text", ""))
        rec = {"pid": pid, "http": 200, "stop": r.get("stop"), "in": r.get("in"),
               "out": r.get("out"), "wall_s": r.get("lat"), "text_chars": len(r.get("text") or ""),
               "json_ok": parsed is not None, "error": None}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        rec = {"pid": pid, "http": e.code, "stop": None, "in": None, "out": None,
               "wall_s": round(time.monotonic() - t0, 2), "text_chars": 0,
               "json_ok": False, "error": f"HTTP {e.code}", "error_detail": detail}
    except Exception as e:  # noqa: BLE001
        rec = {"pid": pid, "http": None, "stop": None, "in": None, "out": None,
               "wall_s": round(time.monotonic() - t0, 2), "text_chars": 0,
               "json_ok": False, "error": repr(e)[:200]}
    if pid == "P4":
        rec["pass"] = rec["http"] == 200
        rec["criterion"] = "http_200_parameter_accepted"
    else:
        rec["pass"] = (rec["http"] == 200 and rec["stop"] in ("end_turn", "stop", None)
                       and rec["json_ok"])
        rec["criterion"] = "http200 + stop∈{end_turn,stop,None} + json_ok"
    rec["tokens_accounting_yuan"] = round(((rec.get("in") or 0) * 0.8e-6
                                           + (rec.get("out") or 0) * 2.8e-6), 8)
    print(json.dumps({k: rec[k] for k in ("pid", "http", "stop", "in", "out", "wall_s",
                                          "text_chars", "json_ok", "pass", "error")},
                     ensure_ascii=False), flush=True)
    return rec


def main():
    if os.environ.get("STAGE_D_V2_PILOT_GO") != "1":
        raise SystemExit("REFUSED: requires STAGE_D_V2_PILOT_GO=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("REFUSED: DEEPSEEK_API_KEY not set")
    OUT.mkdir(parents=True, exist_ok=True)
    j2 = json.loads(Path("/root/research_outputs/static_pi/stage_a/runs_x/run1/J2X.json").read_text("utf-8"))
    sink = json.loads(Path("/root/research_outputs/static_pi/stage_a/runs_x/run3/SINK.json").read_text("utf-8"))
    j2_sha = hashlib.sha256((j2["system"] + "||" + j2["user"]).encode()).hexdigest()
    sink_sha = hashlib.sha256((sink["system"] + "||" + sink["user"]).encode()).hexdigest()
    recs = []
    recs.append(run_pilot("P1_J2_DS_4000", lambda: transport.openai_call(
        "deepseek", j2["system"], j2["user"], 4000, 240, 0)))
    recs.append(run_pilot("P2_SINK_GLMFLASH_LOW_8192", lambda: _glm_call(
        "GLM-5.3-Flash", sink["system"], sink["user"], 8192)))
    recs.append(run_pilot("P3_J2_GLM53_LOW_8192", lambda: _glm_call(
        "GLM-5.3", j2["system"], j2["user"], 8192)))
    recs.append(run_pilot("P4_GLMFLASH_16384_ACCEPT", lambda: _glm_call(
        "GLM-5.3-Flash", "参数接受性预检。", "只回复 OK。", 16384, 120)))
    verdict = {
        "P1_pass": recs[0]["pass"], "P2_pass": recs[1]["pass"],
        "P3_pass": recs[2]["pass"], "P4_pass": recs[3]["pass"],
        "案A_viable(P1+P2)": recs[0]["pass"] and recs[1]["pass"],
        "案B_viable(P3)": recs[2]["pass"],
        "cap_16384_accepted": recs[3]["pass"],
        "prompts": {"J2_sha": j2_sha, "SINK_sha": sink_sha},
        "calls": 4, "tokens_yuan_accounting": round(sum(r["tokens_accounting_yuan"] for r in recs), 8),
    }
    (OUT / "V2_PILOT_RESULTS.json").write_text(
        json.dumps({"verdict": verdict, "records": recs}, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()
