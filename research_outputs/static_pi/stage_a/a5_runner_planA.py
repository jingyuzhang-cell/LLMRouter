#!/usr/bin/env python3
"""A5 结构实验 Plan A 执行器 — 订阅端点 + thinking disabled + 历史 max_tokens。

与 a5_runner.py（资源包端点，thinking 强制开启）的区别仅限传输环境：
  端点 = https://open.bigmodel.cn/api/anthropic/v1/messages
  模型 = GLM-5.3-Flash（alias glm53flash）
  thinking = {"type": "disabled"}（源码固定，与历史 X 链一致）
  max_tokens = 历史冻结值 J1 2500 / J2 3500 / SINK 4000；temperature = 0
  凭据 = 环境变量 A5_GLM_KEY（不落盘、不写元数据、不打印）

提示词、上游输入、评分器、合同均未改动。dry 模式零调用：只构建并核验哈希。
任何 HTTP 错误 / stop != end_turn / JSON 解析失败 → 立即抛异常停止，不重试。
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
MAXTOK = {"J1": 2500, "J2": 3500, "SINK": 4000}
TEMPERATURE = 0
HERE = STAGE / "runs_a5_planA"
PRICE = {"in": 8.0e-7, "out": 2.8e-6}
ORDER = {1: "B", 2: "C", 3: "B"}  # 预登记顺序：run1 B 先（现场延续）、run2 C 先、run3 B 先


class Halt(Exception):
    pass


def _sha(x):
    return hashlib.sha256(x.encode("utf-8")).hexdigest()


def _key():
    k = os.environ.get("A5_GLM_KEY", "").strip()
    if not k:
        raise Halt("A5_GLM_KEY 未设置（从本地环境文件注入，不写入代码/元数据）")
    return k


def build_prompts(k, arm):
    """与冻结 A5 设计逐字节一致：E 复用 X 链 E1P/E2P，仅 J1 system 因臂而异。"""
    e1 = json.loads((STAGE / "runs_x" / f"run{k}" / "E1P.json").read_text("utf-8"))
    e2 = json.loads((STAGE / "runs_x" / f"run{k}" / "E2P.json").read_text("utf-8"))
    e3 = json.loads((STAGE / "runs" / f"run{k}" / "E3.json").read_text("utf-8"))
    e4 = json.loads((STAGE / "runs" / f"run{k}" / "E4.json").read_text("utf-8"))
    j1sys = (J1_SYSTEM + RELAY_ADDENDUM) if arm == "B" else (J1_SYSTEM + RELAY_ADDENDUM + J1_POSITIONS_ADDENDUM)
    j1u = j1_user(json.dumps({"E1": e1["text"], "E2": e2["text"]}, ensure_ascii=False))
    j2sys = J2_SYSTEM + DISAMBIG_ADDENDUM
    sinku_dep = None  # J2/SINK 用户提示依赖 J1/J2 实际输出，运行期构建
    return {"J1": (j1sys, j1u, {"E1P": _sha(e1["text"]), "E2P": _sha(e2["text"])}),
            "J2": (j2sys, None, {"E3": _sha(e3["text"]), "E4": _sha(e4["text"])}),
            "SINK": (SINK_SYSTEM, sinku_dep, {})}


def call(layer, system, user, node, out_dir, upstream_sha, run=None, arm=None):
    body = {"model": MODEL, "max_tokens": MAXTOK[layer],
            "temperature": TEMPERATURE, "thinking": {"type": "disabled"},
            "system": system, "messages": [{"role": "user", "content": user}]}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=payload, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", _key())
    req.add_header("authorization", "Bearer " + _key())
    req.add_header("anthropic-version", "2023-06-01")
    meta = {"run": run, "node": node, "layer": layer, "arm": arm, "endpoint": ENDPOINT,
            "model": MODEL, "thinking": "disabled", "max_tokens": MAXTOK[layer],
            "temperature": TEMPERATURE,
            "prompt_sha256": _sha(system + "||" + user),
            "request_body_sha256": hashlib.sha256(payload).hexdigest(),
            "upstream_sha256": upstream_sha,
            "system": system, "user": user}
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            raw = r.read()
            d = json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        meta.update({"wall_s": round(time.monotonic() - t0, 2),
                     "error": f"HTTP {e.code}", "error_detail": detail,
                     "usage": None, "stop": None, "text": ""})
        _write(out_dir, node, meta)
        raise Halt(f"{node}: HTTP {e.code} -> 停止（不重试）")
    except Exception as e:  # noqa: BLE001
        meta.update({"wall_s": round(time.monotonic() - t0, 2), "error": repr(e)[:300],
                     "usage": None, "stop": None, "text": ""})
        _write(out_dir, node, meta)
        raise Halt(f"{node}: {e!r} -> 停止（不重试）")

    txt = "".join(b.get("text", "") for b in d.get("content", []) if isinstance(b, dict) and b.get("type") == "text")
    u = d.get("usage") or {}
    meta.update({"wall_s": round(time.monotonic() - t0, 2), "error": None,
                 "response_body_sha256": hashlib.sha256(raw).hexdigest(),
                 "usage": {"in": u.get("input_tokens"), "out": u.get("output_tokens")},
                 "stop": d.get("stop_reason"), "text": txt,
                 "cost_accounting_yuan": round((u.get("input_tokens") or 0) * PRICE["in"]
                                               + (u.get("output_tokens") or 0) * PRICE["out"], 8)})
    i, j = txt.find("{"), txt.rfind("}")
    parsed = None
    if i >= 0 and j > i:
        try:
            parsed = json.loads(txt[i:j + 1])
        except json.JSONDecodeError:
            parsed = None
    meta["parsed"] = parsed
    meta["json_ok"] = parsed is not None
    _write(out_dir, node, meta)
    print(f"  {node}: json_ok={meta['json_ok']} stop={meta['stop']} "
          f"in/out={meta['usage'] and (meta['usage']['in'], meta['usage']['out'])} "
          f"wall={meta['wall_s']}s", flush=True)
    if meta["stop"] != "end_turn":
        raise Halt(f"{node}: stop={meta['stop']} -> 停止（截断/异常，不重试）")
    if not meta["json_ok"]:
        raise Halt(f"{node}: JSON 解析失败 -> 停止（不重试）")
    return meta


def _write(out_dir, node, meta):
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = dict(meta)
    meta.pop("_k", None)
    (out_dir / f"{node}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")


def run_sample(k):
    first = ORDER[k]
    out = HERE / f"run{k}"
    out.mkdir(parents=True, exist_ok=True)
    p = build_prompts(k, first)
    print(f"=== A5 PlanA run{k}（先 {first}；后 {'C' if first == 'B' else 'B'}）===", flush=True)
    for arm in (first, "C" if first == "B" else "B"):
        j1sys = (J1_SYSTEM + RELAY_ADDENDUM) if arm == "B" else (J1_SYSTEM + RELAY_ADDENDUM + J1_POSITIONS_ADDENDUM)
        e1 = json.loads((STAGE / "runs_x" / f"run{k}" / "E1P.json").read_text("utf-8"))
        e2 = json.loads((STAGE / "runs_x" / f"run{k}" / "E2P.json").read_text("utf-8"))
        e3 = json.loads((STAGE / "runs" / f"run{k}" / "E3.json").read_text("utf-8"))
        e4 = json.loads((STAGE / "runs" / f"run{k}" / "E4.json").read_text("utf-8"))
        ju = j1_user(json.dumps({"E1": e1["text"], "E2": e2["text"]}, ensure_ascii=False))
        j1 = call("J1", j1sys, ju, f"{arm}_J1", out,
                  {"E1P": _sha(e1["text"]), "E2P": _sha(e2["text"])}, run=k, arm=arm)
        ju2 = j2_user(json.dumps({"J1": j1["text"], "E3": e3["text"], "E4": e4["text"]}, ensure_ascii=False))
        j2 = call("J2", J2_SYSTEM + DISAMBIG_ADDENDUM, ju2, f"{arm}_J2", out,
                  {"J1": _sha(j1["text"]), "E3": _sha(e3["text"]), "E4": _sha(e4["text"])}, run=k, arm=arm)
        ju3 = sink_user(json.dumps({"J1": j1["text"], "J2": j2["text"]}, ensure_ascii=False))
        call("SINK", SINK_SYSTEM, ju3, f"{arm}_SINK", out,
             {"J1": _sha(j1["text"]), "J2": _sha(j2["text"])}, run=k, arm=arm)
    print(f"run{k} 完成（6 调用）", flush=True)


def precheck():
    out = HERE / "precheck"
    print("=== A5 受控预检（1 调用；订阅端点 + thinking disabled + max_tokens=16）===", flush=True)
    m = call("J1", "连接预检。", "只回复 OK。", "precheck", out, {}, run=0, arm="precheck")
    m["precheck_pass"] = (m.get("stop") == "end_turn" and bool(m.get("text")))
    _write(out, "precheck", m)
    if not m["precheck_pass"]:
        raise Halt("预检未通过")
    print("预检 PASS", flush=True)


def dry():
    out = HERE / "dry"
    out.mkdir(parents=True, exist_ok=True)
    report = {"order": ORDER, "endpoint": ENDPOINT, "model": MODEL,
              "thinking": "disabled", "max_tokens": MAXTOK, "temperature": TEMPERATURE,
              "calls": [], "hashes": {}}
    for k in (1, 2, 3):
        for arm in ("B", "C"):
            j1sys = (J1_SYSTEM + RELAY_ADDENDUM) if arm == "B" else (J1_SYSTEM + RELAY_ADDENDUM + J1_POSITIONS_ADDENDUM)
            e1 = json.loads((STAGE / "runs_x" / f"run{k}" / "E1P.json").read_text("utf-8"))
            e2 = json.loads((STAGE / "runs_x" / f"run{k}" / "E2P.json").read_text("utf-8"))
            ju = j1_user(json.dumps({"E1": e1["text"], "E2": e2["text"]}, ensure_ascii=False))
            h = _sha(j1sys + "||" + ju)
            report["hashes"][f"run{k}_{arm}_J1"] = h
            report["calls"].append({"run": k, "arm": arm, "node": "J1", "prompt_sha256": h,
                                    "system_sha256": _sha(j1sys), "user_sha256": _sha(ju)})
    report["expected"] = {"B_system": "28560bc565f40d85", "C_system": "c7384236807cb9b0",
                          "note": "操作者门禁哈希为 system-only；combined 哈希另列并须与中止现场一致"}
    report["B_ok"] = all(c["system_sha256"].startswith("28560bc5") for c in report["calls"] if c["arm"] == "B")
    report["C_ok"] = all(c["system_sha256"].startswith("c7384236") for c in report["calls"] if c["arm"] == "C")
    report["combined_run1_B"] = report["hashes"]["run1_B_J1"]
    report["combined_run1_C"] = report["hashes"]["run1_C_J1"]
    (out / "A5_PLANA_DRY.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"B_ok": report["B_ok"], "C_ok": report["C_ok"],
                      "hashes": {k: v[:16] for k, v in report["hashes"].items()}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dry", "precheck", "run", "all"])
    ap.add_argument("k", nargs="?", type=int)
    a = ap.parse_args()
    try:
        if a.cmd == "dry":
            dry()
        elif a.cmd == "precheck":
            precheck()
        elif a.cmd == "run":
            run_sample(a.k)
        else:
            for k in (1, 2, 3):
                run_sample(k)
    except Halt as e:
        print(f"HALT: {e}", file=sys.stderr)
        sys.exit(2)
