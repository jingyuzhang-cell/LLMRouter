"""DAMJS_EXP_36 child: runs ONE execution on the A‴ executor (stage_d_v2_executor.py).

Env (set by damjs_r2_runner.py):
  APILOT_ARM / APILOT_SCEN / APILOT_REP / APILOT_DEADLINE   execution coordinates (arm = batch label)
  APILOT_MODE            'real' | 'replay'   (replay = recorded responses through the same real handle)
  APILOT_LAUNCH_WALL     wall time at which the parent watchdog started (deadline anchor, M5)
  APILOT_STATE           batch state dir: shared cross-process GlobalBudget ledger (M3)
  APILOT_EXEC_DIR        directory for the executor's full record (unique exec_id per execution)
  APILOT_CAPS            JSON {"calls","tokens","yuan"}: batch hard caps enforced by GlobalBudget (M3)
  APILOT_OUT / APILOT_PROGRESS / APILOT_CANCEL / APILOT_BATCH / APILOT_MANIFEST
  APILOT_REPLAY_SRC      replay mode only: recorded execution whose raw node responses are served
  APILOT_CLOCK_SCALE     replay mode only: VirtualClock scale (real mode is always 1.0)
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

LAUNCH_WALL = float(os.environ.get("APILOT_LAUNCH_WALL") or time.time())
HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, str(HERE))
E = os.environ
MODE = E.get("APILOT_MODE", "replay")
NET = {"attempts": 0}

if MODE == "replay":
    import http.client
    import socket
    import urllib.request

    def _tripwire(*a, **k):
        NET["attempts"] += 1
        raise RuntimeError("NETWORK_TRIPWIRE: replay mode is zero-call")

    urllib.request.urlopen = _tripwire
    socket.create_connection = _tripwire
    http.client.HTTPConnection.connect = _tripwire
    http.client.HTTPSConnection.connect = _tripwire
    for _k in ("STAGE_D_GLM_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(_k, None)

import stage_d_v2_executor as SDE
import damjs_bridge as BR


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def verify_identity(manifest_path):
    if not manifest_path:
        return dict(verified=None, reason="no_manifest")
    mf = json.loads(Path(manifest_path).read_text("utf-8"))
    mism, comps = [], {}
    for c in mf["components"]:
        if not c.get("runtime"):
            continue
        p = c["path"] if os.path.isabs(c["path"]) else str(STAGE_D / c["path"])
        actual = sha_file(p) if os.path.exists(p) else "ABSENT"
        comps[f"{c['role']}:{c['path']}"] = actual
        if actual != c["sha256"]:
            mism.append(dict(role=c["role"], path=c["path"], expected=c["sha256"], actual=actual))
    return dict(verified=not mism, mismatches=mism, components=comps,
                manifest_sha256=sha_file(manifest_path), batch_id=mf.get("batch_id"))


def replay_transport(clock, src_path):
    """Serves recorded responses per node in order, sleeping recorded pure call time (exec_log
    wall) on the executor clock; honours the socket timeout unless the entry sets ignore_timeout."""
    import collections
    import threading
    rec = json.loads(Path(src_path).read_text("utf-8"))
    nodes = rec["raw"]["nodes"]
    walls = collections.defaultdict(list)
    for x in rec.get("exec_log") or []:
        if x.get("node") in nodes:
            walls[x["node"]].append(float(x.get("wall") or 0.0))
    idx, lock = {}, threading.Lock()

    def for_node(node):
        def fn(alias, system, user, max_tokens, timeout_s, temperature):
            with lock:
                i = idx.get(node, 0)
                idx[node] = i + 1
            entries = nodes.get(node) or []
            if not entries:
                raise RuntimeError(f"REPLAY_NO_RECORD:{node}")
            e = entries[min(i, len(entries) - 1)]
            w = walls[node]
            call_s = float(e["wall_override"]) if "wall_override" in e else (
                w[i] if len(w) == len(entries) and i < len(w) else float(e.get("latency") or 0.0))
            if not e.get("ignore_timeout") and timeout_s is not None and call_s > timeout_s:
                clock.sleep(timeout_s)
                raise TimeoutError(f"replay call exceeded socket timeout {timeout_s:.1f}s")
            clock.sleep(call_s)
            if e.get("latency") is None and not e.get("text") and not e.get("out"):
                raise RuntimeError("REPLAYED_TRANSPORT_ERROR")
            out = int(e["out"])
            capped = out >= int(max_tokens)
            stop = (("max_tokens" if capped else "end_turn") if alias in ("glm53flash", "glm53")
                    else ("length" if capped else "stop"))
            return {"text": e["text"], "in": int(e["in"]), "out": out, "stop": stop, "lat": call_s}
        return fn
    return for_node


class HarnessProvider(SDE.RealProvider):
    """The executor's own _RealHandle with the harness transport wrapper (L2/L3/ledger events)."""

    def __init__(self, clock, slots, base_for_node):
        super().__init__(clock, slots, transport_fn=base_for_node("?"))
        self.base_for_node = base_for_node
        self.harness = None

    def start_call(self, alias, model, system, user, max_tokens, timeout_s=120,
                   temperature=0, node="?", cancel_effective=False):
        self.calls.append({"node": node, "alias": alias, "model": model})
        fn = self.harness.wrap_transport(node, self.base_for_node(node))
        return SDE._RealHandle(fn, alias, model, system, user, max_tokens, timeout_s,
                               temperature, self.clock, self.slots, node)


