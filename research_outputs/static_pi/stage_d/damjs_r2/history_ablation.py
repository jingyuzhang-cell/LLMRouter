#!/usr/bin/env python3
"""Zero-call History x deadline-gate ablation at the five real DAMJS decision points (2026-11-07).

Each logged decision point is re-decided by the real damjs_bridge.SchedulerBridge.policy and the
frozen damsj_engine.Scheduler, with executor counters (J1 rerun count, FMT repair count), spent
budget and History reconstructed from the smoke logs at that instant. Four configurations:
  FULL       History on,  deadline gate on   (must reproduce the logged choice)
  NO_HIST    History.forbidden() always False
  NO_DL      Scheduler.feasible() evaluated with an unbounded deadline (quality/budget gates kept;
             utility U still uses the real deadline)
  NO_BOTH    both off
No model, no network, no file outside this directory is touched.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))
import d2_executor as D2
import damjs_bridge as BR
import damsj_engine as ENG

P_IN, P_OUT = 0.8e-6, 2.8e-6
RUNS = HERE / "runs_real"


class _Clock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t


class _Prog:
    def __init__(self):
        self.recs = []

    def write(self, rec):
        self.recs.append(rec)


class _Ex:
    """Executor state needed by the bridge at one decision instant (values from the logs)."""

    def __init__(self, t, deadline_ex, spent_yuan, rerun, fmtrep):
        self.spec = D2.base_spec()
        self.cfg = {"per_exec": {"yuan": 0.18, "calls": 14}}
        self.clock = _Clock(t)
        self.t0 = 0.0
        self.local_yuan = spent_yuan
        self.decisions = []
        self._reruncount = dict(rerun)
        self._fmtrep = fmtrep
        self.deadline_s = deadline_ex


def decide(point, config):
    ex = _Ex(point["t"], point["deadline_ex"], point["spent_yuan"], point["rerun"], point["fmtrep"])
    h = BR.Harness(ex, ex.deadline_s, _Prog(), None, routing={})
    for (node, kind), gains in point["history"].items():
        for g in gains:
            h.sched.hist.record(node, kind, g)
    if config in ("NO_HIST", "NO_BOTH"):
        h.sched.hist.forbidden = lambda node, action: False
    if config in ("NO_DL", "NO_BOTH"):
        orig = h.sched.feasible

        def feasible(c, q, p, _orig=orig, _s=h.sched):
            d = _s.deadline
            _s.deadline = 1e12
            try:
                return _orig(c, q, p)
            finally:
                _s.deadline = d
        h.sched.feasible = feasible
    br = BR.SchedulerBridge(h, D2.REPAIR_LIB)
    acts = br.policy(point["node"], point["sig"])
    rec = br.trace[-1]
    return dict(chosen=rec.get("chosen"), actions=[list(a) for a in acts],
                generated=[c["kind"] for c in rec.get("candidates", [])],
                feasible=[c["kind"] for c in rec.get("candidates", []) if c["feasible"]],
                excluded=[(e["kind"], e["why"]) for e in rec.get("excluded", [])])


def spent_until(prog, t):
    starts = {x["id"]: x for x in prog if x["ev"] == "call_start"}
    return round(sum((e.get("tokens_in") or 0) * P_IN + (e.get("tokens_out") or 0) * P_OUT
                     for e in prog if e["ev"] == "call_end" and e.get("ok") and e["t"] <= t
                     and e["id"] in starts), 6)


def points():
    out = []
    for tag in ("240s_S3_r1_DAMJS", "240s_S4_r1_DAMJS"):
        prog = [json.loads(l) for l in (RUNS / "progress" / f"{tag}.jsonl").read_text("utf-8").splitlines() if l.strip()]
        d_ex = next(x for x in prog if x["ev"] == "exec_start")["deadline_ex"]
        hist, rerun, fmtrep = {}, {}, 0
        for x in prog:
            if x["ev"] == "damjs_observe":
                hist[(x["node"] if x["kind"] != "Z_format" else "FMT", x["kind"])] = list(x["hist"]["gains"])
            if x["ev"] == "damjs_decide":
                out.append(dict(tag=tag, t=x["t"], node=x["node"], sig=x["sig"], deadline_ex=d_ex,
                                spent_yuan=spent_until(prog, x["t"]), history={k: list(v) for k, v in hist.items()},
                                rerun=dict(rerun), fmtrep=fmtrep, logged_chosen=x["chosen"]))
                if x.get("action"):
                    kind, tgt = x["action"]
                    if kind == "format_repair":
                        fmtrep += 1
                        hist.setdefault(("FMT", "Z_format"), []).append(0.0)
                    else:
                        rerun[tgt] = rerun.get(tgt, 0) + 1
                        hist.setdefault((tgt, "Z_structure" if kind == "structure_repair" else "R"), []).append(0.0)
        # observe events overwrite the placeholder gain written at apply time
    return out


def main():
    pts = points()
    configs = ("FULL", "NO_HIST", "NO_DL", "NO_BOTH")
    rows = []
    for p in pts:
        res = {c: decide(p, c) for c in configs}
        rows.append(dict(tag=p["tag"], t=p["t"], node=p["node"], d_rem=round(p["deadline_ex"] - p["t"], 2),
                         history={f"{k[0]}|{k[1]}": v for k, v in p["history"].items()},
                         rerun=p["rerun"], fmtrep=p["fmtrep"], logged_chosen=p["logged_chosen"],
                         full_reproduces_log=res["FULL"]["chosen"] == p["logged_chosen"], results=res))
    (HERE / "runs_real" / "HISTORY_ABLATION.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
    for r in rows:
        line = " | ".join(f"{c}={r['results'][c]['chosen']}" for c in configs)
        print(f"{r['tag'][5:]:<12} t={r['t']:>7} {r['node']:<4} d_rem={r['d_rem']:>7} logged={r['logged_chosen']:<12} "
              f"repro={r['full_reproduces_log']} || {line}")
        for c in configs:
            x = r["results"][c]
            print(f"      {c:<8} generated={x['generated']} feasible={x['feasible']} excluded={x['excluded']}")
    return 0 if all(r["full_reproduces_log"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
