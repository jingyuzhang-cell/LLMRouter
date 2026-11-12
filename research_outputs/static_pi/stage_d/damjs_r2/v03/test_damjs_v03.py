#!/usr/bin/env python3
"""Zero-call validation of DAMJS V0.3 against DAMJS_V0_3.md (frozen a173154d…).

All fixtures are merges of archived REAL responses (192-run baseline + 2026-11-06 smoke). The
replay provider is content-conditioned: per-node variant lists are selected by a substring of the
live user prompt, so a downstream node receives the recorded response that matches the upstream
content it actually received (v1-world vs empty-J1-world). Network is tripwired; credentials are
stripped; nothing outside damjs_r2/v03/ is written.

  N1  H-ND-1a: repair succeeds -> v2 commits, no rollback, TP equals the baseline record
  N2  H-ND-1b: repair caps, v1 valid -> rollback; downstream runs in the v1 world; TP recovers
               vs the same replay with nd=off (R2 behaviour)
  N3  H-ND-3:  usable-for-usable commits (S4 FMT keeps the Z_format gain)
  N4  H-EV:    slow-service latch -> EV<=0 excludes Z_structure (ev on) / chosen (ev off);
               Z_format never gated
  N5  N2 + consistency: rollback event, History gain=0 + forbidden, invalidations, COMPLETE
  N6  regression: nd=ev=off reproduces the smoke decision sequence
  N7  estimator units: priors, latch, posterior; L/EV arithmetic at the preregistered thresholds
"""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

NET = {"n": 0}


def _trip(*a, **k):
    NET["n"] += 1
    raise RuntimeError("NETWORK_TRIPWIRE")


urllib.request.urlopen = _trip
socket.create_connection = _trip
http.client.HTTPConnection.connect = _trip
http.client.HTTPSConnection.connect = _trip
for _k in ("STAGE_D_GLM_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(_k, None)

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, str(STAGE_D / "damjs_r2"))
sys.path.insert(0, str(HERE))
import d2_executor as D2
import stage_d_v2_executor as V2
import damsj_engine as ENG
import damjs_v03 as V03

RUNS = STAGE_D / "runs_final"
SMOKE = STAGE_D / "damjs_r2" / "runs_real" / "exec_records"
SCALE = 10.0
RESULTS = {"tests": [], "runs": [], "prereg_sha256": __import__("hashlib").sha256(
    (STAGE_D / "DAMJS_V0_3.md").read_bytes()).hexdigest()}


