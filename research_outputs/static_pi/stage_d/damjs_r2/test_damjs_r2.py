#!/usr/bin/env python3
"""Zero-call acceptance suite for DAMJS_EXP_36 (operator ruling 2026-11-06, step 2).

T0 existing engine (29) and wrapper (17) suites      T5 cross-process budget ledger and batch stop
T1 A‴ baseline replay through the real child path    T6 L2 / L3 / L4 on the real wrapper
T2 three-arm label mapping                           T7 manifest and per-execution identity
T3 real damjs_engine.Scheduler invocation            T8 zero-call proof and real-mode gates
T4 History repeated-action constraint

Every child runs in replay mode: recorded responses through the executor's real handle, behind a
network tripwire, with credentials stripped. Nothing in this suite can reach a model API.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, str(HERE))
for _k in ("STAGE_D_GLM_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(_k, None)
import damjs_bridge as BR
import damjs_r2_runner as R
import damsj_engine as ENG

OUT = HERE / "ACCEPTANCE_RESULTS.json"
RES = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "tests": [], "runs": []}
SCALE = 10.0


def check(tid, name, ok, **ev):
    RES["tests"].append(dict(id=tid, name=name, ok=bool(ok), evidence=ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {tid} {name}", flush=True)


def tmp(prefix):
    return Path(tempfile.mkdtemp(prefix=f"r2acc_{prefix}_"))


def base(arm, sc, r):
    return STAGE_D / "runs_final" / f"{arm}__{sc}__r{r}.json"


def synth(src, edit, dest):
    d = json.loads(Path(src).read_text("utf-8"))
    edit(d)
    dest.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
    return dest


def run(runs, tag, arm, sc, rep, deadline, src, scale=SCALE, caps=None, manifest=R.MANIFEST):
    rec = R.run_one(tag=tag, arm=arm, scenario=sc, rep=rep, deadline=deadline, mode="replay",
                    runs_dir=runs, caps=caps or R.CAPS, manifest=manifest, replay_src=src, clock_scale=scale)
    res = json.loads((Path(runs) / "results" / f"{tag}.json").read_text("utf-8"))
    prog = R.read_progress(Path(runs) / "progress" / f"{tag}.jsonl")
    RES["runs"].append(dict(tag=tag, runs_dir=str(runs), status=rec["status"], tp=rec["tp"],
                            watchdog=rec["watchdog"], net=rec["network_attempts"], identity_ok=rec["identity_ok"]))
    return rec, res, prog


def outcome_orig(d):
    per = {}
    for c in d["raw"]["calls"]:
        per.setdefault(c["node"], []).append(c["alias"])
    return dict(tp=d["tp"], status=d["status"], calls=d["calls"], final_states=d["final_states"],
                actions=sorted((a["kind"], a["node"]) for a in d["actions"]), per_node=per)


def outcome_r2(r):
    return dict(tp=r.get("tp"), status=r.get("status"), calls=r.get("calls"), final_states=r.get("final_states"),
                actions=sorted((a["kind"], a["node"]) for a in r.get("actions") or []),
                per_node={n: v for n, v in (r.get("per_node_calls") or {}).items() if v})


def w_node(node):
    return max(3 * BR.P95_WALL[node], ENG.W_MIN)


def classify_orig(d):
    errs = sum(1 for es in d["raw"]["nodes"].values() for e in es
               if e.get("latency") is None and not e.get("text") and not e.get("out"))
    long_calls = [x["node"] for x in d.get("exec_log") or [] if x.get("node") in BR.P95_WALL
                  and (x.get("wall") or 0) > w_node(x["node"])]
    if errs:
        return "has_transport_errors"
    if long_calls:
        return "call_exceeds_L2_W_node"
    if d["makespan_s"] >= 300.0 - R.RESERVE_S - 5.0:
        return "makespan_near_L3"
    return "fully_timed"


def t0():
    for script, expect in (("test_damsj_engine.py", "29 passed, 0 failed"), ("test_damsj_executor.py", "17 passed, 0 failed")):
        p = subprocess.run([sys.executable, str(STAGE_D / script)], capture_output=True, text=True, timeout=600,
                           cwd=str(STAGE_D))
        tail = (p.stdout or "").strip().splitlines()[-1:] or [""]
        check("T0", f"{script} -> {expect}", expect in (p.stdout or ""), tail=tail[0], rc=p.returncode)


def t1():
    runs = tmp("t1")
    rows, strata = [], {}
    for sc in ("S3", "S4"):
        for arm, label in (("Static", "Static"), ("Proposed-Dynamic", "Current-Proposed")):
            for r in range(1, 9):
                src = base(arm, sc, r)
                orig = json.loads(src.read_text("utf-8"))
                rec, res, prog = run(runs, f"t1_{label}_{sc}_r{r}", label, sc, r, 300.0, src)
                o, n = outcome_orig(orig), outcome_r2(res)
                mism = [k for k in o if o[k] != n[k]]
                stratum = classify_orig(orig)
                fmt_out = R.partial_outputs(prog).get("FMT")
                scorer_ok = (res.get("status") != "COMPLETE") or (R.score_text(fmt_out) == res.get("tp"))
                rows.append(dict(tag=f"{label}|{sc}|r{r}", stratum=stratum, match=not mism, mismatched=mism,
                                 orig={k: o[k] for k in mism}, r2={k: n[k] for k in mism},
                                 policy=res.get("policy_source"), identity_ok=(res.get("identity") or {}).get("ok"),
                                 degraded_scorer_matches_finish=scorer_ok,
                                 cp_structure_repair=("structure_repair", "J1") in [tuple(a) for a in n["actions"]]))
                strata.setdefault(stratum, [0, 0])
                strata[stratum][0] += (not mism)
                strata[stratum][1] += 1
    ft = [x for x in rows if x["stratum"] == "fully_timed"]
    check("T1", "A‴ baseline replay: every fully-timed record reproduced field-by-field",
          ft and all(x["match"] for x in ft),
          strata={k: f"{v[0]}/{v[1]}" for k, v in strata.items()},
          mismatches=[{k: x[k] for k in ("tag", "stratum", "mismatched", "orig", "r2")} for x in rows if not x["match"]])
    check("T1", "degraded-output scorer reproduces finish() TP on every COMPLETE replay",
          all(x["degraded_scorer_matches_finish"] for x in rows))
    RES["t1_rows"] = rows
    return rows


def t2(t1_rows):
    m = {k: BR.resolve_arm(k) for k in R.ARMS}
    exp = {"Static": ("Static", "native:Static"),
           "Current-Proposed": ("Proposed-Dynamic", "native:Proposed-Dynamic"),
           "DAMJS": ("Proposed-Dynamic", "damjs_engine.Scheduler")}
    bad = []
    for lab in ("Current-Proposd", "proposed", "", "Proposed-Dynamic"):
        try:
            BR.resolve_arm(lab)
            bad.append(lab)
        except ValueError:
            pass
    check("T2", "arm map exact; unknown or raw executor labels rejected", m == exp and not bad, mapping=m, accepted_bad=bad)
    runs = tmp("t2")
    for sub in ("progress", "results", "exec_records", "state"):
        (runs / sub).mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("STAGE_D_GLM_KEY", "DEEPSEEK_API_KEY")}
    env.update(APILOT_ARM="Current-Proposd", APILOT_SCEN="S3", APILOT_REP="1", APILOT_DEADLINE="300",
               APILOT_MODE="replay", APILOT_LAUNCH_WALL=repr(time.time()), APILOT_STATE=str(runs / "state"),
               APILOT_EXEC_DIR=str(runs / "exec_records"), APILOT_CAPS=json.dumps(R.CAPS),
               APILOT_OUT=str(runs / "results" / "bad.json"), APILOT_PROGRESS=str(runs / "progress" / "bad.jsonl"),
               APILOT_CANCEL=str(runs / "progress" / "bad.cancel"), APILOT_BATCH=R.BATCH,
               APILOT_MANIFEST=str(R.MANIFEST), APILOT_REPLAY_SRC=str(base("Static", "S3", 1)), APILOT_CLOCK_SCALE="10")
    p = subprocess.run([sys.executable, str(R.CHILD)], env=env, capture_output=True, text=True, timeout=120)
    calls = [r for r in R.read_progress(runs / "progress" / "bad.jsonl") if r.get("ev") == "call_start"]
    check("T2", "child refuses an unknown arm label before any call", p.returncode == 3 and
          "UNKNOWN_ARM_LABEL" in p.stderr and not calls and not (runs / "results" / "bad.json").exists(),
          rc=p.returncode, stderr=p.stderr.strip()[-120:])
    cp = [x for x in t1_rows if x["tag"].startswith("Current-Proposed|S3")]
    st = [x for x in t1_rows if x["tag"].startswith("Static|")]
    check("T2", "Current-Proposed runs the native Proposed-Dynamic policy (repairs J1 in S3), Static never acts",
          all(x["policy"] == "native:Proposed-Dynamic" for x in cp) and sum(x["cp_structure_repair"] for x in cp) >= 6
          and all(x["policy"] == "native:Static" for x in st),
          cp_runs_with_J1_repair=f"{sum(x['cp_structure_repair'] for x in cp)}/{len(cp)}")


def t3():
    runs = tmp("t3")
    eng_sha = R.sha_file(STAGE_D / "damsj_engine.py")
    mf = json.loads(R.MANIFEST.read_text("utf-8"))
    eng_mf = next(c["sha256"] for c in mf["components"] if c["role"] == "engine")
    problems, n_dec, n_act, gate_rows, aborted_runs = [], 0, 0, [], []
    for D in (130.0, 150.0, 240.0):
        for sc in ("S3", "S4"):
            for r in (1, 2):
                tag = f"t3_DAMJS_{int(D)}_{sc}_r{r}"
                rec, res, prog = run(runs, tag, "DAMJS", sc, r, D, base("Proposed-Dynamic", sc, r))
                br = res.get("bridge") or {}
                decs = [x for x in prog if x.get("ev") == "damjs_decide"]
                chosen = [tuple(x["action"]) for x in decs if x.get("chosen") not in (None, "NONE")]
                start = next((x for x in prog if x.get("ev") == "exec_start"), {})
                n_dec += len(decs)
                if start.get("policy") != "damjs_engine.Scheduler" or start.get("identity_pre_ok") is not True:
                    problems.append((tag, "exec_start_policy_or_identity_pre"))
                if rec["aborted"]:
                    aborted_runs.append(dict(tag=tag, decisions=[(x["node"], x["chosen"], x.get("reason")) for x in decs],
                                             completed=res.get("completed_nodes"), quarantined=res.get("late_result_quarantined")))
                else:
                    acts = [(a["kind"], a["node"]) for a in res.get("actions") or []]
                    n_act += len(acts)
                    if res.get("policy_source") != "damjs_engine.Scheduler":
                        problems.append((tag, "policy_source"))
                    if Path(br.get("engine_module", "")).resolve() != (STAGE_D / "damsj_engine.py").resolve():
                        problems.append((tag, "engine_module"))
                    if acts != chosen or br.get("counts", {}).get("apply") != len(acts):
                        problems.append((tag, "actions_not_from_scheduler", acts, chosen))
                    if (res.get("identity") or {}).get("ok") is not True:
                        problems.append((tag, "identity"))
                for x in decs:
                    if x.get("engine") != "damjs_engine.Scheduler":
                        problems.append((tag, "engine_tag"))
                    for c in x.get("candidates", []):
                        if c["kind"] not in BR.ALLOWED_KINDS:
                            problems.append((tag, "F3_violation", c["kind"]))
                        if c["kind"] == "Z_structure" and (c["lat"] != 116.9 or c["affected"] != ["J1", "J2", "SINK", "FMT"]):
                            problems.append((tag, "Z_structure_lat", c["lat"], c["affected"]))
                        if c["kind"] == "Z_format" and (c["lat"] != 0.0 or c["affected"] != ["FMT"]):
                            problems.append((tag, "Z_format_lat", c["lat"]))
                        if c["kind"] in ("Z_structure", "Z_format"):
                            follows = (c["lat_gate"] <= c["d_rem"]) == c["feasible"]
                            picked = x["chosen"] == c["kind"]
                            gate_rows.append(dict(tag=tag, kind=c["kind"], d_rem=c["d_rem"], gate=c["lat_gate"],
                                                  feasible=c["feasible"], chosen=x["chosen"]))
                            if not follows or picked != c["feasible"]:
                                problems.append((tag, "gate_inconsistent", c["kind"], c["d_rem"], c["lat_gate"], x["chosen"]))
                    if any(e["why"] == "F3_scope_excluded" for e in x.get("excluded", [])):
                        problems.append((tag, "X_or_PI_generated"))
    check("T3", "every DAMJS decision comes from damjs_engine.Scheduler and every action maps 1:1 to a decision",
          not problems and n_dec > 0, decisions=n_dec, actions_in_completed_runs=n_act, problems=problems[:10],
          aborted_runs=aborted_runs, engine_sha=eng_sha[:16], engine_sha_manifest=eng_mf[:16])
    check("T3", "deadline gate: Z_* chosen iff L_hat+sigma_l+T_reserve <= D_rem (both branches observed)",
          not [p for p in problems if p[1] == "gate_inconsistent"]
          and any(g["feasible"] for g in gate_rows) and any(not g["feasible"] for g in gate_rows),
          gate_decisions=gate_rows)


def t4():
    runs = tmp("t4")

    def persist(d):
        j1 = d["raw"]["nodes"]["J1"]
        j1[1] = dict(j1[1], text=j1[0]["text"])
    src = synth(base("Proposed-Dynamic", "S3", 1), persist, runs / "persistent_J1_fault.json")
    _, dj, dprog = run(runs, "t4_DAMJS", "DAMJS", "S3", 1, 300.0, src)
    _, cp, _ = run(runs, "t4_CP", "Current-Proposed", "S3", 1, 300.0, src)
    obs = [x for x in dprog if x.get("ev") == "damjs_observe"]
    later = [x for x in dprog if x.get("ev") == "damjs_decide" and x["node"] == "J1"][1:]
    dj_rep = [a for a in dj.get("actions") or [] if a["kind"] == "structure_repair"]
    cp_rep = [a for a in cp.get("actions") or [] if a["kind"] == "structure_repair"]
    ok = (len(dj_rep) == 1 and len(obs) == 1 and obs[0]["gain"] == 0.0 and obs[0]["forbidden_now"]
          and later and all(c["kind"] != "Z_structure" for x in later for c in x["candidates"])
          and all(x["chosen"] == "NONE" for x in later)
          and len(dj["per_node_calls"]["J1"]) == 2 and len(cp_rep) >= 2 and len(cp["per_node_calls"]["J1"]) >= 3)
    check("T4", "persistent J1 fault: DAMJS repairs once, History forbids a repeat; Current-Proposed repeats",
          ok, damjs_repairs=len(dj_rep), damjs_J1_calls=len(dj["per_node_calls"]["J1"]), observe=obs,
          later_decisions=[dict(chosen=x["chosen"], kinds=[c["kind"] for c in x["candidates"]]) for x in later],
          cp_repairs=len(cp_rep), cp_J1_calls=len(cp["per_node_calls"]["J1"]))
    h = ENG.History()
    h.record("J1", "Z_structure", 0.0)
    c3a = h.forbidden("J1", "Z_structure")
    h2 = ENG.History()
    h2.record("J1", "Z_structure", 1.0)
    allowed_after_gain = not h2.forbidden("J1", "Z_structure")
    h2.record("J1", "Z_structure", 0.0)
    c3b = h2.forbidden("J1", "Z_structure")
    check("T4", "engine History semantics on observed gains: C3-a and C3-b", c3a and allowed_after_gain and c3b,
          c3a=c3a, allowed_after_positive=allowed_after_gain, c3b=c3b)


def t5():
    runs = tmp("t5")
    caps_saved, order_saved, phase_saved = R.CAPS, R.build_order, R.PHASE_CAPS
    plan = [dict(phase="smoke", block="300s|S3|r1", arm=a, scenario="S3", rep=1, deadline=300.0, tag=f"t5_{a}")
            for a in ("Static", "Current-Proposed", "DAMJS")]
    try:
        R.PHASE_CAPS = {"smoke": dict(calls=9, tokens=1_250_000, yuan=2.30)}
        R.build_order = lambda seed=None: plan
        argv_saved = sys.argv
        sys.argv = ["damjs_r2_runner.py", "--mode", "replay", "--phase", "smoke", "--runs-dir", str(runs),
                    "--clock-scale", str(SCALE)]
        rc = R.main()
        summ = json.loads((runs / "BATCH_SUMMARY_smoke.json").read_text("utf-8"))
        led = [json.loads(l) for l in (runs / "LEDGER.jsonl").read_text().splitlines()]
        check("T5", "phase cap (batch cap 350) reaches the children: shared ledger, denial -> INCOMPLETE_BUDGET -> stop",
              rc == 1 and summ["executed"] == 2 and summ["status"] == "INCOMPLETE" and summ["ledger"]["calls"] == 9
              and led[0]["ledger_after"]["calls"] == 7 and led[1]["status"] == "INCOMPLETE_BUDGET"
              and not (runs / "results" / "t5_DAMJS.json").exists(),
              stop=summ["stop"], ledger_after=[x["ledger_after"] for x in led], statuses=[x["status"] for x in led])
        rc2 = R.main()
        summ2 = json.loads((runs / "BATCH_SUMMARY_smoke.json").read_text("utf-8"))
        check("T5", "exhausted ledger refuses to launch the next execution", rc2 == 1 and summ2["executed"] == 0
              and "before launching" in (summ2["stop"] or ""), stop=summ2["stop"])
        for name, caps in (("yuan", dict(calls=350, tokens=1_250_000, yuan=0.005)),
                           ("tokens", dict(calls=350, tokens=3_000, yuan=2.30))):
            r2 = tmp(f"t5{name}")
            rec, res, _ = run(r2, f"t5_{name}", "Static", "S3", 1, 300.0, base("Static", "S3", 1), caps=caps)
            led2 = R.read_ledger(r2)
            check("T5", f"{name} cap denies the first reservation and stops", rec["status"] == "INCOMPLETE_BUDGET"
                  and R.stop_reason(rec, caps) is not None and led2["tokens"] == 0 and led2["yuan"] == 0.0,
                  ledger=led2, stop=R.stop_reason(rec, caps), invalid_reason=res.get("invalid_reason"))
    finally:
        R.CAPS, R.build_order, R.PHASE_CAPS = caps_saved, order_saved, phase_saved
        sys.argv = argv_saved
    check("T5", "phase caps: smoke = 50 calls / 190,000 tokens / Y0.37 inside batch caps; main = batch caps",
          R.caps_for("smoke") == dict(calls=50, tokens=190_000, yuan=0.37) and R.caps_for("main") == R.CAPS
          and R.CAPS == dict(calls=350, tokens=1_250_000, yuan=2.30),
          smoke=R.caps_for("smoke"), main=R.caps_for("main"))


def t6():
    runs = tmp("t6")

    def slow_e1(d):
        d["raw"]["nodes"]["E1"][0]["wall_override"] = 200.0
    src = synth(base("Static", "S3", 1), slow_e1, runs / "slow_E1.json")
    rec, res, prog = run(runs, "t6_L2_wnode", "Static", "S3", 1, 300.0, src)
    st = [x for x in prog if x.get("ev") == "call_start" and x["node"] == "E1"]
    en = [x for x in prog if x.get("ev") == "call_end" and x["node"] == "E1"]
    e1_end = next((x for x in prog if x.get("ev") == "node_end" and x["node"] == "E1"), {})
    j1_start = next((x for x in prog if x.get("ev") == "call_start" and x["node"] == "J1"), {})
    check("T6", "L2 W_node: a stuck E1 call is cut at max(3*p95,120)=120 s; A‴ semantics: transport error -> empty "
          "output + D2 signal, DAG continues",
          len(st) == 1 and abs(st[0]["timeout_s"] - 120.0) < 1e-6 and len(en) == 1 and not en[0]["ok"]
          and en[0]["err"].startswith("TimeoutError") and 119.0 <= en[0]["t"] - st[0]["t"] <= 121.5
          and e1_end.get("ok") and e1_end.get("output") == ""
          and {"D2": "structure"} in [a["sig"] for a in res["anomalies"] if a["node"] == "E1"]
          and j1_start and j1_start["t"] < 130.0 and rec["watchdog"] == "COMPLETE",
          e1_timeout=st[0]["timeout_s"] if st else None, e1_cut_after=round(en[0]["t"] - st[0]["t"], 2) if en else None,
          e1_err=en[0]["err"] if en else None, j1_start=j1_start.get("t"), makespan=res.get("makespan_s"))

    def slow_j1(d):
        d["raw"]["nodes"]["J1"][0]["wall_override"] = 400.0
    src = synth(base("Static", "S3", 1), slow_j1, runs / "slow_J1.json")
    rec, res, prog = run(runs, "t6_L2_deadline", "Static", "S3", 1, 300.0, src)
    st = [x for x in prog if x.get("ev") == "call_start" and x["node"] == "J1"]
    ex_start = next(x for x in prog if x.get("ev") == "exec_start")
    exp_w = ex_start["deadline_ex"] - R.RESERVE_S - st[0]["t"] if st else None
    refused = [x for x in prog if x.get("ev") == "call_refused" and x["node"] == "J1"]
    late_starts = [x for x in prog if x.get("ev") == "call_start" and x["t"] > ex_start["deadline_ex"] - R.RESERVE_S]
    check("T6", "L2 deadline term: J1 timeout = D_rem - T_reserve; no call starts after D-15; watchdog degrades (L4)",
          len(st) == 1 and abs(st[0]["timeout_s"] - exp_w) < 0.5 and not late_starts
          and rec["watchdog"] == "INCOMPLETE_DEADLINE_DEGRADED" and res["status"] == "INCOMPLETE_DEADLINE_DEGRADED"
          and {"E1", "E2", "E3", "E4"} <= set(res["completed_nodes"]) and "J1" not in res["completed_nodes"]
          and rec["reconcile"]["n_unsettled"] >= 1 and rec["reconcile"]["topup_tokens"] > 0
          and rec["ledger_after"]["tokens"] == rec["ledger_before"]["tokens"] + rec["reconcile"]["topup_tokens"],
          j1_timeout=st[0]["timeout_s"] if st else None, expected=round(exp_w, 2) if exp_w else None,
          refused=[x["reason"] for x in refused], completed=res.get("completed_nodes"), reconcile=rec["reconcile"],
          late_quarantined=res.get("late_result_quarantined"))

    def stuck_j1(d):
        d["raw"]["nodes"]["J1"][0].update(wall_override=60.0, ignore_timeout=True)
    src = synth(base("Static", "S3", 1), stuck_j1, runs / "stuck_J1.json")
    t_start = time.time()
    rec, res, prog = run(runs, "t6_L3_kill", "Static", "S3", 1, 40.0, src, scale=1.0)
    wall = time.time() - t_start
    orig = json.loads(base("Static", "S3", 1).read_text("utf-8"))
    outs = R.partial_outputs(prog)
    e_ok = all(outs.get(n) == orig["raw"]["nodes"][n][0]["text"] for n in ("E1", "E2", "E3", "E4"))
    check("T6", "L3 hard stop at D-15 on a stuck call (1:1 clock); L4 keeps the completed E outputs verbatim",
          rec["watchdog"] == "INCOMPLETE_DEADLINE_DEGRADED" and 24.0 <= rec["elapsed_s"] <= 31.0
          and e_ok and "J1" not in res["completed_nodes"] and res["tp"] == 0 and res["scored_from"] == "unknown_all"
          and rec["reconcile"]["n_unsettled"] == 1 and rec["reconcile"]["unsettled"][0]["node"] == "J1",
          elapsed=rec["elapsed_s"], wall=round(wall, 1), completed=res["completed_nodes"],
          reconcile=rec["reconcile"], degraded=dict(tp=res["tp"], src=res["scored_from"]))
    recs = [dict(ev="node_end", node="J1", ok=True, output="j1v1", ts=1.0),
            dict(ev="node_invalidate", nodes=["J1", "J2"], ts=2.0),
            dict(ev="node_end", node="J2", ok=True, output="j2v2", ts=3.0),
            dict(ev="node_end", node="SINK", ok=True, output="sink", ts=9.0)]
    po, po_cut = R.partial_outputs(recs), R.partial_outputs(recs, cutoff_ts=5.0)
    check("T6", "L4 partial outputs drop invalidated results and anything after the abort time",
          po == {"J2": "j2v2", "SINK": "sink"} and po_cut == {"J2": "j2v2"}, all=po, cutoff=po_cut)


def t7():
    v = R.verify_manifest()
    check("T7", "new MANIFEST: every registered component SHA matches disk", v["ok"], n=v["n"],
          manifest_sha256=v["manifest_sha256"], mismatches=v["mismatches"])
    ids = [r for r in RES["runs"] if r["identity_ok"] is not None]
    check("T7", "every completed replay execution verified its identity block pre and post",
          ids and all(r["identity_ok"] for r in ids), n=len(ids))
    runs = tmp("t7")
    mf = json.loads(R.MANIFEST.read_text("utf-8"))
    for c in mf["components"]:
        if c["role"] == "bridge":
            c["sha256"] = "0" * 64
    bad = runs / "tampered_manifest.json"
    bad.write_text(json.dumps(mf, ensure_ascii=False), "utf-8")
    rec, res, _ = run(runs, "t7_tamper", "Static", "S3", 1, 300.0, base("Static", "S3", 1), manifest=bad)
    mism = [m["role"] for m in res["identity"]["pre"]["mismatches"]]
    check("T7", "tampered manifest -> execution identity fails -> runner stop reason INTEGRITY_FAIL",
          res["identity"]["ok"] is False and mism == ["bridge"] and (R.stop_reason(rec, R.CAPS) or "").startswith("INTEGRITY_FAIL"),
          mismatches=mism, stop=R.stop_reason(rec, R.CAPS))
    saved = R.MANIFEST
    try:
        R.MANIFEST = bad
        refused = False
        try:
            R.verify_manifest.__defaults__ = (bad,)
            sys.argv = ["damjs_r2_runner.py", "--mode", "replay", "--phase", "smoke", "--runs-dir", str(runs / "b")]
            R.main()
        except SystemExit as e:
            refused = "INTEGRITY_FAIL" in str(e)
        check("T7", "runner refuses to start a batch whose manifest does not match disk", refused)
    finally:
        R.MANIFEST = saved
        R.verify_manifest.__defaults__ = (saved,)


def t8():
    nets = sum(r["net"] for r in RES["runs"])
    check("T8", "zero network attempts across every replay execution", nets == 0, executions=len(RES["runs"]))
    captured = {}

    def fake_run_isolated(**kw):
        captured.update(kw["env"])
        return dict(status="CHILD_FAILED_rc9", elapsed=0.0)
    saved = R.run_isolated
    os.environ["STAGE_D_GLM_KEY"] = os.environ["DEEPSEEK_API_KEY"] = "dummy-not-a-key"
    try:
        R.run_isolated = fake_run_isolated
        R.run_one(tag="t8_env", arm="Static", scenario="S3", rep=1, deadline=300.0, mode="replay",
                  runs_dir=tmp("t8"), caps=R.CAPS, replay_src=base("Static", "S3", 1), clock_scale=SCALE)
    finally:
        R.run_isolated = saved
        os.environ.pop("STAGE_D_GLM_KEY", None)
        os.environ.pop("DEEPSEEK_API_KEY", None)
    check("T8", "replay children never receive credential variables",
          "STAGE_D_GLM_KEY" not in captured and "DEEPSEEK_API_KEY" not in captured and captured.get("APILOT_MODE") == "replay")
    gates = []

    def _no_real(*a, **k):
        raise RuntimeError("SAFETY_NET: real path reached during gate test")
    saved_lc, saved_ro = R.load_credentials, R.run_one
    R.load_credentials, R.run_one = _no_real, _no_real
    for argv, env in ((["--mode", "real", "--phase", "smoke"], {}),
                      (["--mode", "real", "--phase", "smoke"], {"STAGE_D_REAL_CALLS_AUTHORIZED": "1"}),
                      (["--mode", "real", "--phase", "main"], {"STAGE_D_REAL_CALLS_AUTHORIZED": "1", "DAMJS_R2_GO": "smoke"}),
                      (["--mode", "real", "--phase", "all"], {"STAGE_D_REAL_CALLS_AUTHORIZED": "1", "DAMJS_R2_GO": "all"})):
        saved_env = {k: os.environ.get(k) for k in ("STAGE_D_REAL_CALLS_AUTHORIZED", "DAMJS_R2_GO")}
        os.environ.update(env)
        sys.argv = ["damjs_r2_runner.py"] + argv + ["--runs-dir", str(tmp("t8g"))]
        try:
            R.main()
            gates.append((argv, "NOT_REFUSED"))
        except SystemExit as e:
            gates.append((argv, "REFUSED" if "REFUSED" in str(e) else str(e)[:60]))
        finally:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    R.load_credentials, R.run_one = saved_lc, saved_ro
    check("T8", "real mode refused without STAGE_D_REAL_CALLS_AUTHORIZED=1 and a matching per-phase DAMJS_R2_GO",
          all(g[1] == "REFUSED" for g in gates), gates=[f"{' '.join(a)} -> {s}" for a, s in gates])


def main():
    t_all = time.time()
    t0()
    rows = t1()
    t2(rows)
    t3()
    t4()
    t5()
    t6()
    t7()
    t8()
    n_ok = sum(t["ok"] for t in RES["tests"])
    RES["summary"] = dict(passed=n_ok, failed=len(RES["tests"]) - n_ok, executions=len(RES["runs"]),
                          wall_s=round(time.time() - t_all, 1), manifest_sha256=R.sha_file(R.MANIFEST))
    OUT.write_text(json.dumps(RES, ensure_ascii=False, indent=1), "utf-8")
    print(f"\nRESULT: {n_ok} passed, {len(RES['tests']) - n_ok} failed "
          f"({len(RES['runs'])} replay executions, {RES['summary']['wall_s']} s)")
    return 0 if n_ok == len(RES["tests"]) else 1


if __name__ == "__main__":
    sys.exit(main())
