#!/usr/bin/env python3
"""Zero-call claim-level audit of NDC downstream evidence quality (VALUE / LOCALIZATION / SUPPORT).

For every answer of every NDC arm execution (r1a from quarantine archives, r1b/r2 from results):
  VALUE        scorer verdict on the value (correct / wrong)
  LOCALIZATION doc and page vs the fact's gold evidence references
  SUPPORT      quote text vs the gold reference quote (normalized containment), and whether the
               correct citation EXISTS upstream in this run (E quotes, J1 evidence, J2 evidence)
               -> root cause: upstream_absent | sink_copy_failure | wrong_reference
Contrast arm: the baseline S3 Proposed-Dynamic records (repaired relay, strict 13-15) show the
healthy pattern. Writes NDC_EVIDENCE_AUDIT.json.
"""
import copy
import json
import tempfile
import re
import sys
import unicodedata


def _ref_ok(cite, e):
    return (str(cite["doc"]) == str(e.get("doc_id")) and str(cite["page"]) == str(e.get("page"))
            and bool(cite["quote"]) and (_norm(e.get("quote")) in cite["quote"] or cite["quote"] == _norm(e.get("quote"))))
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import d2_executor as D2
from terminal_quality import evaluate_terminal_quality

SA = D2.SA_EX
DOCMAP = dict(SA.DOCMAP)
RUNS = HERE / "runs_real_ndc"
BASE = STAGE_D / "runs_final"


def _norm(t):
    t = unicodedata.normalize("NFKC", str(t or ""))
    return re.sub(r"\s+", "", t)


def gold_refs():
    out = {}
    for f in SA.CONTRACT["required_facts"]:
        out[f["fact_id"]] = [r for r in (f.get("source_evidence") or []) if isinstance(r, dict)]
    return out


def norm_ans(parsed):
    for a in parsed.get("answers", []):
        if a.get("doc") in DOCMAP:
            a["doc"] = DOCMAP[a["doc"]]
    return parsed


def collect_run(tag, prog_file, late=None):
    prog = [json.loads(l) for l in Path(prog_file).read_text().splitlines() if l.strip()]
    fmts = [x for x in prog if x.get("ev") == "node_end" and x["node"] == "FMT" and x.get("ok")]
    if not fmts:
        return None
    parsed = D2.extract_json(fmts[-1]["output"]) or {}
    parsed = norm_ans(parsed)
    q = evaluate_terminal_quality(SA.CONTRACT, SA.build_terminal_output(json.loads(json.dumps(parsed))), D2.SRC())
    verdict = {c["fact_id"]: c["status"] for c in q["claim_results"]}
    # upstream availability: any (doc,page) + quote text from E/J1/J2 outputs of THIS run
    upstream = []
    for node in ("E1", "E2", "E3", "E4", "J1", "J2"):
        for x in prog:
            if x.get("ev") == "node_end" and x["node"] == node and x.get("ok") and x.get("output"):
                p = D2.extract_json(x["output"])
                if not isinstance(p, dict):
                    continue
                blobs = []

                def walk(o):
                    if isinstance(o, dict):
                        if o.get("quote"):
                            blobs.append(o)
                        for v in o.values():
                            walk(v)
                    elif isinstance(o, list):
                        for v in o:
                            walk(v)
                walk(p)
                for b in blobs:
                    upstream.append(dict(node=node, doc=b.get("doc_id") or b.get("doc") or (DOCMAP.get(node)),
                                         page=str(b.get("page")), quote=_norm(b.get("quote"))))
    rows = []
    for a in parsed.get("answers", []):
        fid = a.get("fact_id")
        refs = gold_refs().get(fid) or []
        v = verdict.get(fid, "NO_CLAIM")
        value_ok = str(v).startswith("CORRECT")
        cite = dict(doc=a.get("doc"), page=str(a.get("page")), quote=_norm(a.get("quote")))
        diags = []
        for e in refs:
            d_ok = str(cite["doc"]) == str(e.get("doc_id"))
            p_ok = str(cite["page"]) == str(e.get("page"))
            q_ok = bool(cite["quote"]) and (_norm(e.get("quote")) in cite["quote"] or cite["quote"] == _norm(e.get("quote")))
            if d_ok and p_ok and q_ok:
                diags.append(None)   # placeholder: matched ref
                continue
            avail = any(u["doc"] == str(e.get("doc_id")) and u["page"] == str(e.get("page"))
                        and _norm(e.get("quote")) and (_norm(e.get("quote")) in u["quote"] or u["quote"] == _norm(e.get("quote")))
                        for u in upstream)
            why = ("upstream_absent" if not avail else
                   "wrong_doc" if not d_ok else
                   "wrong_page" if not p_ok else
                   "quote_mismatch")
            diags.append(dict(ref=e.get("doc_id"), avail_upstream=avail, why=why,
                              ans_doc=cite["doc"], ref_doc=e.get("doc_id"),
                              ans_page=cite["page"], ref_page=str(e.get("page")),
                              quote_head=cite["quote"][:40]))
        mode = None
        for f in SA.CONTRACT["required_facts"]:
            if f["fact_id"] == fid:
                mode = f.get("evidence_mode") or ("ALL" if f.get("derivation") else "ANY")
                break
        matched = [i for i, e in enumerate(refs) if _ref_ok(cite, e)]
        if mode == "ALL":
            diags = [d for i, d in enumerate(diags) if i not in matched]
            support_ok_refs = len(matched) == len(refs)
        else:
            diags = [] if matched else [d for d in diags if d]
            support_ok_refs = bool(matched)
        rows.append(dict(fact_id=fid, value_ok=value_ok, verdict=v, mode=mode, n_refs=len(refs),
                         support_ok=not diags and support_ok_refs, failed_refs=diags))
    return dict(tag=tag, rows=rows,
                summary=dict(n_answers=len(rows),
                             value_ok=sum(r["value_ok"] for r in rows),
                             cited_ok=sum(1 for r in rows if r["value_ok"] and not r["failed_refs"]),
                             causes={}))


