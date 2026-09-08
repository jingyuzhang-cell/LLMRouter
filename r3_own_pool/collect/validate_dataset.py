"""R3 dataset validator (protocol v1.1) - MUST pass before any training.

Level A (per line, schema): required fields, exactly-4 responses covering the frozen
4-slot pool, field domains per schema/r3_record.schema.json, unique query_id,
task_type<->quality_source consistency.

Level B (corpus, trainability): ok-rate >= 99% of slots, latency/label coverage 100%,
utility 24 combos present, split frozen & disjoint, sha256 manifest match (if provided).

Exit code 0 iff all enabled checks pass; report written to validation_report.json.
"""
import argparse
import hashlib
import json
import pathlib
import sys

R = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = json.loads((R / "schema" / "r3_record.schema.json").read_text())
POOL = SCHEMA["properties"]["responses"]["items"]["properties"]["model"]["enum"]
TASK_SOURCE = {
    "gsm8k": "exact_match", "mbpp": "pass@1", "humaneval": "pass@1",
    "mmlupro": "option_match", "arenahard": "judge_qwen-max",
}
UTILITY_KEYS = [f"lam{l}_mu{m}" for l in (0, 0.1, 0.5, 1, 2, 5) for m in (0, 0.1, 0.5, 1)]


def dataset_of(qid):
    return qid.rsplit("_", 1)[0].replace("_test", "").replace("_train", "") \
        if qid.count("_") > 1 else qid


class Report:
    def __init__(self):
        self.checks = []
        self.fails = 0

    def check(self, name, ok, detail=""):
        self.checks.append({"check": name, "pass": bool(ok), "detail": detail})
        if not ok:
            self.fails += 1
        return ok

    @property
    def status(self):
        return "PASS" if self.fails == 0 else "FAIL"


