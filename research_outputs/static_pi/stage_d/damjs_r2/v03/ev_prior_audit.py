#!/usr/bin/env python3
"""Zero-call audit of the frozen V0.3 EV-gate statistics (operator request 2026-11-07).

Checks, from archived records only:
  S1 slow prior: Beta(33,67) vs its stated source (2026-11-06 smoke, J1-GLM caps 3/9)
  S2 normal prior: source count (caps 14/264) vs the estimator's frozen failure-event definition
     (transport error/timeout OR cap OR unparseable); nature of the extra events
  S3 clustering sensitivity of the baseline rate (by execution; by 8 time windows)
  S4 mu and L by caliber (lenient / strict), success-conditional, from the 192-run S3 records
  S5 doc-label driver of strict TP (SINK citation doc = document id vs node name)
  S6 decision matrix: EV-gate accept/reject across parameterizations x regimes
Writes EV_PRIOR_AUDIT.json next to this file. Frozen files are read, never written.
"""
import collections
import glob
import json
import os
import sys
from pathlib import Path

from scipy.stats import beta as B, chi2

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
sys.path.insert(0, str(STAGE_D))
import d2_executor as D2

RUNS = STAGE_D / "runs_final"
SMOKE = STAGE_D / "damjs_r2" / "runs_real"


def ci(a, b):
    return [round(float(B.ppf(.025, a, b)), 4), round(float(B.ppf(.975, a, b)), 4)]


def j1_rows():
    rows = []
    for f in sorted(glob.glob(str(RUNS / "*__S*__r*.json"))):
        d = json.load(open(f))
        j1 = [e for e in d["raw"]["nodes"].get("J1", []) if e["model"] == "glm53flash"]
        for i, e in enumerate(j1):
            terr = e.get("latency") is None and not e.get("text") and not e.get("out")
            cap = (e["out"] or 0) >= 8192
            unp = (not terr) and not isinstance(D2.extract_json(e.get("text") or ""), dict)
            rows.append(dict(exec=d["exec_id"], sc=d["scenario"], idx=i, cap=cap, terr=terr, unparse=unp,
                             fail=cap or terr or unp, mtime=os.path.getmtime(f), lat=e.get("latency")))
    return rows


def deff(rows, key, ev):
    cl = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        c = cl[key(r)]
        c[0] += r[ev]
        c[1] += 1
    N = sum(n for _, n in cl.values())
    K = sum(c for c, _ in cl.values())
    m, p = len(cl), K / N
    var_cl = m / (m - 1) * sum((c - p * n) ** 2 for c, n in cl.values()) / N ** 2
    d = var_cl / (p * (1 - p) / N)
    x2 = sum((c - p * n) ** 2 / (p * n * (1 - p)) for c, n in cl.values())
    return dict(p=round(p, 4), k=K, n=N, clusters=m, deff=round(d, 3), n_eff=round(N / d, 1),
                chi2=round(x2, 2), df=m - 1, p_value=round(float(1 - chi2.cdf(x2, m - 1)), 4))


def s3_tps():
    def tp(d):
        cr = d["score"]["claim_results"]
        return sum(c["status"].startswith("CORRECT") for c in cr), sum(c["status"] == "CORRECT_GOLD" for c in cr)
    out = []
    for r in range(1, 9):
        s = json.load(open(RUNS / f"Static__S3__r{r}.json"))
        p = json.load(open(RUNS / f"Proposed-Dynamic__S3__r{r}.json"))
        rep = [e for e in p["raw"]["nodes"]["J1"] if e["model"] == "glm53flash"][1:]
        ok = any("dates_relay" in (D2.extract_json(e["text"] or "") or {}) for e in rep)
        out.append(dict(rep=r, static=tp(s), proposed=tp(p), repair_ok=ok, repair_calls=len(rep)))
    return out


def sink_docs(d):
    sink = (d["raw"]["nodes"].get("SINK") or [{}])[-1].get("text", "")
    return sorted({a.get("doc") for a in (D2.extract_json(sink) or {}).get("answers", []) if a.get("doc")})


def post_mean(prior, fails, calls):
    a, b = prior
    return (a + fails) / (a + b + calls)


