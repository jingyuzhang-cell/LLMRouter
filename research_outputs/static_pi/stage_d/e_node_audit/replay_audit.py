#!/usr/bin/env python3
"""E-node compatibility audit: zero-call replay (2026-11-06).

Recorded responses from the 192-run Stage D archive (runs_final/) are fed through each
executor's own real-mode handle class (_RealHandle), which is the code path a real batch
uses. The network is disabled by a tripwire, credential env vars are removed, all budget
and run-store state goes to throwaway temp dirs, and no frozen file is written.

Experiments
  X1  base executor 64dea819 + base config, mirroring the D3 probe (Current-Proposed|S3|r1, 240 s)
  X2  unit check: base _finish_call on a completed real handle -> capture the exception
  X3  V2 executor e80fe6a3 + V2 config, replaying Static/Proposed-Dynamic x S3/S4 r1
  X4  V2 with the runner's unmapped arm name 'Current-Proposed' (Proposed-Dynamic|S3|r1 responses)
  X5  V2 with the child's DAMJS policy closure (Proposed-Dynamic|S3/S4|r1 responses)
"""
import http.client
import socket
import urllib.request

NET = {"attempts": 0}


def _tripwire(*a, **k):
    NET["attempts"] += 1
    raise RuntimeError("NETWORK_TRIPWIRE: zero-call audit")


urllib.request.urlopen = _tripwire
socket.create_connection = _tripwire
http.client.HTTPConnection.connect = _tripwire
http.client.HTTPSConnection.connect = _tripwire

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

for k in ("STAGE_D_GLM_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(k, None)

HERE = Path("/root/research_outputs/static_pi/stage_d")
OUT = HERE / "e_node_audit"
RUNS = HERE / "runs_final"
sys.path.insert(0, str(HERE))

FILES = ["stage_d_executor.py", "stage_d_executor_config.json", "stage_d_v2_executor.py",
         "stage_d_v2_executor_config.json", "d2_executor.py", "_damsj_real_child.py",
         "damsj_engine.py", "damsj_pilot_runner.py", "damsj_executor.py",
         "DAMJS_BATCH_MANIFEST.json"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


SHA_BEFORE = {f: sha(HERE / f) for f in FILES}


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, HERE / fname)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


BASE = load("sde_base", "stage_d_executor.py")
V2 = load("sde_v2", "stage_d_v2_executor.py")


def record(exec_id):
    return json.loads((RUNS / (exec_id.replace("|", "__") + ".json")).read_text("utf-8"))


def replay_provider(SDE, clock, slots, rec):
    """RealProvider subclass whose handles are the executor's own _RealHandle, with a
    transport function that serves the recorded raw response for the requesting node
    (in recorded order; if a node asks for more calls than were recorded, the last
    entry is served again and flagged repeated=True)."""
    nodes = rec["raw"]["nodes"]
    idx, log, lock = {}, [], threading.Lock()

    def fn_for(node):
        def fn(alias, system, user, max_tokens, timeout_s, temperature):
            with lock:
                i = idx.get(node, 0)
                idx[node] = i + 1
            entries = nodes.get(node) or []
            if not entries:
                log.append(dict(node=node, requested_alias=alias, requested_max_tokens=max_tokens,
                                served=None))
                raise RuntimeError(f"REPLAY_NO_RECORD:{node}")
            e = entries[min(i, len(entries) - 1)]
            log.append(dict(node=node, requested_alias=alias, requested_max_tokens=max_tokens,
                            served_from_model=e["model"], index=i, repeated=i >= len(entries),
                            tokens_in=e["in"], tokens_out=e["out"]))
            return {"text": e["text"], "in": e["in"], "out": e["out"], "stop": "replay",
                    "lat": e.get("latency") or 0.0}
        return fn

    class ReplayProvider(SDE.RealProvider):
        def start_call(self, alias, model, system, user, max_tokens, timeout_s=120,
                       temperature=0, node="?", cancel_effective=False):
            self.calls.append({"node": node, "alias": alias, "model": model})
            return SDE._RealHandle(fn_for(node), alias, model, system, user, max_tokens,
                                   timeout_s, temperature, self.clock, self.slots, node)

    return ReplayProvider(clock, slots, transport_fn=fn_for("?")), log


def run_exec(SDE, cfg_file, arm, scen, rep, rec, deadline=None, policy_factory=None):
    cfg = SDE.load_config(HERE / cfg_file)
    if deadline is not None:
        cfg["deadline_s"]["default"] = deadline
        cfg["deadline_s"][scen] = deadline
    tmp = Path(tempfile.mkdtemp(prefix="enode_audit_"))
    (tmp / "state").mkdir()
    clock = SDE.make_clock(True, cfg["mock"]["scale"])
    gb = SDE.GlobalBudget(cfg["global"]["calls"], cfg["global"]["yuan"],
                          cfg["global"].get("tokens"), tmp / "state")
    slots = SDE.SlotManager(cfg["slots"], clock)
    store = SDE.RunStore(tmp / "state", tmp / "out")
    prov, log = replay_provider(SDE, clock, slots, rec)
    ex = SDE.FinalExec(arm, scen, rep, cfg, clock, gb, slots, prov, store, dry_run=False)
    if policy_factory is not None:
        ex.policy = policy_factory(ex, clock)
    t0 = time.time()
    ret = ex.run()
    ret = ret if isinstance(ret, dict) else {}
    return dict(
        arm=arm, scenario=scen, rep=rep, deadline_s=ex.deadline_s,
        status=ret.get("status"), tp=ret.get("tp"), calls=ret.get("calls"),
        final_states=ret.get("final_states"),
        anomalies=[(a["node"], a["sig"]) for a in ret.get("anomalies") or []],
        decisions=[(d["node"], d["sig"], d["acts"]) for d in ret.get("decisions") or []],
        actions=ret.get("actions"),
        raw_calls_recorded=len((ret.get("raw") or {}).get("calls") or []),
        exec_log_len=len(ret.get("exec_log") or []),
        tokens_in=ret.get("tokens_in"), tokens_out=ret.get("tokens_out"),
        slots_max_seen=(ret.get("slots") or {}).get("max_seen"),
        invalid_reason=ret.get("invalid_reason"),
        call_sequence=[f"{c['node']}<-{c['requested_alias']}@{c['requested_max_tokens']}"
                       + ("(REPEATED)" if c.get("repeated") else "") for c in log],
        any_repeated=any(c.get("repeated") for c in log),
        wall_s=round(time.time() - t0, 1),
    )


def original(exec_id):
    d = record(exec_id)
    return dict(status=d["status"], tp=d["tp"], calls=d["calls"], final_states=d["final_states"],
                call_sequence=[f"{c['node']}<-{c['alias']}" for c in d["raw"]["calls"]],
                deadline_s=d["deadline_s"])


results = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "experiments": {}}
X = results["experiments"]

