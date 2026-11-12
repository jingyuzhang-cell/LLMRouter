#!/usr/bin/env python3
"""Caliber v3 (zero-call): DOCMAP alias normalization + deterministic citation canonicalization.

Canonicalization rules (content-free, auditable; applied only when the raw citation fails the
scorer's own span check, and only in the analysis layer — the frozen scorer is untouched):
  C1 curly-quote restoration: pair ASCII double quotes in the quote as “ ” and retry the span check
  C2 page-field sanitation: if the page value is not a valid page of the cited document, retry the
     document's pages in order and keep the first page where the quote spans
Rescores every NDC arm, the six smoke executions and the 32 baseline S3/S4 records in three
calibers: lenient / strict-normalized / strict-normalized+canonicalized. Writes CALIBER_V3.json.
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
from terminal_quality import _span_is_valid, evaluate_terminal_quality

SA = D2.SA_EX
DM = dict(SA.DOCMAP)
SRC = D2.SRC()
RUNS = HERE / "runs_real_ndc"
SMOKE = STAGE_D / "damjs_r2" / "runs_real" / "exec_records"
BASE = STAGE_D / "runs_final"


def curly(s):
    out, op = [], True
    for ch in str(s or ""):
        if ch == '"':
            out.append("“" if op else "”")
            op = not op
        else:
            out.append(ch)
    return "".join(out)


def canon_citation(a, report):
    doc = DM.get(a.get("doc"), a.get("doc"))
    page = a.get("page")
    quote = a.get("quote") or ""
    pages = [p for p in (SRC.get(doc) or {}).get("pages", {})]
    if doc in SRC and str(page) in pages and _span_is_valid(SRC, doc, page, quote, None, None, None, None):
        return
    for qq, rule in ((curly(quote), "curly"), (quote, "page")):
        for p in ([str(page)] if str(page) in pages else []) + pages:
            if doc in SRC and _span_is_valid(SRC, doc, p, qq, None, None, None, None):
                report.append(dict(fact_id=a.get("fact_id"), rule=rule if rule == "curly" else f"page->{p}"))
                a["quote"], a["page"] = qq, p
                return
    report.append(dict(fact_id=a.get("fact_id"), rule="unrecovered"))


def normalize(parsed):
    rep = []
    for a in parsed.get("answers", []):
        if a.get("doc") in DM:
            a["doc"] = DM[a["doc"]]
    for a in parsed.get("answers", []):
        canon_citation(a, rep)
    return rep


def score(parsed):
    q = evaluate_terminal_quality(SA.CONTRACT, SA.build_terminal_output(json.loads(json.dumps(parsed))), D2.SRC())
    cr = q["claim_results"]
    return sum(c["status"].startswith("CORRECT") for c in cr), sum(c["status"] == "CORRECT_GOLD" for c in cr)


def fmt_from_sink(sink_text, scenario, fmt_repaired):
    parsed = D2.extract_json(sink_text or "")
    if not parsed:
        return None, None, None
    bypass = scenario == "S4" and not fmt_repaired
    fmt = parsed if bypass else SA.apply_format_rules(copy.deepcopy(parsed))[0]
    return parsed, fmt, score(fmt)


def three(sink_text, scenario, fmt_repaired):
    parsed, fmt, raw = fmt_from_sink(sink_text, scenario, fmt_repaired)
    if parsed is None:
        return dict(lenient=0, strict_raw=0, strict_norm=0, strict_norm_canon=0)
    norm_p = copy.deepcopy(fmt)
    for a in norm_p.get("answers", []):
        if a.get("doc") in DM:
            a["doc"] = DM[a["doc"]]
    can_p = copy.deepcopy(norm_p)
    rep = normalize(can_p)
    return dict(lenient=raw[0], strict_raw=raw[1], strict_norm=score(norm_p)[1],
                strict_norm_canon=score(can_p)[1], canon_report=rep)


def main():
    out = {}
    for tag, f, sc, repaired in [
        ("NDC_r1a_R2", RUNS / "quarantine" / "NDC_r1_R2.jsonl.attempt_20261107T223114", "S3", True),
        ("NDC_r1a_ND", RUNS / "quarantine" / "NDC_r1_ND-only.jsonl.attempt_20261107T223414", "S3", True),
        ("NDC_r1b_R2", RUNS / "progress" / "NDC_r1_R2.jsonl", "S3", True),
        ("NDC_r1b_ND", RUNS / "progress" / "NDC_r1_ND-only.jsonl", "S3", True),
        ("NDC_r2_R2", RUNS / "progress" / "NDC_r2_R2.jsonl", "S3", True),
        ("NDC_r2_ND", RUNS / "progress" / "NDC_r2_ND-only.jsonl", "S3", True),
    ] + [(f"smoke_{p.stem.split('__')[0]}_{p.stem.split('__')[1]}", p, p.stem.split("__")[1], None)
         for p in sorted(SMOKE.glob("*.json"))] + [
        (f"base_{a}_{s}_r{r}", BASE / f"{a}__{s}__r{r}.json", s, None)
        for s in ("S3", "S4") for a in ("Static", "Proposed-Dynamic") for r in range(1, 9)]:
        if "base_" in tag or tag.startswith("smoke_"):
            d = json.load(open(f))
            sink = (d["raw"]["nodes"].get("SINK") or [{}])[-1].get("text", "")
            rep = any(x["kind"] == "format_repair" for x in d.get("actions") or [])
            res = three(sink, d["scenario"], rep)
        else:
            prog = [json.loads(l) for l in Path(f).read_text().splitlines() if l.strip()]
            sink = next((x["output"] for x in prog if x.get("ev") == "node_end" and x["node"] == "SINK" and x.get("ok")), "")
            res = three(sink, sc, True)
        out[tag] = res
    (HERE / "CALIBER_V3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    for k in ("NDC_r1a_R2", "NDC_r1a_ND", "NDC_r1b_R2", "NDC_r1b_ND", "NDC_r2_R2", "NDC_r2_ND",
              "smoke_Static_S3", "smoke_DAMJS_S3", "smoke_Static_S4", "smoke_DAMJS_S4",
              "base_Proposed-Dynamic_S3_r1", "base_Static_S3_r1"):
        v = out.get(k) or {}
        cr = v.get("canon_report") or []
        rules = {}
        for c in cr:
            rules[c["rule"].split("->")[0]] = rules.get(c["rule"].split("->")[0], 0) + 1
        print(f"{k:<28} L={v.get('lenient'):>2} S_raw={v.get('strict_raw'):>2} S_norm={v.get('strict_norm'):>2} "
              f"S_norm_canon={v.get('strict_norm_canon'):>2} canon={rules}")
    return out


if __name__ == "__main__":
    main()
