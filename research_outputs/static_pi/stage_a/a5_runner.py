#!/usr/bin/env python3
"""A5 结构实验（B/C 双臂）— 标准 API 通道执行器。

环境变更（必须随结果报告）：
  端点 = https://open.bigmodel.cn/api/paas/v4/chat/completions（资源包）
  模型 = glm-5.3-flash
  thinking = 无法关闭（该端点对 disabled 返回 code 1210；默认强制思考）
  ⇒ 与历史 A 臂（订阅端点 + thinking disabled）**环境不同，A 仅作参考不可比**；
    B vs C 同环境同上游，**内部对照有效**。
"""
import json, os, random, re, sys, time, urllib.request, urllib.error
from pathlib import Path

sys.path.insert(0, "/root/research_outputs/static_pi/stage_a")
from executor import (E_SYSTEM, E_POSITION_ADDENDUM, J1_SYSTEM, RELAY_ADDENDUM,
                      J1_POSITIONS_ADDENDUM, J2_SYSTEM, DISAMBIG_ADDENDUM,
                      SINK_SYSTEM, e_user, j1_user, j2_user, sink_user, sha)

KEY = "9c1234c8251f40ca9734fbc6706744d2.tizj8XGWxlGdKjAl"
URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-5.3-flash"
MAXTOK = {"E": 8000, "J1": 8000, "J2": 8000, "SINK": 8000}  # 强制思考端点：thinking 先耗配额，历史预算会截断
HERE = Path("/root/research_outputs/static_pi/stage_a/runs_a5")


def call(layer, system, user, node, out_dir, max_tokens=None):
    body = {"model": MODEL, "max_tokens": max_tokens or MAXTOK[layer],
            "temperature": 0,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + KEY)
    meta = {"node": node, "layer": layer, "endpoint": URL, "model": MODEL,
            "thinking": "forced_on(default)", "max_tokens": body["max_tokens"],
            "temperature": 0, "prompt_sha256": sha(system + "||" + user),
            "system": system, "user": user}
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read()); u = d["usage"]
        txt = d["choices"][0]["message"].get("content", "") or ""
        meta.update({"wall_s": round(time.monotonic() - t0, 2), "error": None,
                     "usage": {"in": u["prompt_tokens"], "out": u["completion_tokens"],
                               "reasoning": u.get("completion_tokens_details", {}).get("reasoning_tokens")},
                     "stop": d["choices"][0].get("finish_reason"), "text": txt})
    except Exception as e:
        meta.update({"wall_s": round(time.monotonic() - t0, 2), "error": repr(e)[:200],
                     "usage": None, "stop": None, "text": ""})
    i, j = meta["text"].find("{"), meta["text"].rfind("}")
    meta["parsed"] = None
    if i >= 0 and j > i:
        try: meta["parsed"] = json.loads(meta["text"][i:j+1])
        except json.JSONDecodeError: pass
    meta["json_ok"] = meta["parsed"] is not None
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{node}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    print(f"  {node}: json_ok={meta['json_ok']} stop={meta['stop']} "
          f"in/out={meta['usage'] and (meta['usage']['in'], meta['usage']['out'])} "
          f"wall={meta['wall_s']}s {'ERR=' + meta['error'] if meta['error'] else ''}", flush=True)
    return meta


def run_sample(k, first):
    """方案A（操作者批准）：E1P/E2P 复用 X 链冻结输出；只新跑 J1/J2/SINK；B/C 串行随机顺序。"""
    out = HERE / f"run{k}"
    print(f"=== A5 run{k}（先 {first}）===")
    e1 = json.loads((Path(f"/root/research_outputs/static_pi/stage_a/runs_x/run{k}/E1P.json")).read_text("utf-8"))
    e2 = json.loads((Path(f"/root/research_outputs/static_pi/stage_a/runs_x/run{k}/E2P.json")).read_text("utf-8"))
    up = json.dumps({"E1": e1["text"], "E2": e2["text"]}, ensure_ascii=False)
    ju = j1_user(up)
    res = {}
    for arm in (first, "C" if first == "B" else "B"):
        j1sys = (J1_SYSTEM + RELAY_ADDENDUM) if arm == "B" else (J1_SYSTEM + RELAY_ADDENDUM + J1_POSITIONS_ADDENDUM)
        j1 = call("J1", j1sys, ju, f"{arm}_J1", out)
        j2 = call("J2", J2_SYSTEM + DISAMBIG_ADDENDUM,
                  j2_user(json.dumps({"J1": j1["text"], "E3": json.loads((Path("/root/research_outputs/static_pi/stage_a/runs/run%d/E3.json" % k)).read_text())["text"],
                                      "E4": json.loads((Path("/root/research_outputs/static_pi/stage_a/runs/run%d/E4.json" % k)).read_text())["text"]}, ensure_ascii=False)),
                  f"{arm}_J2", out)
        sink = call("SINK", SINK_SYSTEM,
                    sink_user(json.dumps({"J1": j1["text"], "J2": j2["text"]}, ensure_ascii=False)),
                    f"{arm}_SINK", out)
        res[arm] = sink
    return res


if __name__ == "__main__":
    k = int(sys.argv[1]); first = sys.argv[2] if len(sys.argv) > 2 else "B"
    run_sample(k, first)