def main():
    runs = []
    for tag, f in (("r1a_R2", RUNS / "quarantine" / "NDC_r1_R2.jsonl.attempt_20261107T223114"),
                   ("r1a_ND", RUNS / "quarantine" / "NDC_r1_ND-only.jsonl.attempt_20261107T223414"),
                   ("r1b_R2", RUNS / "progress" / "NDC_r1_R2.jsonl"),
                   ("r1b_ND", RUNS / "progress" / "NDC_r1_ND-only.jsonl"),
                   ("r2_R2", RUNS / "progress" / "NDC_r2_R2.jsonl")):
        r = collect_run(tag, f)
        if r:
            runs.append(r)
    # baseline contrast: repaired-relay Proposed S3 r1 (strict 14) and no-relay Static S3 r1 (norm strict 8)
    for tag, f in (("baseProp_S3_r1", BASE / "Proposed-Dynamic__S3__r1.json"),
                   ("baseStatic_S3_r1", BASE / "Static__S3__r1.json")):
        d = json.load(open(f))
        tmp = Path(tempfile.mktemp(suffix=".jsonl"))
        sink = (d["raw"]["nodes"].get("SINK") or [{}])[-1].get("text", "")
        fmt_txt = json.dumps(SA.apply_format_rules(copy.deepcopy(D2.extract_json(sink)))[0], ensure_ascii=False)
        lines = [json.dumps({"ev": "node_end", "node": "FMT", "ok": True, "output": fmt_txt}, ensure_ascii=False)]
        for node in ("E1", "E2", "E3", "E4", "J1", "J2"):
            for e in d["raw"]["nodes"].get(node, []):
                if e.get("text"):
                    lines.append(json.dumps({"ev": "node_end", "node": node, "ok": True, "output": e["text"]},
                                            ensure_ascii=False))
        tmp.write_text("\n".join(lines) + "\n", "utf-8")
        r = collect_run(tag, tmp)
        if r:
            runs.append(r)
    causes = {}
    for r in runs:
        c = {}
        for row in r["rows"]:
            for fr in row["failed_refs"]:
                c[fr["why"]] = c.get(fr["why"], 0) + 1
                causes.setdefault(r["tag"], {}).setdefault(fr["why"], 0)
                causes[r["tag"]][fr["why"]] += 1
        r["summary"]["causes"] = c
    out = dict(generated="2026-11-07", runs=[dict(tag=r["tag"], summary=r["summary"], rows=r["rows"]) for r in runs])
    (HERE / "NDC_EVIDENCE_AUDIT.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    for r in runs:
        s = r["summary"]
        print(f"{r['tag']:<16} answers={s['n_answers']:>2} value_ok={s['value_ok']:>2} cited_ok={s['cited_ok']:>2} causes={s['causes']}")
    return out


if __name__ == "__main__":
    main()