def main():
    label, scen, rep = E["APILOT_ARM"], E["APILOT_SCEN"], int(E["APILOT_REP"])
    deadline = float(E["APILOT_DEADLINE"])
    exec_arm, policy_source = BR.resolve_arm(label)
    if MODE not in ("real", "replay"):
        raise SystemExit(f"REFUSED: unknown APILOT_MODE {MODE!r}")
    if MODE == "real" and E.get("STAGE_D_REAL_CALLS_AUTHORIZED") != "1":
        raise SystemExit("REFUSED: real mode requires STAGE_D_REAL_CALLS_AUTHORIZED=1")
    progress = BR.Progress(E["APILOT_PROGRESS"])
    ident_pre = verify_identity(E.get("APILOT_MANIFEST"))

    cfg = SDE.load_config(STAGE_D / "stage_d_v2_executor_config.json")
    caps = json.loads(E["APILOT_CAPS"])
    cfg["global"]["calls"] = int(caps["calls"])
    cfg["global"]["yuan"] = float(caps["yuan"])
    cfg["global"]["tokens"] = int(caps["tokens"])
    if MODE == "real":
        clock = SDE.make_clock(True, cfg["mock"]["scale"])
        base_for_node = lambda node: SDE.stage_d_real_transport
    else:
        clock = SDE.VirtualClock(float(E.get("APILOT_CLOCK_SCALE", "1")))
        base_for_node = replay_transport(clock, E["APILOT_REPLAY_SRC"])
    scale = clock.scale
    state_dir, exec_dir = Path(E["APILOT_STATE"]), Path(E["APILOT_EXEC_DIR"])
    gb = SDE.GlobalBudget(cfg["global"]["calls"], cfg["global"]["yuan"], cfg["global"]["tokens"], state_dir)
    slots = SDE.SlotManager(cfg["slots"], clock)
    store = SDE.RunStore(state_dir, exec_dir)
    provider = HarnessProvider(clock, slots, base_for_node)

    offset = (time.time() - LAUNCH_WALL) * scale
    deadline_ex = deadline - offset
    cfg["deadline_s"]["default"] = deadline_ex
    cfg["deadline_s"][scen] = deadline_ex
    ex = SDE.FinalExec(exec_arm, scen, rep, cfg, clock, gb, slots, provider, store,
                       dry_run=(MODE != "real"))
    ex.exec_id = f"{label}|{scen}|r{rep}|D{int(deadline)}"
    harness = BR.Harness(ex, ex.deadline_s, progress, E.get("APILOT_CANCEL"), routing=SDE.AROUT)
    provider.harness = harness
    harness.install_progress()
    bridge = None
    if label == "DAMJS":
        bridge = BR.SchedulerBridge(harness, SDE.D2.REPAIR_LIB)
        ex.policy = bridge.policy
        ex.arm = "DAMJS"
    progress.write(dict(ev="exec_start", arm=label, executor_arm=exec_arm, policy=policy_source,
                        scen=scen, rep=rep, deadline=deadline, deadline_ex=round(deadline_ex, 3),
                        startup_offset_s=round(offset, 3), mode=MODE,
                        identity_pre_ok=ident_pre.get("verified")))
    t0 = time.time()
    ret = ex.run()
    ret = ret if isinstance(ret, dict) else {}
    ident_post = verify_identity(E.get("APILOT_MANIFEST"))
    score = ret.get("score") or {}
    result = dict(
        batch=E.get("APILOT_BATCH"), arm=label, executor_arm=exec_arm, policy_source=policy_source,
        scenario=scen, rep=rep, deadline_s=deadline, deadline_ex_s=round(deadline_ex, 3),
        startup_offset_s=round(offset, 3), mode=MODE, exec_id=ex.exec_id,
        status=ret.get("status"), tp=ret.get("tp"), slot_success=score.get("slot_success"),
        makespan_s=ret.get("makespan_s"), elapsed_since_launch_s=round(time.time() - LAUNCH_WALL, 2),
        calls=ret.get("calls"), tokens_in=ret.get("tokens_in"), tokens_out=ret.get("tokens_out"),
        accounting_yuan=ret.get("accounting_yuan"), actual_cash_yuan=ret.get("actual_cash_yuan"),
        actions=ret.get("actions"), decisions=ret.get("decisions"), anomalies=ret.get("anomalies"),
        final_states=ret.get("final_states"), invalid_reason=ret.get("invalid_reason"),
        per_node_calls={n: [c["alias"] for c in ret.get("raw", {}).get("calls", []) if c["node"] == n]
                        for n in ex.spec},
        exec_record=str(store.record_path(ex.exec_id)),
        bridge=bridge.summary() if bridge else None,
        network_attempts=NET["attempts"], wall_s=round(time.time() - t0, 2),
        identity=dict(pre=ident_pre, post=ident_post,
                      ok=bool(ident_pre.get("verified")) and bool(ident_post.get("verified"))))
    tmp = Path(E["APILOT_OUT"] + ".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, E["APILOT_OUT"])
    progress.write(dict(ev="exec_end", arm=label, tp=result["tp"], status=result["status"],
                        network_attempts=NET["attempts"]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as e:
        if str(e).startswith("UNKNOWN_ARM_LABEL"):
            print(str(e), file=sys.stderr)
            sys.exit(3)
        raise