# X1: mirror the D3 probe exactly (base executor, base config, Current-Proposed|S3|r1, 240 s).
probe = json.loads(Path("/tmp/Current-Proposed__S3__r1.json").read_text("utf-8"))
X["X1_base_mirror_of_D3_probe"] = dict(
    replay_source="Proposed-Dynamic|S3|r1",
    replay=run_exec(BASE, "stage_d_executor_config.json", "Current-Proposed", "S3", 1,
                    record("Proposed-Dynamic|S3|r1"), deadline=240.0),
    probe_record=dict(status=probe["status"], calls=probe["calls"],
                      final_states=probe["final_states"],
                      anomalies=[(a["node"], a["sig"]) for a in probe["anomalies"]],
                      raw_calls_recorded=len(probe["raw"]["calls"]),
                      exec_log_len=len(probe["exec_log"]),
                      tokens_in=probe["tokens_in"], tokens_out=probe["tokens_out"],
                      slots_max_seen=probe["slots"]["max_seen"]))

# X2: direct exception capture on the base real handle.
cfg = BASE.load_config(HERE / "stage_d_executor_config.json")
tmp = Path(tempfile.mkdtemp(prefix="enode_audit_unit_"))
(tmp / "state").mkdir()
clock = BASE.make_clock(True, cfg["mock"]["scale"])
gb = BASE.GlobalBudget(cfg["global"]["calls"], cfg["global"]["yuan"], cfg["global"].get("tokens"),
                       tmp / "state")
