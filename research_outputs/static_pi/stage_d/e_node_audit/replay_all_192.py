#!/usr/bin/env python3
"""Full 192-record replay through stage_d_v2_executor.py (zero calls, 2026-11-06).

Every record in runs_final/ is re-executed through V2's real-mode handle (_RealHandle)
with its recorded per-node responses, recorded latencies (slept on a scaled virtual
clock so wall-time-dependent branches such as S5' see the original timings) and an
inferred stop reason (cap reached -> max_tokens/length, otherwise a normal stop).
Outcome fields are compared with the original record. Network is disabled by tripwire;
state goes to a temp dir; no frozen file is written.
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

import collections
import glob
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

for k in ("STAGE_D_GLM_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(k, None)

HERE = Path("/root/research_outputs/static_pi/stage_d")
OUT = HERE / "e_node_audit"
SCALE = float(os.environ.get("REPLAY_CLOCK_SCALE", "50"))
sys.path.insert(0, str(HERE))
FILES = ["stage_d_v2_executor.py", "stage_d_v2_executor_config.json", "d2_executor.py"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


SHA_BEFORE = {f: sha(HERE / f) for f in FILES}
spec = importlib.util.spec_from_file_location("sde_v2", HERE / "stage_d_v2_executor.py")
V2 = importlib.util.module_from_spec(spec)
sys.modules["sde_v2"] = V2
spec.loader.exec_module(V2)


def inferred_stop(alias, out, max_tokens):
    capped = out is not None and max_tokens is not None and out >= max_tokens
    if alias in ("glm53flash", "glm53"):
        return "max_tokens" if capped else "end_turn"
    return "length" if capped else "stop"


def is_transport_error(e):
    # V2 _RealHandle leaves latency=None only when the transport raised; result text is "".
    return e.get("latency") is None and not e.get("text") and not e.get("out")


def provider_for(clock, slots, rec):
    nodes = rec["raw"]["nodes"]
    walls = collections.defaultdict(list)
    for x in rec.get("exec_log") or []:
        if x.get("node") in nodes:
            walls[x["node"]].append(float(x.get("wall") or 0.0))
    idx, log, lock = {}, [], threading.Lock()

    def fn_for(node):
        def fn(alias, system, user, max_tokens, timeout_s, temperature):
            with lock:
                i = idx.get(node, 0)
                idx[node] = i + 1
            entries = nodes.get(node) or []
            if not entries:
                log.append(dict(node=node, alias=alias, served=None))
                raise RuntimeError(f"REPLAY_NO_RECORD:{node}")
            e = entries[min(i, len(entries) - 1)]
            w = walls[node]
            call_s = w[i] if len(w) == len(entries) and i < len(w) else float(e.get("latency") or 0.0)
            log.append(dict(node=node, alias=alias, max_tokens=max_tokens, served_model=e["model"],
                            repeated=i >= len(entries)))
            clock.sleep(call_s)
            if is_transport_error(e):
                raise RuntimeError("REPLAYED_TRANSPORT_ERROR")
            return {"text": e["text"], "in": e["in"], "out": e["out"],
                    "stop": inferred_stop(alias, e["out"], max_tokens), "lat": call_s}
        return fn

    class ReplayProvider(V2.RealProvider):
        def start_call(self, alias, model, system, user, max_tokens, timeout_s=120,
                       temperature=0, node="?", cancel_effective=False):
            self.calls.append({"node": node, "alias": alias, "model": model})
            return V2._RealHandle(fn_for(node), alias, model, system, user, max_tokens,
                                  timeout_s, temperature, self.clock, self.slots, node)

    return ReplayProvider(clock, slots, transport_fn=fn_for("?")), log


def outcome(d):
    per_node = collections.defaultdict(list)
    for c in (d.get("raw") or {}).get("calls", []):
        per_node[c["node"]].append(c["alias"])
    return dict(status=d.get("status"), tp=d.get("tp"), calls=d.get("calls"),
                final_states=d.get("final_states"),
                action_kinds=sorted((a.get("kind"), a.get("node")) for a in d.get("actions") or []),
                per_node_calls=dict(sorted(per_node.items())))


cfg_template = json.loads((HERE / "stage_d_v2_executor_config.json").read_text("utf-8"))
tmp = Path(tempfile.mkdtemp(prefix="replay192_"))
(tmp / "state").mkdir()
rows, t_start = [], time.time()
records = sorted(f for f in glob.glob(str(HERE / "runs_final" / "*__S*__r*.json"))
                 if os.environ.get("REPLAY_FILTER", "") in Path(f).name)
for f in records:
    orig = json.loads(Path(f).read_text("utf-8"))
    if "exec_id" not in orig:
        continue
    arm, sc, rep = orig["arm"], orig["scenario"], int(orig["rep"])
    cfg = json.loads(json.dumps(cfg_template))
    clock = V2.VirtualClock(SCALE)
    gb = V2.GlobalBudget(cfg["global"]["calls"], cfg["global"]["yuan"], cfg["global"].get("tokens"),
                         tmp / "state" / orig["exec_id"].replace("|", "__"))
    slots = V2.SlotManager(cfg["slots"], clock)
    store = V2.RunStore(tmp / "state", tmp / "out")
    prov, log = provider_for(clock, slots, orig)
    ex = V2.FinalExec(arm, sc, rep, cfg, clock, gb, slots, prov, store, dry_run=False)
    try:
        ret = ex.run()
        ret = ret if isinstance(ret, dict) else {}
        err = None
    except Exception as e:
        ret, err = {}, repr(e)[:200]
    o, r = outcome(orig), outcome(ret)
    mism = [k for k in o if o[k] != r[k]]
    n_err = sum(1 for es in orig["raw"]["nodes"].values() for e in es if is_transport_error(e))
    rows.append(dict(exec_id=orig["exec_id"], scenario=sc, arm=arm, match=not mism and not err,
                     stratum="has_transport_errors" if n_err else "fully_timed",
                     transport_errors_in_original=n_err,
                     mismatched_fields=mism, error=err,
                     original={k: o[k] for k in mism}, replay={k: r[k] for k in mism},
                     alias_model_mismatch=sum(1 for c in log if c.get("served_model") not in (None, c["alias"])),
                     repeated_serves=sum(1 for c in log if c.get("repeated"))))

by_sc = collections.defaultdict(lambda: [0, 0])
by_stratum = collections.defaultdict(lambda: [0, 0, 0])
field_counts = collections.Counter()
for row in rows:
    by_sc[row["scenario"]][0] += row["match"]
    by_sc[row["scenario"]][1] += 1
    s = by_stratum[row["stratum"]]
    s[0] += row["match"]
    s[1] += "tp" not in row["mismatched_fields"] and not row["error"]
    s[2] += 1
    field_counts.update(row["mismatched_fields"])
tp_match = sum(1 for row in rows if "tp" not in row["mismatched_fields"] and not row["error"])
summary = dict(
    generated=time.strftime("%Y-%m-%dT%H:%M:%S"), clock_scale=SCALE, n=len(rows),
    exact_match=sum(r["match"] for r in rows), tp_match=tp_match,
    by_stratum={k: dict(exact=v[0], tp=v[1], n=v[2]) for k, v in sorted(by_stratum.items())},
    by_scenario={k: f"{v[0]}/{v[1]}" for k, v in sorted(by_sc.items())},
    mismatched_field_counts=dict(field_counts),
    alias_model_mismatches=sum(r["alias_model_mismatch"] for r in rows),
    repeated_serves=sum(r["repeated_serves"] for r in rows),
    errors=[r["exec_id"] for r in rows if r["error"]],
    integrity=dict(network_attempts=NET["attempts"],
                   files_unchanged=SHA_BEFORE == {f: sha(HERE / f) for f in FILES},
                   sha256=SHA_BEFORE),
    wall_s=round(time.time() - t_start, 1))
(OUT / "REPLAY_192_RESULTS.json").write_text(
    json.dumps(dict(summary=summary, rows=rows), ensure_ascii=False, indent=1), "utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=1))
