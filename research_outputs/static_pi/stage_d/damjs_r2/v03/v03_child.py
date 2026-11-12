"""DAMJS_V03_PILOT child: ONE execution on the A‴ executor with the V0.3 bridge.

Same environment contract as damjs_r2_child.py, which it imports read-only for the identity check,
the replay transport and the harness provider. The only difference from the R2 child is the policy
wiring: damjs_v03.install with the arm's (nd, ev) switches. All four arms run this same code and
differ only in the two switches (the R2 arm = both off, regression-verified in test_damjs_v03 N6).
"""
import json
import os
import sys
import time
from pathlib import Path

LAUNCH_WALL = float(os.environ.get("APILOT_LAUNCH_WALL") or time.time())
HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import damjs_r2_child as R2C   # replay mode: installs the network tripwire and strips credentials on import
import damjs_v03 as V03

SDE = R2C.SDE
E = os.environ
ARMS = {"R2": (False, False), "ND-only": (True, False), "EV-only": (False, True), "V0.3": (True, True)}
STRICT, UNSUPPORTED = "CORRECT_GOLD", "CORRECT_BUT_UNSUPPORTED_CITATION"


def load_fixture(path):
    """Upstream fixture from a generation run: the fixture_call events (full response per call, in
    order per node) recorded at the transport level."""
    fixture = {}
    for line in Path(path).read_text("utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("ev") == "fixture_call":
                fixture.setdefault(r["node"], []).append(dict(text=r["text"], in_=r["in"], out=r["out"], wall=r["wall"]))
    return fixture


def recording_transport(clock, base_for_node, progress, recorded):
    """Generation mode: pass calls through and record each full successful response."""
    def for_node(node):
        base = base_for_node(node)

        def fn(alias, system, user, max_tokens, timeout_s, temperature):
            t0 = clock.now()
            r = base(alias, system, user, max_tokens, timeout_s, temperature)
            wall = round(clock.now() - t0, 3)
            progress.write(dict(ev="fixture_call", node=node, text=r.get("text") or "", **{"in": int(r.get("in", 0))},
                                out=int(r.get("out", 0)), wall=wall, valid=V03._valid(r.get("text"))))
            recorded.setdefault(node, []).append(V03._valid(r.get("text")))
            return r
        return fn
    return for_node


def controlled_transport(clock, base_for_node, fixture, inject, log):
    """Per node: serve the upstream fixture entries first, then the injection for the J1 repair call,
    otherwise delegate to the base transport (real API in real mode)."""
    import threading
    used, lock = {}, threading.Lock()

    def for_node(node):
        base = base_for_node(node)

        def fn(alias, system, user, max_tokens, timeout_s, temperature):
            with lock:
                i = used.get(node, 0)
                used[node] = i + 1
            served = (fixture or {}).get(node) or []
            if i < len(served):
                e = served[i]
                clock.sleep(float(e["wall"]))
                log.append(dict(node=node, call=i + 1, source="fixture"))
                return {"text": e["text"], "in": e["in_"], "out": e["out"], "stop": "end_turn", "lat": e["wall"]}
            if inject and node == inject["node"] and i == len(served):
                w = float(inject["wall"])
                if timeout_s is not None and w > timeout_s:
                    clock.sleep(timeout_s)
                    log.append(dict(node=node, call=i + 1, source="injected", truncated=True))
                    raise TimeoutError(f"injected wall {w}s > socket timeout {timeout_s:.1f}s")
                clock.sleep(w)
                log.append(dict(node=node, call=i + 1, source="injected"))
                return {"text": inject["text"], "in": int(inject["in"]), "out": int(inject["out"]),
                        "stop": "max_tokens", "lat": w, "_injected": True}
            log.append(dict(node=node, call=i + 1, source="live"))
            return base(alias, system, user, max_tokens, timeout_s, temperature)
        return fn
    return for_node


def main():
    label, scen, rep = E["APILOT_ARM"], E["APILOT_SCEN"], int(E["APILOT_REP"])
    if label not in ARMS:
        raise ValueError(f"UNKNOWN_ARM_LABEL:{label!r}")
    nd, ev = ARMS[label]
    deadline = float(E["APILOT_DEADLINE"])
    mode = R2C.MODE
    if mode not in ("real", "replay"):
        raise SystemExit(f"REFUSED: unknown APILOT_MODE {mode!r}")
    if mode == "real" and E.get("STAGE_D_REAL_CALLS_AUTHORIZED") != "1":
        raise SystemExit("REFUSED: real mode requires STAGE_D_REAL_CALLS_AUTHORIZED=1")
    progress = R2C.BR.Progress(E["APILOT_PROGRESS"])
    ident_pre = R2C.verify_identity(E.get("APILOT_MANIFEST"))

    cfg = SDE.load_config(STAGE_D / "stage_d_v2_executor_config.json")
    caps = json.loads(E["APILOT_CAPS"])
    cfg["global"].update(calls=int(caps["calls"]), yuan=float(caps["yuan"]), tokens=int(caps["tokens"]))
    if mode == "real":
        clock = SDE.make_clock(True, cfg["mock"]["scale"])
        base_for_node = lambda node: SDE.stage_d_real_transport
    else:
        clock = SDE.VirtualClock(float(E.get("APILOT_CLOCK_SCALE", "1")))
        base_for_node = R2C.replay_transport(clock, E["APILOT_REPLAY_SRC"])
    fixture = load_fixture(E["APILOT_UPSTREAM_FIXTURE"]) if E.get("APILOT_UPSTREAM_FIXTURE") else None
    inject = json.loads(E["APILOT_INJECT"]) if E.get("APILOT_INJECT") else None
    gen_stop = E.get("APILOT_GEN_STOP_AFTER") or None
    controlled_log, recorded = [], {}
    if fixture or inject:
        base_for_node = controlled_transport(clock, base_for_node, fixture, inject, controlled_log)
    if gen_stop:
        base_for_node = recording_transport(clock, base_for_node, progress, recorded)
    state_dir, exec_dir = Path(E["APILOT_STATE"]), Path(E["APILOT_EXEC_DIR"])
    gb = SDE.GlobalBudget(cfg["global"]["calls"], cfg["global"]["yuan"], cfg["global"]["tokens"], state_dir)
    slots = SDE.SlotManager(cfg["slots"], clock)
    store = SDE.RunStore(state_dir, exec_dir)
    provider = R2C.HarnessProvider(clock, slots, base_for_node)

    offset = (time.time() - LAUNCH_WALL) * clock.scale
    deadline_ex = deadline - offset
    cfg["deadline_s"]["default"] = deadline_ex
    cfg["deadline_s"][scen] = deadline_ex
    ex = SDE.FinalExec("Proposed-Dynamic", scen, rep, cfg, clock, gb, slots, provider, store,
                       dry_run=(mode != "real"))
    ex.exec_id = f"{label}|{scen}|r{rep}|D{int(deadline)}" + (f"|{E['APILOT_RUN_TAG']}" if E.get("APILOT_RUN_TAG") else "")
    harness, bridge = V03.install(ex, ex.deadline_s, progress, E.get("APILOT_CANCEL"), routing=SDE.AROUT,
                                  repair_lib=SDE.D2.REPAIR_LIB, nd=nd, ev=ev)
    provider.harness = harness
    ex.arm = label
    if gen_stop:
        inner_call = ex.call

        def gen_call(node, _inner=inner_call):
            out = _inner(node)
            if node == gen_stop and any(recorded.get(node) or []):
                progress.write(dict(ev="fixture_complete", stop_after=node, nodes=sorted(ex.outputs),
                                    identity_pre_ok=ident_pre.get("verified"), network_attempts=R2C.NET["attempts"]))
                os._exit(0)
            return out
        ex.call = gen_call
    progress.write(dict(ev="exec_start", arm=label, executor_arm="Proposed-Dynamic", policy="damjs_v03.BridgeV03",
                        nd=nd, ev_gate=ev, scen=scen, rep=rep, deadline=deadline,
                        deadline_ex=round(deadline_ex, 3), startup_offset_s=round(offset, 3), mode=mode,
                        identity_pre_ok=ident_pre.get("verified")))
    t0 = time.time()
    ret = ex.run()
    ret = ret if isinstance(ret, dict) else {}
    ident_post = R2C.verify_identity(E.get("APILOT_MANIFEST"))
    score = ret.get("score") or {}
    claims = score.get("claim_results") or []
    result = dict(
        batch=E.get("APILOT_BATCH"), arm=label, executor_arm="Proposed-Dynamic", policy_source="damjs_v03.BridgeV03",
        nd=nd, ev_gate=ev, scenario=scen, rep=rep, deadline_s=deadline, deadline_ex_s=round(deadline_ex, 3),
        startup_offset_s=round(offset, 3), mode=mode, exec_id=ex.exec_id,
        status=ret.get("status"), tp=ret.get("tp"), tp_strict=sum(c["status"] == STRICT for c in claims),
        unsupported=sorted(c["fact_id"] for c in claims if c["status"] == UNSUPPORTED),
        slot_success=score.get("slot_success"), makespan_s=ret.get("makespan_s"),
        elapsed_since_launch_s=round(time.time() - LAUNCH_WALL, 2),
        calls=ret.get("calls"), tokens_in=ret.get("tokens_in"), tokens_out=ret.get("tokens_out"),
        accounting_yuan=ret.get("accounting_yuan"), actual_cash_yuan=ret.get("actual_cash_yuan"),
        actions=ret.get("actions"), decisions=ret.get("decisions"), anomalies=ret.get("anomalies"),
        final_states=ret.get("final_states"), invalid_reason=ret.get("invalid_reason"),
        per_node_calls={n: [c["alias"] for c in ret.get("raw", {}).get("calls", []) if c["node"] == n]
                        for n in ex.spec},
        exec_record=str(store.record_path(ex.exec_id)), bridge=bridge.summary(),
        controlled_injection=bool(fixture or inject), controlled_log=controlled_log,
        injected_calls=[c for c in controlled_log if c["source"] == "injected"],
        network_attempts=R2C.NET["attempts"], wall_s=round(time.time() - t0, 2),
        identity=dict(pre=ident_pre, post=ident_post,
                      ok=bool(ident_pre.get("verified")) and bool(ident_post.get("verified"))))
    tmp = Path(E["APILOT_OUT"] + ".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, E["APILOT_OUT"])
    progress.write(dict(ev="exec_end", arm=label, tp=result["tp"], tp_strict=result["tp_strict"],
                        status=result["status"], network_attempts=R2C.NET["attempts"]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as e:
        if str(e).startswith("UNKNOWN_ARM_LABEL"):
            print(str(e), file=sys.stderr)
            sys.exit(3)
        raise
