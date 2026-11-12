#!/usr/bin/env python3
"""Caliber revision (zero-call, 2026-11-07): DOCMAP alias-normalized strict TP + EV threshold sensitivity.

N  strict-normalized TP: before the frozen scorer, map SINK citation doc labels through the frozen
   stage_a DOCMAP {E1:D1, E2:D2, E3:D3, E4:D4} (each E node's prompt reads exactly that document, so a
   label "E1" denotes document D1). Scorer, Gold and contract are unchanged.
T  EV threshold sensitivity: bootstrap of the success-conditional mu and the failure loss L on the
   normalized-strict and lenient calibers; decision stability at the four regime points under the
   V0.3.1 priors.
Writes CALIBER_REVISION.json. Reads archived records only.
"""
import copy
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import d2_executor as D2
import damjs_v03 as V03
from terminal_quality import evaluate_terminal_quality

SA = D2.SA_EX
DOCMAP = dict(SA.DOCMAP)
RUNS = STAGE_D / "runs_final"
SMOKE = STAGE_D / "damjs_r2" / "runs_real" / "exec_records"


def normalized(parsed):
    p = copy.deepcopy(parsed)
    for a in p.get("answers", []):
        if a.get("doc") in DOCMAP:
            a["doc"] = DOCMAP[a["doc"]]
    return p


def score(parsed):
    q = evaluate_terminal_quality(SA.CONTRACT, SA.build_terminal_output(json.loads(json.dumps(parsed))), D2.SRC())
    cr = q["claim_results"]
    return dict(lenient=sum(c["status"].startswith("CORRECT") for c in cr),
                strict=sum(c["status"] == "CORRECT_GOLD" for c in cr))


def terminal_from_sink(sink_text, scenario, fmt_repaired):
    parsed = D2.extract_json(sink_text or "")
    if not parsed:
        return None
    bypass = scenario == "S4" and not fmt_repaired
    return parsed if bypass else SA.apply_format_rules(copy.deepcopy(parsed))[0]


def three(d):
    sink = (d["raw"]["nodes"].get("SINK") or [{}])[-1].get("text", "")
    term = terminal_from_sink(sink, d["scenario"], any(a["kind"] == "format_repair" for a in d["actions"]))
    if term is None:
        return dict(lenient=0, strict_raw=0, strict_norm=0, docs=[])
    raw, norm = score(term), score(normalized(term))
    return dict(lenient=raw["lenient"], strict_raw=raw["strict"], strict_norm=norm["strict"],
                lenient_norm=norm["lenient"],
                docs=sorted({a.get("doc") for a in term.get("answers", []) if a.get("doc")}))