def check(tid, name, ok, **ev):
    RESULTS["tests"].append(dict(id=tid, name=name, ok=bool(ok), evidence=ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {tid} {name}", flush=True)


def rec(base, arm, sc, r):
    return json.loads((RUNS / f"{arm}__{sc}__r{r}.json").read_text("utf-8"))


def smoke(label, sc):
    return json.loads((SMOKE / f"{label}__{sc}__r1__D240.json").read_text("utf-8"))


def node_rec(d, n):
    return [{"model": e.get("model", "deepseek"), "text": e["text"], "in": e["in"], "out": e["out"],
             "latency": e.get("latency")} for e in d["raw"]["nodes"].get(n, [])]


def entry(text, in_, out, when=None, wall=None, cap=False):
    return dict(text=text, **{"in": in_}, out=out, when=when, wall=wall, cap=cap)


class Provider(V2.RealProvider):
    """Content-conditioned replay: variants whose `when` substring appears in the live user prompt
    are served in listed order; entries without `when` are the default tail."""

    def __init__(self, clock, slots, spec):
        super().__init__(clock, slots, transport_fn=lambda *a: {})
        self.spec, self.harness, self.used, self.served, self.lock = spec, None, {}, [], threading.Lock()

    def _variant_fn(self, node):
        def fn(alias, system, user, max_tokens, timeout_s, temperature):
            variants = self.spec.get(node) or []
            with self.lock:
                used = self.used.setdefault(node, set())
                cands = [i for i, v in enumerate(variants) if v.get("when") is None or v["when"] in (user or "")]
                if not cands:
                    raise RuntimeError(f"REPLAY_NO_VARIANT:{node}")
                pick = next((i for i in cands if i not in used), cands[-1])
                used.add(pick)
                self.served.append((node, pick, variants[pick].get("when")))
            e = variants[pick]
            w = float(e.get("wall") if e.get("wall") is not None else 5.0)
            if timeout_s is not None and w > timeout_s:
                self.clock.sleep(timeout_s)
                raise TimeoutError(f"replay wall {w}s > socket timeout {timeout_s:.1f}s")
            self.clock.sleep(w)
            if e.get("cap"):
                return {"text": e["text"], "in": e["in"], "out": e["out"], "stop": "max_tokens", "lat": w}
            return {"text": e["text"], "in": e["in"], "out": e["out"], "stop": "end_turn", "lat": w}
        return fn

    def start_call(self, alias, model, system, user, max_tokens, timeout_s=120,
                   temperature=0, node="?", cancel_effective=False):
        self.calls.append({"node": node, "alias": alias, "model": model})
        fn = self.harness.wrap_transport(node, self._variant_fn(node))
        return V2._RealHandle(fn, alias, model, system, user, max_tokens, timeout_s,
                              temperature, self.clock, self.slots, node)


def run(tag, spec, *, deadline=300.0, sc="S3", rep=1, nd=True, ev=True):
    cfg = V2.load_config(STAGE_D / "stage_d_v2_executor_config.json")
    cfg["deadline_s"]["default"] = cfg["deadline_s"][sc] = deadline
    tmp = Path(tempfile.mkdtemp(prefix="v03_"))
    (tmp / "state").mkdir()
    clock = V2.VirtualClock(SCALE)
    gb = V2.GlobalBudget(100, 5.0, 10_000_000, tmp / "state")
    slots = V2.SlotManager(cfg["slots"], clock)
    store = V2.RunStore(tmp / "state", tmp / "out")
    prov = Provider(clock, slots, spec)
    ex = V2.FinalExec("DAMJS", sc, rep, cfg, clock, gb, slots, prov, store, dry_run=True)
    prog_path = tmp / "progress.jsonl"
    open(prog_path, "w").close()
    h, br = V03.install(ex, ex.deadline_s, BR_Progress(prog_path), "", routing=V2.AROUT,
                        repair_lib=D2.REPAIR_LIB, nd=nd, ev=ev)
    prov.harness = h
    ret = ex.run()
    prog = [json.loads(l) for l in prog_path.read_text().splitlines() if l.strip()]
    strict = sum(1 for c in (ret.get("score") or {}).get("claim_results") or [] if c["status"] == "CORRECT_GOLD")
    RESULTS["runs"].append(dict(tag=tag, nd=nd, ev=ev, deadline=deadline, scenario=sc, status=ret.get("status"),
                                tp_lenient=ret.get("tp"), tp_strict=strict, served=list(prov.served),
                                rollbacks=list(h.rollbacks), estimator=h.estimator.state()))
    return dict(rec=ret, strict=strict, prog=prog, bridge=br, harness=h, served=list(prov.served))


class BR_Progress:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, r):
        with self.lock, open(self.path, "a") as f:
            f.write(json.dumps(dict(r, schema=1, ts=time.time()), ensure_ascii=False) + "\n")


def decs(prog):
    return [(x["node"], x["chosen"], x.get("reason"), x.get("estimator", {}).get("glm53flash", {}))
            for x in prog if x.get("ev") == "damjs_decide"]


def fixture_s3_repair_success():
    base = rec("", "Proposed-Dynamic", "S3", 1)
    sm = smoke("DAMJS", "S3")
    E = {n: node_rec(base, n) for n in ("E1", "E2", "E3", "E4", "J1", "J2", "SINK")}
    spec = {n: [entry(e["text"], e["in"], e["out"], wall=3.0) for e in E[n]] for n in ("E1", "E2", "E3", "E4")}
    spec["J1"] = [entry(E["J1"][0]["text"], E["J1"][0]["in"], E["J1"][0]["out"], wall=50.0),
                  entry(E["J1"][1]["text"], E["J1"][1]["in"], E["J1"][1]["out"], wall=60.0)]
    spec["J2"] = [entry(E["J2"][0]["text"], E["J2"][0]["in"], E["J2"][0]["out"], wall=8.0)]
    spec["SINK"] = [entry(E["SINK"][0]["text"], E["SINK"][0]["in"], E["SINK"][0]["out"], wall=8.0)]
    return spec, base


def fixture_s3_repair_caps():
    sm = smoke("DAMJS", "S3")                       # empty-J1 world responses
    st = smoke("Static", "S3")                      # valid-no-relay-J1 world responses
    E = {n: node_rec(sm, n) for n in ("E1", "E2", "E3", "E4")}
    j1 = node_rec(sm, "J1")
    spec = {n: [entry(e["text"], e["in"], e["out"], wall=3.0) for e in E[n]] for n in E}
    spec["J1"] = [entry(j1[0]["text"], 1524, 1510, wall=28.0),
                  entry("", 1690, 8192, wall=120.0, cap=True)]
    for n in ("J2", "SINK"):
        good = node_rec(st, n)[0]
        bad = node_rec(sm, n)[0]
        spec[n] = [entry(good["text"], good["in"], good["out"], when="person_identity", wall=8.0),
                   entry(bad["text"], bad["in"], bad["out"], wall=8.0)]
    return spec, sm, st


def fixture_s4_fmt():
    sm = smoke("DAMJS", "S4")
    E = {n: node_rec(sm, n) for n in ("E1", "E2", "E3", "E4", "J1", "J2", "SINK")}
    spec = {n: [entry(e["text"], e["in"], e["out"], wall=3.0) for e in E[n]] for n in E}
    spec["J1"] = [entry(E["J1"][0]["text"], E["J1"][0]["in"], E["J1"][0]["out"], wall=76.0)]
    spec["J2"] = [entry(E["J2"][0]["text"], E["J2"][0]["in"], E["J2"][0]["out"], wall=8.0)]
    spec["SINK"] = [entry(E["SINK"][0]["text"], E["SINK"][0]["in"], E["SINK"][0]["out"], wall=8.0)]
    return spec, sm


def fixture_s3_slow():
    sm = smoke("DAMJS", "S3")
    st = smoke("Static", "S3")
    E = {n: node_rec(sm, n) for n in ("E1", "E2", "E3", "E4")}
    spec = {n: [entry(e["text"], e["in"], e["out"], wall=3.0) for e in E[n]] for n in E}
    spec["J1"] = [entry("", 1701, 8192, wall=155.0, cap=True)]
    for n in ("J2", "SINK"):
        good = node_rec(st, n)[0]
        spec[n] = [entry(good["text"], good["in"], good["out"], wall=8.0)]
    return spec


def n1():
    spec, base = fixture_s3_repair_success()
    r = run("N1_repair_success", spec)
    rb = [x for x in r["prog"] if x["ev"] == "node_rollback"]
    check("N1", "repair success commits v2 (no rollback), TP equals the baseline record",
          not rb and r["rec"]["tp"] == base["tp"] and V03._valid(r["rec"]["raw"]["nodes"]["J1"][-1]["text"])
          and "dates_relay" in (D2.extract_json(r["rec"]["raw"]["nodes"]["J1"][-1]["text"]) or {}),
          tp=r["rec"]["tp"], strict=r["strict"], baseline_tp=base["tp"], rollbacks=len(rb))


def n2():
    spec, sm, st = fixture_s3_repair_caps()
    on = run("N2_nd_on", spec)
    off = run("N2_nd_off", spec, nd=False, ev=False)
    rb = [x for x in on["prog"] if x["ev"] == "node_rollback"]
    j1_final_on = [x for x in on["prog"] if x["ev"] == "node_end" and x["node"] == "J1"][-1].get("output") or ""
    raw_v2_audit = on["rec"]["raw"]["nodes"]["J1"][-1]["text"]
    check("N2", "capped repair with valid v1: rollback restores v1 bytes; downstream runs in the v1 world; "
                "TP recovers vs nd=off on the identical replay",
          rb and rb[0]["node"] == "J1" and j1_final_on == node_rec(sm, "J1")[0]["text"]
          and on["rec"]["tp"] - off["rec"]["tp"] >= 4 and on["rec"]["tp"] >= 12,
          tp_nd_on=on["rec"]["tp"], tp_nd_off=off["rec"]["tp"], strict_nd_on=on["strict"], strict_nd_off=off["strict"],
          served_on=[s for s in on["served"] if s[0] in ("J2", "SINK")],
          served_off=[s for s in off["served"] if s[0] in ("J2", "SINK")], rollback=rb[:1],
          committed_j1_len=len(j1_final_on), smoke_v1_len=len(node_rec(sm, "J1")[0]["text"]),
          raw_audit_keeps_v2_len=len(raw_v2_audit))


def n3():
    spec, sm = fixture_s4_fmt()
    r = run("N3_fmt_commit", spec, sc="S4")
    rb = [x for x in r["prog"] if x["ev"] == "node_rollback"]
    fmt_out = [x for x in r["prog"] if x["ev"] == "node_end" and x["node"] == "FMT"][-1]
    check("N3", "usable-for-usable commits: S4 Z_format keeps its gain, no rollback anywhere",
          not rb and r["rec"]["tp"] == sm["tp"] and fmt_out.get("ok") and r["strict"] == 14
          and any(x.get("ev") == "damjs_decide" and x.get("chosen") == "Z_format" for x in r["prog"]),
          tp=r["rec"]["tp"], strict=r["strict"], smoke_tp=sm["tp"], rollbacks=len(rb))


def n4():
    spec = fixture_s3_slow()
    on = run("N4_ev_on", spec, deadline=320.0)
    off = run("N4_ev_off", spec, deadline=320.0, ev=False)
    j1_on = [x for x in on["prog"] if x.get("ev") == "damjs_decide" and x["node"] == "J1"]
    j1_off = [x for x in off["prog"] if x.get("ev") == "damjs_decide" and x["node"] == "J1"]
    est = next(x for x in on["prog"] if x["ev"] == "call_outcome" and x["node"] == "J1")["estimator"]["glm53flash"]
    excl = [e for x in j1_on for e in x.get("excluded", []) if str(e.get("why", "")).startswith("EV_gate")]
    fmt_gated = [e for x in on["prog"] if x.get("ev") == "damjs_decide" for e in x.get("excluded", [])
                 if e.get("kind") == "Z_format" and str(e.get("why", "")).startswith("EV_gate")]
    rb = [x for x in on["prog"] + off["prog"] if x["ev"] == "node_rollback"]
    check("N4", "slow latch -> p≈46%: EV gate excludes Z_structure (ev on -> NONE) while ev off chooses it; "
                "Z_format never gated; v1 invalid -> no rollback (H-ND-2)",
          est["slow"] is True and est["p"] > 0.105 and excl and j1_on and j1_on[0]["chosen"] == "NONE"
          and j1_off and j1_off[0]["chosen"] == "Z_structure" and not fmt_gated and not rb,
          estimator=est, ev_exclusions=excl, j1_decision_on=j1_on[0]["chosen"] if j1_on else None,
          j1_decision_off=j1_off[0]["chosen"] if j1_off else None,
          d_rem_off=j1_off[0]["d_rem"] if j1_off else None, rollbacks=len(rb))


def n5():
    spec, sm, st = fixture_s3_repair_caps()
    r = run("N5_consistency", spec)
    prog = r["prog"]
    rb_t = next(x["t"] for x in prog if x["ev"] == "node_rollback")
    j2_start = next(x["t"] for x in prog if x["ev"] == "node_start" and x["node"] == "J2")
    obs = [x for x in prog if x["ev"] == "damjs_observe" and x["node"] == "J1"]
    hist = r["bridge"].summary()
    check("N5", "rollback consistency: observe gain=0 with repeat forbidden, downstream starts after rollback, "
                "invalidations present, run completes",
          obs and obs[0]["gain"] == 0.0 and obs[0]["forbidden_now"] and j2_start >= rb_t
          and any(x["ev"] == "node_invalidate" for x in prog) and r["rec"]["status"] == "COMPLETE"
          and hist["rollbacks"] and hist["estimator"]["glm53flash"]["slow"] is True,
          observe=obs[:1], j2_start=j2_start, rollback_t=rb_t, status=r["rec"]["status"])


def n6():
    spec, sm, st = fixture_s3_repair_caps()
    r = run("N6_r2_mode", spec, nd=False, ev=False)
    rb = [x for x in r["prog"] if x["ev"] == "node_rollback"]
    chosen = [c for _, c, _, _ in decs(r["prog"])]
    check("N6", "regression: nd=ev=off reproduces the smoke decision order and destructive overwrite",
          chosen[:2] == ["Z_structure", "NONE"] and not rb
          and r["rec"]["raw"]["nodes"]["J1"][-1]["text"] == "" and r["rec"]["tp"] < 12,
          chosen=chosen, tp=r["rec"]["tp"], final_j1_len=len(r["rec"]["raw"]["nodes"]["J1"][-1]["text"]))


def n7():
    est = V03.FailureEstimator()
    p0 = est.p("glm53flash")
    est.observe("glm53flash", True, 200.0)                       # model failure: counts, latches
    p_slow = est.p("glm53flash")
    p_at_latch = est.post("glm53flash")
    est.observe("glm53flash", "truncated", 200.0)                # censored: not counted, wall feeds latch
    p_after_trunc = est.p("glm53flash")
    post_trunc = est.post("glm53flash")
    est.observe("glm53flash", True, 60.0)                        # model failure after latch
    est.observe("glm53flash", False, 30.0)
    post = est.post("glm53flash")
    p_post = post["p"]
    ds = est.p("deepseek")
    a0, b0 = V03.PRIOR_NORMAL
    p_latch_expect = (V03.PRIOR_SLOW[0] + 1) / (sum(V03.PRIOR_SLOW) + 1)
    ok = (abs(p0 - a0 / (a0 + b0)) < 1e-9
          and abs(p_slow - p_latch_expect) < 1e-9
          and post_trunc["observed"] == dict(calls=1, fails=1) and post_trunc["truncated"] == 1
          and abs(p_after_trunc - p_latch_expect) < 1e-9        # truncation censored: p unchanged
          and post["observed"] == dict(calls=3, fails=2) and post["truncated"] == 1
          and abs(p_post - (V03.PRIOR_SLOW[0] + 2) / (sum(V03.PRIOR_SLOW) + 3)) < 1e-9
          and not est.slow.get("deepseek") and abs(ds - a0 / (a0 + b0)) < 1e-9
          and post["ci95"][0] < post["p"] < post["ci95"][1] and p_at_latch["ci95"][0] < 0.15)
    mu, L = V03.MU_EV["Z_structure"], V03.L_EV["Z_structure"]
    ev_slow = (1 - p_slow) * mu - p_slow * L
    ev_norm = (1 - p0) * mu - p0 * L
    thr = mu / (mu + L)
    # sensitivity: decision stable across the (mu, L) grid used in EV_PRIOR_AUDIT at both regimes
    grid_ok = all(((1 - p0) * m - p0 * l > 0) == (m / (m + l) > p0)
                  and ((1 - p_slow) * m - p_slow * l > 0) == (m / (m + l) > p_slow)
                  for m in (1.29, 1.89) for l in (4.25, 6.0, 10.0))
    check("N7", "V0.3.1 estimator: censoring-consistent priors, truncated events excluded from p but latched, "
                "single-caliber mu/L, EV sign consistent with the threshold across the (mu,L) grid",
          ok and ev_norm > 0 > ev_slow and grid_ok,
          p_normal=round(p0, 4), p_slow=round(p_slow, 4), p_after_trunc=round(p_after_trunc, 4),
          p_post=round(p_post, 4), latch_ci=p_at_latch["ci95"], post=post,
          priors=dict(normal=list(V03.PRIOR_NORMAL), slow=[round(x, 2) for x in V03.PRIOR_SLOW]),
          mu=mu, L=L, ev_normal=round(ev_norm, 3), ev_slow=round(ev_slow, 3), threshold=round(thr, 4),
          grid_stable=grid_ok)


def n8():
    """Node-level protection on a stub executor with real call/apply_action semantics: J1 is the
    direct repair target; J2 had completed on J1 v1 and is invalidated downstream."""
    import damjs_bridge as BR

    class _Ex:
        def __init__(self):
            self.spec = D2.base_spec()
            self.cfg = {"per_exec": {"yuan": 0.18, "calls": 14}}
            self.clock = V2.VirtualClock(1.0)
            self.t0 = self.clock.now()
            self.local_yuan = 0.0
            self.outputs = {"J1": '{"v": "J1 v1"}', "J2": '{"built_on": "J1 v1"}'}
            self.state = {n: "Ready" for n in self.spec}
            self.state.update(J1="Completed", J2="Completed")
            self.next_text = {}

        def call(self, node):
            self.outputs[node] = self.next_text.get(node, "")
            self.state[node] = "Completed"

        def apply_action(self, node, kind):
            self.state[node] = "Ready"
            for d in self.spec[node]["downs"]:
                if self.state.get(d) == "Completed":
                    self.state[d] = "Ready"

    tmpf = Path(tempfile.mkdtemp(prefix="v03_")) / "p.jsonl"
    h = V03.HarnessV03(_Ex(), 300.0, BR.Progress(str(tmpf)), "", routing={}, nd=True)
    h.install_progress()
    ex = h.ex
    ex.apply_action("J1", "structure_repair")
    recovered = sorted(h.recovered)
    ex.next_text = {"J1": "", "J2": ""}            # both re-executions return unusable output
    ex.call("J1")
    ex.call("J2")
    rb = [r["node"] for r in h.rollbacks]
    check("N8", "node-level protection: only the direct recovery target (J1) is armed and restored; the "
                "downstream node (J2) invalidated by the repair is not protected (stale-parent output not reused)",
          recovered == ["J1"] and ex.outputs["J1"] == '{"v": "J1 v1"}' and ex.outputs["J2"] == "" and rb == ["J1"]
          and not h.recovered and not h.armed,
          recovered_after_apply=recovered, rollbacks=rb, j1=ex.outputs["J1"], j2=ex.outputs["J2"])


def main():
    t0 = time.time()
    n1(); n2(); n3(); n4(); n5(); n6(); n7(); n8()
    ok = sum(t["ok"] for t in RESULTS["tests"])
    RESULTS["summary"] = dict(passed=ok, failed=len(RESULTS["tests"]) - ok, wall_s=round(time.time() - t0, 1),
                              network_attempts=NET["n"])
    (HERE / "V03_VALIDATION_RESULTS_v2.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), "utf-8")
    print(f"\nRESULT: {ok} passed, {len(RESULTS['tests']) - ok} failed; network={NET['n']}")
    return 0 if ok == len(RESULTS["tests"]) else 1


if __name__ == "__main__":
    sys.exit(main())