slots = BASE.SlotManager(cfg["slots"], clock)
store = BASE.RunStore(tmp / "state", tmp / "out")
unit = {}
for label, text in (("recorded_deepseek_contract_json", record("Static|S3|r1")["raw"]["nodes"]["E1"][0]["text"]),
                    ("empty_text", "")):
    prov, _ = replay_provider(BASE, clock, slots, {"raw": {"nodes": {"E1": [
        {"model": "stub", "text": text, "in": 565, "out": 2000, "latency": 0.0}]}}})
    ex = BASE.FinalExec("Static", "S3", 1, cfg, clock, gb, slots, prov, store, dry_run=False)
    ex.t0 = clock.now()
    h = ex._call("E1", "glm53flash", "glm53flash", "sys", "user", 2000)
    try:
        ex._finish_call("E1", h, 1)
        unit[label] = dict(raised=None)
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)[-1]
        unit[label] = dict(raised=f"{type(e).__name__}: {e}", at=f"{Path(tb.filename).name}:{tb.lineno}",
                           line=tb.line, tokens_settled_before_raise=dict(in_=ex.tokens_in, out=ex.tokens_out),
                           raw_calls_recorded=len(ex.raw["calls"]))
unit["v2_RealHandle_has_latency_attr"] = hasattr(
    V2._RealHandle(lambda *a: None, "x", "x", "", "", 1, 1, None, clock, slots, "E1"), "latency")
unit["base_RealHandle_has_latency_attr"] = hasattr(
    BASE._RealHandle(lambda *a: None, "x", "x", "", "", 1, 1, None, clock, slots, "E1"), "latency")
X["X2_unit_finish_call"] = unit

# X3: V2 replays vs the original 192-run records.
X["X3_v2_replay_vs_original"] = {}
for eid in ("Static|S3|r1", "Proposed-Dynamic|S3|r1", "Static|S4|r1", "Proposed-Dynamic|S4|r1"):
    arm, sc, r = eid.split("|")
    X["X3_v2_replay_vs_original"][eid] = dict(
        replay=run_exec(V2, "stage_d_v2_executor_config.json", arm, sc, int(r[1:]), record(eid)),
        original=original(eid))

# X4: the runner's arm label passed through unmapped.
X["X4_v2_unmapped_arm_label"] = dict(
    replay_source="Proposed-Dynamic|S3|r1",
    as_Current_Proposed=run_exec(V2, "stage_d_v2_executor_config.json", "Current-Proposed", "S3", 1,
                                 record("Proposed-Dynamic|S3|r1")),
    as_Proposed_Dynamic=run_exec(V2, "stage_d_v2_executor_config.json", "Proposed-Dynamic", "S3", 1,
                                 record("Proposed-Dynamic|S3|r1")))

# X5: the child's DAMJS policy closure on V2 (child imported with stage_d_executor aliased to V2).
tmpd = Path(tempfile.mkdtemp(prefix="enode_audit_damjs_"))
os.environ.update(APILOT_ARM="DAMJS", APILOT_SCEN="S3", APILOT_REP="1", APILOT_DEADLINE="300",
                  APILOT_OUT=str(tmpd / "out.json"), APILOT_PROGRESS=str(tmpd / "progress.jsonl"),
                  APILOT_CANCEL=str(tmpd / "cancel_absent"), APILOT_BATCH="E_NODE_AUDIT_REPLAY")
sys.modules["stage_d_executor"] = V2
CHILD = load("damsj_real_child_audit", "_damsj_real_child.py")
from damsj_engine import History


def damjs_policy_factory(ex, clock):
    hist, started = History(), [None]

    def wrapped(node, sig):
        if started[0] is None:
            started[0] = clock.now()
        return CHILD.make_damsj_policy(ex, hist, clock, started[0])(node, sig)
    return wrapped


X["X5_v2_damjs_closure"] = {}
for eid in ("Proposed-Dynamic|S3|r1", "Proposed-Dynamic|S4|r1"):
    _, sc, r = eid.split("|")
    X["X5_v2_damjs_closure"][eid] = run_exec(V2, "stage_d_v2_executor_config.json", "Proposed-Dynamic",
                                             sc, int(r[1:]), record(eid),
                                             policy_factory=damjs_policy_factory)
X["X5_v2_damjs_closure"]["progress_events"] = [
    json.loads(l) for l in (tmpd / "progress.jsonl").read_text().splitlines() if l.strip()
] if (tmpd / "progress.jsonl").exists() else []

SHA_AFTER = {f: sha(HERE / f) for f in FILES}
results["integrity"] = dict(network_attempts=NET["attempts"],
                            files_unchanged=SHA_BEFORE == SHA_AFTER,
                            sha256=SHA_AFTER)
(OUT / "REPLAY_AUDIT_RESULTS.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
print(json.dumps(results, ensure_ascii=False, indent=1))