def main():
    out = dict(transform=dict(docmap=DOCMAP, source="stage_a/executor.py DOCMAP (frozen)",
                              rule="SINK answer doc label in DOCMAP keys -> mapped document id; nothing else changes"))
    out["smoke"] = {f.stem: three(json.load(open(f))) for f in sorted(SMOKE.glob("*.json"))}
    base = {}
    for sc in ("S3", "S4"):
        for arm in ("Static", "Proposed-Dynamic"):
            base[f"{sc}|{arm}"] = [three(json.load(open(RUNS / f"{arm}__{sc}__r{r}.json"))) for r in range(1, 9)]
    out["baseline"] = base
    # counterfactual worlds from the N2 replay (downstream = smoke Static S3 vs smoke DAMJS S3 responses)
    out["n2_replay_worlds"] = dict(rollback_world=out["smoke"]["Static__S3__r1__D240"],
                                   r2_world=out["smoke"]["DAMJS__S3__r1__D240"])
    st = json.load(open(SMOKE / "Static__S4__r1__D240.json"))
    sink = (st["raw"]["nodes"].get("SINK") or [{}])[-1].get("text", "")
    fmt = SA.apply_format_rules(copy.deepcopy(D2.extract_json(sink)))[0]
    out["s4_offline_format_counterfactual"] = dict(
        static_bypassed=out["smoke"]["Static__S4__r1__D240"],
        static_sink_plus_format_rules=dict(raw=score(fmt), normalized=score(normalized(fmt))),
        damjs=out["smoke"]["DAMJS__S4__r1__D240"])
    # mu / L on both calibers (baseline S3: Static 8 vs Proposed; success = repaired J1 carries the relay)
    stat, prop = base["S3|Static"], base["S3|Proposed-Dynamic"]
    ok_idx = []
    for r in range(1, 9):
        p = json.load(open(RUNS / f"Proposed-Dynamic__S3__r{r}.json"))
        rep = [e for e in p["raw"]["nodes"]["J1"] if e["model"] == "glm53flash"][1:]
        if any("dates_relay" in (D2.extract_json(e["text"] or "") or {}) for e in rep):
            ok_idx.append(r - 1)
    fail_idx = [i for i in range(8) if i not in ok_idx]
    sm = out["smoke"]
    cal = {}
    for c in ("lenient", "strict_norm"):
        s_mean = sum(x[c] for x in stat) / 8
        mu = sum(prop[i][c] for i in ok_idx) / len(ok_idx) - s_mean
        L_base = [s_mean - prop[i][c] for i in fail_idx]
        L_smoke = [sm["Static__S3__r1__D240"][c] - sm["DAMJS__S3__r1__D240"][c],
                   sm["Static__S3__r1__D240"][c] - sm["Current-Proposed__S3__r1__D240"][c]]
        cal[c] = dict(static_mean=round(s_mean, 3), mu_success=round(mu, 3), n_success=len(ok_idx),
                      L_baseline=[round(x, 3) for x in L_base], L_smoke=L_smoke,
                      threshold_at_max_L=round(mu / (mu + max(L_base + L_smoke)), 4))
    out["mu_L_by_caliber"] = cal
    # bootstrap sensitivity of the threshold and of the four regime decisions (V0.3.1 priors)
    rng = random.Random(20261107)
    pn = V03.PRIOR_NORMAL
    ps = V03.PRIOR_SLOW
    regimes = {"normal_first_clean": pn[0] / (sum(pn) + 1),
               "latched_cap": (ps[0] + 1) / (sum(ps) + 1),
               "latched_wall": ps[0] / (sum(ps) + 1),
               "after_failed_repair": (ps[0] + 1) / (sum(ps) + 2)}
    sens = {}
    for c in ("lenient", "strict_norm"):
        s_vals = [x[c] for x in stat]
        p_vals = [prop[i][c] for i in ok_idx]
        L_pool = cal[c]["L_baseline"] + cal[c]["L_smoke"]
        thr = []
        for _ in range(20000):
            sb = [rng.choice(s_vals) for _ in s_vals]
            pb = [rng.choice(p_vals) for _ in p_vals]
            mu = sum(pb) / len(pb) - sum(sb) / len(sb)
            L = rng.choice(L_pool)
            thr.append(mu / (mu + L) if mu > 0 and (mu + L) > 0 else 0.0)
        thr.sort()
        sens[c] = dict(threshold_p05=round(thr[1000], 4), threshold_p50=round(thr[10000], 4),
                       threshold_p95=round(thr[19000], 4),
                       decision_stability={k: dict(p_hat=round(v, 4),
                                                   share_accept=round(sum(t > v for t in thr) / len(thr), 4))
                                           for k, v in regimes.items()},
                       L_pool=L_pool)
    out["threshold_sensitivity"] = dict(frozen_point=dict(mu=V03.MU_EV["Z_structure"], L=V03.L_EV["Z_structure"],
                                                          threshold=round(1.89 / 11.89, 4)),
                                        bootstrap=sens, seed=20261107, draws=20000)
    (HERE / "CALIBER_REVISION.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print("smoke three-caliber:")
    for k, v in out["smoke"].items():
        print(f"  {k:<36} docs={str(v['docs']):<26} lenient={v['lenient']:>2} strict_raw={v['strict_raw']:>2} strict_norm={v['strict_norm']:>2}")
    for k, rows in base.items():
        print(f"  {k:<26} strict_raw={[x['strict_raw'] for x in rows]} strict_norm={[x['strict_norm'] for x in rows]}")
    print("N2 worlds normalized strict:", out["n2_replay_worlds"]["r2_world"]["strict_norm"], "->",
          out["n2_replay_worlds"]["rollback_world"]["strict_norm"])
    print("S4 offline counterfactual:", out["s4_offline_format_counterfactual"]["static_sink_plus_format_rules"])
    print("mu/L:", json.dumps(cal, ensure_ascii=False))
    print("sensitivity:", json.dumps(sens, ensure_ascii=False))


if __name__ == "__main__":
    main()
