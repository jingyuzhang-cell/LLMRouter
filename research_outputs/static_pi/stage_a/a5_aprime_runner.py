#!/usr/bin/env python3
"""A5 A′ 7 次先导执行器（GO-gated；零重试；thinking=low；max_tokens=4000）。

预注册：/root/q_foundation/A5_PRIME_PREREGISTRATION_V2_DRAFT.md
线程：C0-P（真实 run3-SINK 提示词，1 次）→ run1-C（3 次）→ run1-B（3 次）。

安全门：
  - 必须同时设置 A5PRIME_GO=1 且传入 --go，否则只打印状态、零调用。
  - 凭据仅从环境变量 A5_GLM_KEY 读取，不落盘、不打印。
  - 任何 HTTP 错误 / stop!=end_turn / JSON 解析失败 → 立即停止，不重试。
  - 不切换端点/模型/thinking 档位；不把 max_tokens 提高到 8000。
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

STAGE = Path("/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, str(STAGE))
from executor import (J1_SYSTEM, RELAY_ADDENDUM, J1_POSITIONS_ADDENDUM,  # noqa: E402
                      J2_SYSTEM, DISAMBIG_ADDENDUM, SINK_SYSTEM,
                      j1_user, j2_user, sink_user, sha)

ENDPOINT = "https://open.bigmodel.cn/api/anthropic/v1/messages"
MODEL = "GLM-5.3-Flash"
MAXTOK = 4000
TEMPERATURE = 0
OUT = STAGE / "runs_a5_planAPrime"
FREEZE = STAGE / "A5_APRIME_V4_FREEZE_MANIFEST.json"
EXPECTED = {
    "B_J1_system": "28560bc565f40d85",   # system-only sha256
    "C_J1_system": "c7384236807cb9b0",
    "run1_B_J1_combined": "d13b8a229c60fcb8",
    "run1_C_J1_combined": "419880b0c7788037",
}


class Halt(Exception):
    pass


def _freeze_ok():
    if not FREEZE.exists():
        return False
    m = json.loads(FREEZE.read_text("utf-8"))
    cur = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return m.get("status") in ("FROZEN_PENDING_GO", "GO") and m.get("runner_sha256") == cur


def _key():
    k = os.environ.get("A5_GLM_KEY", "").strip()
    if not k:
        raise Halt("A5_GLM_KEY 未设置")
    return k


def _sha(x):
    return hashlib.sha256(x.encode("utf-8")).hexdigest()


def call(layer, system, user, node, out_dir, run, arm, expected_prompt=None):
    prompt = sha(system + "||" + user)
    if expected_prompt and not prompt.startswith(expected_prompt):
        raise Halt(f"{node}: prompt hash {prompt[:16]} != expected {expected_prompt}")
    body = {"model": MODEL, "max_tokens": MAXTOK, "temperature": TEMPERATURE,
            "thinking": {"type": "low"}, "system": system,
            "messages": [{"role": "user", "content": user}]}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=payload, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", _key())
    req.add_header("authorization", "Bearer " + _key())
    req.add_header("anthropic-version", "2023-06-01")
    meta = {"run": run, "arm": arm, "node": node, "endpoint": ENDPOINT, "model": MODEL,
            "thinking": "low", "max_tokens": MAXTOK, "temperature": TEMPERATURE,
            "prompt_sha256": prompt,
            "request_body_sha256": hashlib.sha256(payload).hexdigest(),
            "system": system, "user": user}
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            raw = r.read()
            d = json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        meta.update({"wall_s": round(time.monotonic() - t0, 2), "error": f"HTTP {e.code}",
                     "error_detail": detail, "stop": None, "usage": None, "text": "",
                     "json_ok": False})
        _write(out_dir, node, meta)
        raise Halt(f"{node}: HTTP {e.code} -> 停止（不重试）")
    except Exception as e:  # noqa: BLE001
        meta.update({"wall_s": round(time.monotonic() - t0, 2), "error": repr(e)[:300],
                     "stop": None, "usage": None, "text": "", "json_ok": False})
        _write(out_dir, node, meta)
        raise Halt(f"{node}: {e!r} -> 停止（不重试）")

    blocks = d.get("content") or []
    txt = "".join(b.get("text", "") for b in blocks
                  if isinstance(b, dict) and b.get("type") == "text")
    u = d.get("usage") or {}
    meta.update({
        "wall_s": round(time.monotonic() - t0, 2), "error": None,
        "response_body_sha256": hashlib.sha256(raw).hexdigest(),
        "usage": {"in": u.get("input_tokens"), "out": u.get("output_tokens"),
                  "reasoning": u.get("reasoning_tokens")},
        "stop": d.get("stop_reason"), "text": txt,
        "content_blocks": [{"type": b.get("type"), "chars": len(b.get("text", "") or "")}
                           for b in blocks if isinstance(b, dict)],
        "cost_accounting_yuan": round(((u.get("input_tokens") or 0) * 8.0e-7
                                       + (u.get("output_tokens") or 0) * 2.8e-6), 8)})
    i, j = txt.find("{"), txt.rfind("}")
    parsed = None
    if i >= 0 and j > i:
        try:
            parsed = json.loads(txt[i:j + 1])
        except json.JSONDecodeError:
            pass
    meta["parsed"] = parsed
    meta["json_ok"] = parsed is not None
    _write(out_dir, node, meta)
    print(f"  {node}: json_ok={meta['json_ok']} stop={meta['stop']} "
          f"in/out={meta['usage']['in'], meta['usage']['out']} wall={meta['wall_s']}s", flush=True)
    # 历史 Anthropic 端点成功响应可能返回 stop_reason=null；null+完整 JSON 视为成功。
    if meta["stop"] not in (None, "end_turn"):
        raise Halt(f"{node}: stop={meta['stop']} -> 停止（截断/异常，不重试）")
    if not meta["json_ok"]:
        raise Halt(f"{node}: JSON 解析失败 -> 停止（不重试）")
    return meta


def _write(out_dir, node, meta):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{node}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")


def c0p():
    """C0-P：真实 run3-SINK 历史提示词；验证 low + 4000，同时作历史规模预算代理。"""
    sink = json.loads((STAGE / "runs_x" / "run3" / "SINK.json").read_text("utf-8"))
    print("=== C0-P（真实 run3-SINK 提示词；1 调用）===", flush=True)
    call("SINK", sink["system"], sink["user"], "C0P_SINK", OUT / "c0p", 0, "C0P")


def arm(arm):
    """run1 的单臂：J1→J2→SINK；C 臂 C-first（run1 预登记顺序）。"""
    k = 1
    e1 = json.loads((STAGE / "runs_x" / f"run{k}" / "E1P.json").read_text("utf-8"))
    e2 = json.loads((STAGE / "runs_x" / f"run{k}" / "E2P.json").read_text("utf-8"))
    e3 = json.loads((STAGE / "runs" / f"run{k}" / "E3.json").read_text("utf-8"))
    e4 = json.loads((STAGE / "runs" / f"run{k}" / "E4.json").read_text("utf-8"))
    j1sys = ((J1_SYSTEM + RELAY_ADDENDUM) if arm == "B"
             else (J1_SYSTEM + RELAY_ADDENDUM + J1_POSITIONS_ADDENDUM))
    expected_sys = EXPECTED["B_J1_system"] if arm == "B" else EXPECTED["C_J1_system"]
    expected_comb = EXPECTED["run1_B_J1_combined"] if arm == "B" else EXPECTED["run1_C_J1_combined"]
    if not sha(j1sys).startswith(expected_sys):
        raise Halt(f"run1-{arm}: J1 system hash mismatch")
    out = OUT / "run1" / arm
    print(f"=== run1-{arm}（3 调用）===", flush=True)
    j1u = j1_user(json.dumps({"E1": e1["text"], "E2": e2["text"]}, ensure_ascii=False))
    j1 = call("J1", j1sys, j1u, "J1", out, 1, arm, expected_prompt=expected_comb)
    j2u = j2_user(json.dumps({"J1": j1["text"], "E3": e3["text"], "E4": e4["text"]},
                             ensure_ascii=False))
    j2 = call("J2", J2_SYSTEM + DISAMBIG_ADDENDUM, j2u, "J2", out, 1, arm)
    sinku = sink_user(json.dumps({"J1": j1["text"], "J2": j2["text"]}, ensure_ascii=False))
    call("SINK", SINK_SYSTEM, sinku, "SINK", out, 1, arm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "c0p", "run1-c", "run1-b", "all"])
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    if a.cmd == "status":
        print(json.dumps({"endpoint": ENDPOINT, "model": MODEL, "thinking": "low",
                          "max_tokens": MAXTOK, "temperature": TEMPERATURE,
                          "go_gate": os.environ.get("A5PRIME_GO") == "1" and a.go,
                          "out": str(OUT)}, ensure_ascii=False, indent=1))
        return
    if os.environ.get("A5PRIME_GO") != "1" or not a.go:
        print("GO gate closed: 需要 A5PRIME_GO=1 且 --go；零调用。", file=sys.stderr)
        sys.exit(3)
    if not _freeze_ok():
        print("FREEZE mismatch: 执行器 sha 与冻结清单不一致；零调用。", file=sys.stderr)
        sys.exit(4)
    try:
        if a.cmd in ("c0p", "all"):
            c0p()
        if a.cmd in ("run1-c", "all"):
            arm("C")
        if a.cmd in ("run1-b", "all"):
            arm("B")
    except Halt as e:
        print(f"HALT: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