def main():
    rows = j1_rows()
    n = len(rows)
    cnt = {k: sum(r[k] for r in rows) for k in ("cap", "terr", "unparse", "fail")}
    terr_dec = []
    for f in sorted(glob.glob(str(RUNS / "*__S*__r*.json"))):
        d = json.load(open(f))
        j1 = [e for e in d["raw"]["nodes"].get("J1", []) if e["model"] == "glm53flash"]
        if j1 and j1[0].get("latency") is None and not j1[0].get("text") and not j1[0].get("out"):
            dec = [300 - x["t_rem"] for x in d["decisions"] if x["node"] == "J1"]
            if dec:
                terr_dec.append(dec[0])
    cap_lat = sorted(r["lat"] for r in rows if r["cap"] and r["lat"] is not None)
    order = sorted({(r["mtime"], r["exec"]) for r in rows})
    rank = {e: i for i, (_, e) in enumerate(order)}

    audit = dict(generated="2026-11-07", note="zero-call; archived records only")
    audit["S1_slow_prior"] = dict(
        frozen=dict(prior=[33, 67], pseudo_count=100, mean=0.33, ci95=ci(33, 67)),
        source=dict(caps=3, calls=9, smoke_failures_under_frozen_definition=4,
                    smoke_definition_note="4/9 = 3 caps + 1 L2 deadline-truncation timeout (CP S4 repair, timeout 67.6 s)",
                    clopper_pearson_3_of_9=[round(float(B.ppf(.025, 3, 7)), 4), round(float(B.ppf(.975, 4, 6)), 4)]),
        verdict=("Beta(33,67) carries 100 pseudo-observations for a 9-call source: an x11.1 amplification, "
                 "not a discount. The stated '降权' derivation is incorrect."),
        power_prior_family={f"a0={w}": dict(prior=[0.5 + 3 * w, 0.5 + 6 * w], mean=round((0.5 + 3 * w) / (1 + 9 * w), 4),
                                            ci95=ci(0.5 + 3 * w, 0.5 + 6 * w), n_eff=1 + 9 * w)
                            for w in (0.0, 0.25, 0.5, 1.0)})
    audit["S2_normal_prior_source"] = dict(
        j1_glm_calls=n, executions=len({r["exec"] for r in rows}), counts=cnt,
        cap_only_rate=round(cnt["cap"] / n, 4), frozen_definition_rate=round(cnt["fail"] / n, 4),
        transport_errors=dict(n=cnt["terr"], first_call_j1_decision_times_s=sorted(round(t, 1) for t in terr_dec),
                              interpretation=("J1 starts ~6-11 s after launch and its decision lands at ~126 s: these are the "
                                              "baseline executor's 120 s socket timeouts, i.e. right-censored call durations "
                                              "(the pilot's J1 timeout is W_eff ~190-219 s, so the event is not transferable)")),
        capped_call_latency_s=cap_lat,
        verdict=("The normal prior counts caps only (14/264 = 5.3%) while the estimator counts timeout|cap|unparseable; "
                 "under the estimator's own definition the baseline rate is 37/264 = 14.0%. 23 of the 37 events are 120 s "
                 "censored timeouts specific to the baseline environment."))
    audit["S3_clustering"] = dict(
        cap=dict(by_execution=deff(rows, lambda r: r["exec"], "cap"),
                 by_8_time_windows=deff(rows, lambda r: rank[r["exec"]] * 8 // len(order), "cap")),
        fail=dict(by_execution=deff(rows, lambda r: r["exec"], "fail"),
                  by_8_time_windows=deff(rows, lambda r: rank[r["exec"]] * 8 // len(order), "fail")),
        verdict="design effect 1.07-1.19 (n_eff ~220-246 of 264); no significant time heterogeneity; clustering is not the issue")
    s3 = s3_tps()
    ok = [x for x in s3 if x["repair_ok"]]
    bad = [x for x in s3 if x["repair_calls"] and not x["repair_ok"]]
    sl = sum(x["static"][0] for x in s3) / 8
    ss = sum(x["static"][1] for x in s3) / 8
    audit["S4_mu_L_by_caliber"] = dict(
        per_rep=s3,
        frozen=dict(mu=1.29, mu_source="GAIN_TABLE (lenient TP; derivation script not in repository)", L=11,
                    L_source="2026-11-06 smoke strict: Static S3 11 - DAMJS S3 0", threshold=round(1.29 / 12.29, 4)),
        lenient=dict(mu_success=round(sum(x["proposed"][0] for x in ok) / len(ok) - sl, 3), n_success=len(ok),
                     L_baseline=round(sl - sum(x["proposed"][0] for x in bad) / len(bad), 3), n_fail=len(bad),
                     L_smoke=[6, 10]),
        strict=dict(mu_success=round(sum(x["proposed"][1] for x in ok) / len(ok) - ss, 3),
                    L_baseline=round(ss - sum(x["proposed"][1] for x in bad) / len(bad), 3),
                    static_S3_strict_baseline=[x["static"][1] for x in s3], L_smoke=11),
        verdict=("The frozen threshold mixes calibers (lenient mu with a strict L) and takes L against an atypical Static "
                 "run: baseline Static S3 strict TP is 0 in 8/8 runs, the smoke's Static S3 scored 11."))
    docs = {}
    for sc in ("S3", "S4"):
        for arm in ("Static", "Proposed-Dynamic"):
            docs[f"{sc}|{arm}"] = [dict(rep=r, docs=sink_docs(json.load(open(RUNS / f"{arm}__{sc}__r{r}.json"))),
                                        strict=sum(c["status"] == "CORRECT_GOLD" for c in json.load(
                                            open(RUNS / f"{arm}__{sc}__r{r}.json"))["score"]["claim_results"]))
                                   for r in range(1, 9)]
    for tag, f in (("smoke Static S3", "Static__S3__r1__D240.json"), ("smoke DAMJS S3", "DAMJS__S3__r1__D240.json"),
                   ("smoke Static S4", "Static__S4__r1__D240.json"), ("smoke DAMJS S4", "DAMJS__S4__r1__D240.json")):
        d = json.load(open(SMOKE / "exec_records" / f))
        docs[tag] = [dict(docs=sink_docs(d), strict=sum(c["status"] == "CORRECT_GOLD" for c in (d.get("score") or {}).get("claim_results") or []))]
    audit["S5_strict_driver"] = dict(
        sink_citation_docs=docs,
        verdict=("Strict TP is gated by whether SINK cites document ids (D1-D4) or node names (E1-E4). In S3 the repaired J1's "
                 "relay carries document ids (successful repairs: strict 13-14); without relay Static S3 cites node names "
                 "(strict 0 in 8/8). In S4 the label is stochastic in both arms. Consequences: the smoke 'strict -11' and the "
                 "N2 replay 'strict 0->11' both rest on the smoke Static S3 run's atypical D1 labels; the typical strict "
                 "expectation for the rollback (v1, no relay) world is ~0, and ND's robust benefit is lenient (~+5-6)."))
    priors_normal = {"cap_only": (14.5, 250.5), "frozen_definition": (37.5, 227.5)}
    priors_slow = {"frozen_33_67": (33.0, 67.0), "power_a0_0.5": (2.0, 3.5), "jeffreys_a0_0": (0.5, 0.5)}
    params = {"frozen(mu=1.29,L=11)": (1.29, 11.0),
              "lenient(mu=1.89,L=4.25)": (1.89, 4.25), "lenient(mu=1.89,L=10)": (1.89, 10.0),
              "strict(mu=13.57,L=0)": (13.57, 0.0), "strict(mu=13.57,L=11)": (13.57, 11.0)}
    regimes = {"normal: first J1 clean (repair decision)": ("normal", 0, 1),
               "latched: first J1 capped": ("slow", 1, 1),
               "latched: first J1 valid but >154 s": ("slow", 0, 1),
               "latched: after a failed repair": ("slow", 1, 2)}
    matrix = []
    for pname, (mu, L) in params.items():
        thr = mu / (mu + L) if (mu + L) else 1.0
        for nname, npri in priors_normal.items():
            for sname, spri in priors_slow.items():
                row = dict(params=pname, threshold=round(thr, 4), normal_prior=nname, slow_prior=sname)
                for rname, (reg, k, c) in regimes.items():
                    p = post_mean(npri if reg == "normal" else spri, k, c)
                    ev = (1 - p) * mu - p * L
                    row[rname] = dict(p=round(p, 4), EV=round(ev, 3), decision="ACCEPT" if ev > 0 else "REJECT")
                matrix.append(row)
    audit["S6_decision_matrix"] = matrix
    (HERE / "EV_PRIOR_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=1, default=float), "utf-8")
    print("S1", audit["S1_slow_prior"]["verdict"])
    print("S2", cnt, "rates:", audit["S2_normal_prior_source"]["cap_only_rate"], audit["S2_normal_prior_source"]["frozen_definition_rate"])
    print("S3", {k: (v["by_execution"]["deff"], v["by_8_time_windows"]["deff"], v["by_8_time_windows"]["p_value"]) for k, v in audit["S3_clustering"].items() if isinstance(v, dict)})
    print("S4", {k: v for k, v in audit["S4_mu_L_by_caliber"].items() if k in ("frozen", "lenient", "strict")})
    print("S6 (decisions: normal | latched-cap | latched-wall | after-failed-repair)")
    for r in matrix:
        print(f"  {r['params']:<26} thr={r['threshold']:<6} N={r['normal_prior']:<17} S={r['slow_prior']:<14} " +
              " | ".join(v["decision"][0] + f"({v['p']:.3f})" for k, v in r.items() if isinstance(v, dict)))


if __name__ == "__main__":
    main()
