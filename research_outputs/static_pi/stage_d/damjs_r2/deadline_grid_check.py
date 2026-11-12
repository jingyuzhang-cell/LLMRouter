"""Zero-call deadline screen for DAMJS_EXP_36 from the 32 A‴ baseline records (S3/S4 x Static/Proposed).

success(D) = TP >= 12 and finish <= D - 15 s (L3 terminates the child at D - 15; startup offset added).
Static and Current-Proposed outcomes are read off their own records (the native t_rem gates are
re-applied at the recorded fault time). DAMJS is a projection: the frozen gate decides repair vs NONE
at the recorded fault time, and the outcome is taken from the Proposed record (repair) or the Static
record of the same rep (NONE); a Proposed record with no fault signal is used as is (no decision
to re-gate). This is a feasibility screen, not a prediction.
"""
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "runs_final"
RESERVE, STARTUP = 15.0, 0.15
GATE = {"S3": 116.9 + 6.0 + RESERVE, "S4": 0.0 + 6.0 + RESERVE}   # L_hat + sigma_l + T_reserve
FAULT = {"S3": "J1", "S4": "FMT"}


def rec(arm, sc, r):
    return json.loads((RUNS / f"{arm}__{sc}__r{r}.json").read_text("utf-8"))


def fault_time(d, sc):
    ts = [a["t"] for a in d["anomalies"] if a["node"] == FAULT[sc]]
    return min(ts) if ts else None


def ok(d, D):
    return d["tp"] >= 12 and d["makespan_s"] + STARTUP <= D - RESERVE


def main():
    out = {"definition": __doc__.strip(), "deadlines": {}}
    for D in (110.0, 130.0, 150.0, 240.0):
        row = {}
        for sc in ("S3", "S4"):
            s_ok, p_ok, j_ok, p_act, j_act, ontime = [], [], [], [], [], {"Static": [], "Proposed": []}
            for r in range(1, 9):
                s, p = rec("Static", sc, r), rec("Proposed-Dynamic", sc, r)
                tf = fault_time(p, sc)
                t_rem = D - STARTUP - tf if tf is not None else None
                proposed_acts = t_rem is not None and t_rem >= 60
                damjs_acts = t_rem is not None and t_rem >= GATE[sc]
                s_ok.append(ok(s, D))
                no_fault = tf is None
                p_ok.append(ok(p, D) if (proposed_acts or no_fault) else ok(s, D))
                j_ok.append(ok(p, D) if (damjs_acts or no_fault) else ok(s, D))
                p_act.append(proposed_acts)
                j_act.append(damjs_acts)
                ontime["Static"].append(s["makespan_s"] + STARTUP <= D - RESERVE)
                ontime["Proposed"].append(p["makespan_s"] + STARTUP <= D - RESERVE)
            row[sc] = dict(
                n=8, usable_s=D - RESERVE,
                static_success=sum(s_ok), current_proposed_success=sum(p_ok), damjs_projected_success=sum(j_ok),
                current_proposed_repairs=sum(p_act), damjs_projected_repairs=sum(j_act),
                static_on_time=sum(ontime["Static"]), proposed_on_time=sum(ontime["Proposed"]))
        out["deadlines"][str(int(D))] = row
    for sc in ("S3", "S4"):
        for arm in ("Static", "Proposed-Dynamic"):
            ms = sorted(rec(arm, sc, r)["makespan_s"] for r in range(1, 9))
            tps = [rec(arm, sc, r)["tp"] for r in range(1, 9)]
            out.setdefault("baseline", {})[f"{sc}|{arm}"] = dict(
                makespan_median=st.median(ms), makespan_min=ms[0], makespan_max=ms[-1],
                tp=sorted(tps), fault_time=[fault_time(rec(arm, sc, r), sc) for r in range(1, 9)])
    (HERE / "DEADLINE_GRID_CHECK.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(out["deadlines"], ensure_ascii=False, indent=1))
    print(json.dumps(out["baseline"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