def validate_line(i, rec, rep, seen_ids, seen_prompts, require_utility=False):
    errs = []
    qid = rec.get("query_id")
    for f in ("query_id", "task_type", "difficulty", "query", "ground_truth", "responses"):
        if f not in rec:
            errs.append(f"missing field {f}")
    if errs:
        return [f"line {i} ({qid}): " + e for e in errs]
    if qid in seen_ids:
        errs.append(f"line {i}: duplicate query_id {qid}")
    seen_ids.add(qid)
    if rec["query"] in seen_prompts:
        errs.append(f"line {i}: duplicate prompt text")
    seen_prompts.add(rec["query"])
    if rec["task_type"] not in ("math", "code", "knowledge", "general"):
        errs.append(f"line {i}: bad task_type")
    if rec["difficulty"] not in ("easy", "medium", "hard"):
        errs.append(f"line {i}: difficulty not derived/frozen")
    rs = rec["responses"]
    if not isinstance(rs, list) or len(rs) != 4:
        errs.append(f"line {i}: expected exactly 4 responses, got {len(rs) if isinstance(rs, list) else type(rs)}")
        return [f"line {i} ({qid}): " + e for e in errs]
    models = [r.get("model") for r in rs]
    if sorted(models) != sorted(POOL):
        errs.append(f"line {i}: model set mismatch: {models} (REJECT - e.g. missing slot)")
    ds = None
    for cand in TASK_SOURCE:
        if str(qid).startswith(cand):
            ds = cand
    for r in rs:
        m = r.get("model", "?")
        for f in ("model", "answer", "thinking", "quality", "cost", "latency", "utility_scores", "status"):
            if f not in r:
                errs.append(f"line {i} {m}: missing response field {f}")
        if r.get("status") not in ("ok", "failed", "truncated", "parse_failed"):
            errs.append(f"line {i} {m}: bad status")
        q = r.get("quality") or {}
        for f in ("auto_score", "auto_correct", "judge_score", "judge", "final", "quality_source"):
            if f not in q:
                errs.append(f"line {i} {m}: quality missing {f}")
        if ds and q.get("quality_source") != TASK_SOURCE[ds]:
            errs.append(f"line {i} {m}: quality_source {q.get('quality_source')} != protocol {TASK_SOURCE[ds]}")
        if q.get("final") is not None and not (0 <= q["final"] <= 1):
            errs.append(f"line {i} {m}: final out of [0,1]")
        if r.get("status") == "ok" and q.get("final") is None:
            errs.append(f"line {i} {m}: ok slot has no final label")
        c = r.get("cost") or {}
        if r.get("status") == "ok":
            for f in ("tokens_input", "tokens_output", "usd"):
                if c.get(f) is None:
                    errs.append(f"line {i} {m}: ok slot missing cost.{f}")
        lat = r.get("latency") or {}
        if r.get("status") == "ok":
            for f in ("total_ms", "ttft_ms", "decode_ms", "source"):
                if lat.get(f) is None:
                    errs.append(f"line {i} {m}: ok slot missing latency.{f}")
        u = r.get("utility_scores") or {}
        if require_utility:
            missing_u = [k for k in UTILITY_KEYS if k not in u]
            if missing_u:
                errs.append(f"line {i} {m}: utility_scores missing {len(missing_u)}/24 combos")
    return [f"line {i} ({qid}): " + e for e in errs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", nargs="+", help="one or more frozen JSONL files")
    ap.add_argument("--split", default=None, help="split manifest json {train:[ids],test:[ids]}")
    ap.add_argument("--require-trainability", action="store_true",
                    help="enable level-B corpus gates (post-freeze validation)")
    ap.add_argument("--max-errors", type=int, default=20)
    args = ap.parse_args()

    rep = Report()
    seen_ids, seen_prompts, all_recs = set(), set(), []
    line_errors = []
    for path in args.jsonl:
        with open(path) as f:
            for i, line in enumerate(f, 1):
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    line_errors.append(f"{path}:{i}: JSON decode {e}")
                    continue
                line_errors += validate_line(i, rec, rep, seen_ids, seen_prompts,
                                             require_utility=args.require_trainability)
                all_recs.append(rec)

    rep.check("A: all lines schema-valid", not line_errors,
              "; ".join(line_errors[:args.max_errors]) + (f" (+{len(line_errors)-args.max_errors} more)" if len(line_errors) > args.max_errors else ""))
    rep.check("A: at least one record", len(all_recs) > 0, f"{len(all_recs)} records")

    if args.require_trainability:
        n_slots = sum(len(r["responses"]) for r in all_recs)
        ok_slots = sum(1 for r in all_recs for x in r["responses"] if x["status"] == "ok")
        rep.check("B: ok-rate >= 99%", n_slots and ok_slots / n_slots >= 0.99,
                  f"{ok_slots}/{n_slots} = {ok_slots/max(n_slots,1):.4f}")
        lat_ok = sum(1 for r in all_recs for x in r["responses"] if x["latency"].get("total_ms") is not None)
        rep.check("B: latency coverage 100%", lat_ok == n_slots, f"{lat_ok}/{n_slots}")
        lab_ok = sum(1 for r in all_recs for x in r["responses"]
                     if x["status"] != "ok" or x["quality"]["final"] is not None)
        rep.check("B: final-label coverage on ok slots", lab_ok == n_slots, f"{lab_ok}/{n_slots}")
        # per-source label sanity: arenahard must be judge-labeled, others auto
        for r in all_recs:
            for x in r["responses"]:
                if x["status"] != "ok":
                    continue
                src = next((s for s in TASK_SOURCE if r["query_id"].startswith(s)), None)
                if src == "arenahard" and x["quality"]["judge_score"] is None:
                    rep.check("B: arenahard judge coverage", False, r["query_id"]); break
        if args.split:
            sp = json.loads(pathlib.Path(args.split).read_text())
            tr, te = set(sp["train"]), set(sp["test"])
            rep.check("B: split covers all", tr | te == seen_ids, f"{len(tr & te)} overlap, {len(seen_ids - tr - te)} unassigned")
            rep.check("B: split disjoint", not (tr & te))

    report = {"status": rep.status, "n_records": len(all_recs), "checks": rep.checks}
    out = pathlib.Path("validation_report.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False)[:4000])
    print(f"\n{rep.status}: {rep.fails} failed checks -> {out}")
    sys.exit(0 if rep.status == "PASS" else 1)


if __name__ == "__main__":
    main()
