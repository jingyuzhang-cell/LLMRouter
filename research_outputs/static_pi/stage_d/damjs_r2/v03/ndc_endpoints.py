#!/usr/bin/env python3
"""Endpoint analysis of the real DAMJS_ND_CONTROLLED batch (three calibers + mechanism + costs).

Sources: results/*.json (final batch state), quarantine/*.attempt_* (rep-1 first execution, r1a),
progress/*.jsonl (events), NDC_LEDGER.jsonl (real/injected/fixture accounting).
"""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import d2_executor as D2
import damjs_r2_runner as R
import v03_runner as VR
import nd_controlled as NDC

SA = D2.SA_EX
DOCMAP = dict(SA.DOCMAP)
RUNS = HERE / "runs_real_ndc"


def norm(parsed):
    for a in parsed.get("answers", []):
        if a.get("doc") in DOCMAP:
            a["doc"] = DOCMAP[a["doc"]]
    return parsed


def calibers(fmt_text):
    parsed = D2.extract_json(fmt_text or "")
    if not parsed:
        return dict(lenient=0, strict_raw=0, strict_norm=0, n_answers=0)
    out = {}
    from terminal_quality import evaluate_terminal_quality
    for key, p in (("raw", parsed), ("norm", norm(copy.deepcopy(parsed)))):
        q = evaluate_terminal_quality(SA.CONTRACT, SA.build_terminal_output(json.loads(json.dumps(p))), D2.SRC())
        cr = q["claim_results"]
        out[key] = (sum(c["status"].startswith("CORRECT") for c in cr), sum(c["status"] == "CORRECT_GOLD" for c in cr))
    return dict(lenient=out["raw"][0], strict_raw=out["raw"][1], strict_norm=out["norm"][1],
                n_answers=len(parsed.get("answers") or []))


def fmt_output(prog):
    fmts = [x for x in prog if x.get("ev") == "node_end" and x["node"] == "FMT" and x.get("ok")]
    return fmts[-1].get("output") if fmts else None


def j1_committed(prog):
    ends = [x for x in prog if x.get("ev") == "node_end" and x["node"] == "J1" and x.get("ok")]
    return ends[-1].get("output") or "" if ends else ""


def analyze(tag, prog_path, fixture_text=None, late=None):
    prog = [json.loads(l) for l in Path(prog_path).read_text().splitlines() if l.strip()]
    v1 = None
    for x in prog:
        if x.get("ev") == "node_end" and x["node"] == "J1" and x.get("ok") and x.get("output"):
            v1 = x["output"]
    inj = [x for x in prog if x.get("ev") == "call_outcome" and x.get("outcome") == "injected"]
    rb = [x for x in prog if x.get("ev") == "node_rollback"]
    j1 = j1_committed(prog)
    j2in_valid = None
    st = [x for x in prog if x.get("ev") == "call_start" and x["node"] == "J2"]
    if st:
        j2in_valid = bool(v1) and j1 == v1 if rb else not j1  # placeholder, replaced below
    trunc = [x for x in prog if x.get("ev") == "call_outcome" and x.get("outcome") == "truncated"]
    mk = None
    ch = (late or {})
    return dict(tag=tag, tp_lenient_recording=None, calibers=calibers(fmt_output(prog)),
                rollback=[r["node"] for r in rb], injected=len(inj), truncated=[t["node"] for t in trunc],
                j1_len=len(j1), j1_eq_fixture=(j1 == fixture_text) if fixture_text is not None else None,
                status=ch.get("status"), tp=ch.get("tp"), makespan=ch.get("makespan_s"),
                estimator=ch.get("bridge", {}).get("estimator"), walls=ch.get("per_node_calls"))


def fixture_text(path):
    for line in Path(path).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("ev") == "fixture_call" and r["node"] == "J1":
                return r["text"]
    return None


