#!/usr/bin/env python3
"""Official analysis of DAMJS_ND_CONFIRM (frozen pipeline; the ONLY statistical entry is
nd_confirm_stats.exact_two_sided; scoring caliber is frozen caliber v3)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import d2_executor as D2
import caliber_v3 as C3
from nd_confirm_stats import exact_two_sided, sign_test_two_sided, hodges_lehmann

RUNS = HERE / "runs_real_confirm"
PAIRS = [1, 2, 3, 4, 5, 6, 7]          # pair 8 incomplete (disclosed)


def arm_calibers(rep, arm):
    prog = [json.loads(l) for l in (RUNS / "progress" / f"NDC_r{rep}_{arm}.jsonl").read_text().splitlines() if l.strip()]
    sink = next((x["output"] for x in prog if x.get("ev") == "node_end" and x["node"] == "SINK" and x.get("ok")), "")
    three = C3.three(sink, "S3", True)
    v1 = None
    gen = [json.loads(l) for l in (RUNS / "progress" / f"NDC_r{rep}_GEN.jsonl").read_text().splitlines() if l.strip()]
    j1fx = [x for x in gen if x.get("ev") == "fixture_call" and x["node"] == "J1" and x.get("valid")]
    if j1fx:
        v1 = j1fx[-1]["text"]
    j1c = [x for x in prog if x.get("ev") == "node_end" and x["node"] == "J1" and x.get("ok")][-1].get("output") or ""
    rb = [x for x in prog if x.get("ev") == "node_rollback"]
    res = json.load(open(RUNS / "results" / f"NDC_r{rep}_{arm}.json"))
    return dict(calibers=three, j1_eq_v1=(j1c == (v1 or "")), rollback=len(rb),
                status=res.get("status"), makespan=res.get("makespan_s"),
                calls=res.get("calls"), yuan=res.get("accounting_yuan"),
                injected=len(res.get("injected_calls") or []))


def main():
    rows = {}
    D = []
    for rep in PAIRS:
        r2, nd = arm_calibers(rep, "R2"), arm_calibers(rep, "ND-only")
        d = nd["calibers"]["strict_norm_canon"] - r2["calibers"]["strict_norm_canon"]
        dl = nd["calibers"]["lenient"] - r2["calibers"]["lenient"]
        rows[rep] = dict(R2=r2, ND=nd, d_strict=d, d_lenient=dl)
        D.append(d)
    print("pair | R2 L/S/S3 | ND L/S/S3 | dS3 dL | ND rollback/eq_v1 | R2 eq_v1")
    for rep in PAIRS:
        r = rows[rep]
        c2, cn = r["R2"]["calibers"], r["ND"]["calibers"]
        print(f"  {rep}  | {c2['lenient']:>2}/{c2['strict_raw']:>2}/{c2['strict_norm_canon']:>2} | "
              f"{cn['lenient']:>2}/{cn['strict_raw']:>2}/{cn['strict_norm_canon']:>2} | "
              f"{r['d_strict']:>+3} {r['d_lenient']:>+3} | {r['ND']['rollback']} {r['ND']['j1_eq_v1']} | {r['R2']['j1_eq_v1']}")
    res = exact_two_sided(D)
    hl = hodges_lehmann(D)
    print("\nD (strict-norm-canon):", D)
    print("win/tie/loss:", res["win"], res["ties"], res["loss"], "| m =", res["m"])
    print("two-sided exact Wilcoxon p =", res["p"])
    print("sign test p =", round(sign_test_two_sided(D), 5))
    print("HL:", hl)
    mech_ok = all(rows[p]["ND"]["rollback"] == 1 and rows[p]["ND"]["j1_eq_v1"] and not rows[p]["R2"]["j1_eq_v1"] for p in PAIRS)
    print("mechanism 7/7 (ND rollback byte-exact, R2 destructive):", mech_ok)
    import damjs_r2_runner as R
    print("ledger:", R.read_ledger(RUNS))
    json.dump(dict(pairs={str(k): v for k, v in rows.items()}, D=D, wilcoxon=res, hl=hl,
                   sign_p=sign_test_two_sided(D), mechanism_ok=mech_ok),
              open(HERE / "ND_CONFIRM_ANALYSIS.json", "w"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