def main():
    out = dict(generated="2026-11-07", reps={})
    # r1a: first execution (quarantine archives); fixture from archived gen progress
    fx1a = fixture_text(RUNS / "quarantine" / "NDC_r1_GEN.jsonl.attempt_20261107T223022")
    r1a = {}
    for arm in ("R2", "ND-only"):
        p = RUNS / "quarantine" / f"NDC_r1_{arm}.jsonl.attempt_20261107T223114" if arm == "R2" else \
            RUNS / "quarantine" / f"NDC_r1_{arm}.jsonl.attempt_20261107T223414"
        stamp = "20261107T223114" if arm == "R2" else "20261107T223414"
        late = json.load(open(RUNS / "quarantine" / f"NDC_r1_{arm}.child.json.attempt_{stamp}"))
        r1a[arm] = analyze(f"r1a_{arm}", p, fx1a, late)
    out["reps"]["r1a"] = dict(note="first execution of rep 1 (runner lacked a resume-skip; archived)", arms=r1a,
                              fixture_j1_wall=None)
    # r1b, r2: final results
    for rep, fxfile in (("r1b", "NDC_r1_GEN"), ("r2", "NDC_r2_GEN")):
        fx = fixture_text(RUNS / "progress" / f"{fxfile}.jsonl")
        arms = {}
        for arm in ("R2", "ND-only"):
            rp = RUNS / "results" / f"{fxfile.replace('GEN', arm)}.json"
            late = json.load(open(rp)) if rp.exists() else {}
            arms[arm] = analyze(f"{rep}_{arm}", RUNS / "progress" / f"{fxfile.replace('GEN', arm)}.jsonl", fx, late)
        out["reps"][rep] = dict(arms=arms)
    # gen fixture walls
    for rep, fxfile in (("r1a", None), ("r1b", "NDC_r1_GEN"), ("r2", "NDC_r2_GEN")):
        if fxfile:
            ev = [json.loads(l) for l in (RUNS / "progress" / f"{fxfile}.jsonl").read_text().splitlines() if l.strip()]
            out["reps"][rep]["fixture_j1_wall"] = next(
                (x["wall"] for x in ev if x.get("ev") == "fixture_call" and x["node"] == "J1"), None)
    ev = [json.loads(l) for l in (RUNS / "quarantine" / "NDC_r1_GEN.jsonl.attempt_20261107T223022").read_text().splitlines()]
    out["reps"]["r1a"]["fixture_j1_wall"] = next(
        (x["wall"] for x in ev if x.get("ev") == "fixture_call" and x["node"] == "J1"), None)
    out["ledger"] = [json.loads(l) for l in (RUNS / "NDC_LEDGER.jsonl").read_text().splitlines()]
    out["final_ledger"] = R.read_ledger(RUNS)
    out["caps"] = NDC.CAPS
    (HERE / "NDC_ENDPOINTS.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    for rep, d in out["reps"].items():
        print(f"== {rep} (fixture J1 wall {d['fixture_j1_wall']}s)")
        for arm, a in d["arms"].items():
            c = a["calibers"]
            print(f"  {arm:<8} status={a['status']} tp={a['tp']} | L/S/S-norm={c['lenient']}/{c['strict_raw']}/{c['strict_norm']} "
                  f"rollback={a['rollback']} j1_eq_fixture={a['j1_eq_fixture']} truncated={a['truncated']} mk={a['makespan']}")
        if "R2" in d["arms"] and "ND-only" in d["arms"]:
            for k in ("lenient", "strict_norm"):
                print(f"  paired d{k}: {d['arms']['ND-only']['calibers'][k] - d['arms']['R2']['calibers'][k]:+d}")
    print("ledger rows:", [(r["tag"], r["real"]["calls"], r["injected"]["calls"], r["fixture_replays_deducted"]["calls"])
                            for r in out["ledger"]])
    print("final:", out["final_ledger"])


if __name__ == "__main__":
    main()
