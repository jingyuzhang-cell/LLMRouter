"""Offline rescore of repeat compatibility labels after option-parser audit."""
import json
from pathlib import Path

from .data import load_cohort, read_rows, sha
from .rescore_glm_pilot import extract_option

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/repeat_compatibility_115"
OUT = ROOT / "data/repeat_compatibility_115_rescore_v1"
SLOTS = ["medium", "large", "coder", "reasoning"]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    source_status = json.loads((SOURCE / "STATUS.json").read_text())
    if source_status.get("phase") != "REPEAT_LABELS_COMPLETE":
        raise ValueError("Source repeat labels are incomplete")
    for slot in SLOTS:
        if sha(SOURCE / f"{slot}.jsonl") != source_status["raw_sha256"][slot]:
            raise ValueError(f"Source hash changed: {slot}")

    cohort, _ = load_cohort(ROOT / "data/cohort_full_v2")
    OUT.mkdir(parents=True)
    expected_per_slot = source_status["records"] // len(SLOTS)
    by_slot = {}
    audits = []
    recovered = quality_flips = 0
    for slot in SLOTS:
        rows = read_rows(SOURCE / f"{slot}.jsonl")
        if len(rows) != expected_per_slot:
            raise ValueError(f"Unexpected row count: {slot}")
        rescored = []
        for row in rows:
            option = extract_option(row.get("answer") or "") if row.get("status") != "failed" else None
            gt = str(cohort[row["query_id"]]["ground_truth"]).strip().upper()[-1]
            quality = float(option == gt) if option else 0.0
            updated = {**row, "old_quality": row["quality"], "old_parse_succeeded": row["parse_succeeded"],
                       "quality": quality, "evaluation_status": "scored" if option else "answer_parse_failed",
                       "parse_succeeded": option is not None, "extracted_option": option,
                       "rescore_source_sha256": source_status["raw_sha256"][slot]}
            rescored.append(updated)
            if bool(option) != bool(row["parse_succeeded"]) or option != row.get("extracted_option"):
                recovered += int(option is not None and not row["parse_succeeded"])
                quality_flips += int(quality != row["quality"])
                audits.append({"slot": slot, "query_id": row["query_id"], "repeat_index": row["repeat_index"],
                               "finish_reason": row.get("finish_reason"), "old_option": row.get("extracted_option"),
                               "new_option": option, "ground_truth": gt, "old_quality": row["quality"],
                               "new_quality": quality, "answer": row.get("answer")})
        by_slot[slot] = rescored

    labels = {}
    for slot, rows in by_slot.items():
        for qid in sorted({r["query_id"] for r in rows}):
            values = [r["quality"] for r in rows if r["query_id"] == qid]
            if len(values) != 5:
                raise ValueError(f"Expected five values: {slot}/{qid}")
            labels.setdefault(qid, {})[slot] = {"values": values, "mean": sum(values) / 5}
    labels_path = OUT / "EXPECTED_UTILITY_LABELS.jsonl"
    labels_path.write_text("".join(json.dumps({"query_id": qid, "models": labels[qid]}, ensure_ascii=False) + "\n"
                                   for qid in sorted(labels)))
    (OUT / "AUDIT.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in audits))
    protocol = {"role": "offline answer-extraction correction", "source_dir": str(SOURCE),
                "source_status_sha256": sha(SOURCE / "STATUS.json"),
                "extractor_sha256": sha(ROOT / "router_v2/rescore_glm_pilot.py"),
                "new_generations": 0,
                "policy": "Recover explicit boxed option letters and a sole option-prefixed response; retain unparseable truncations as zero."}
    write_json(OUT / "PROTOCOL.json", protocol)
    write_json(OUT / "STATUS.json", {"phase": "REPEAT_LABELS_COMPLETE", "queries": len(labels),
                                      "records": sum(map(len, by_slot.values())),
                                      "labels_sha256": sha(labels_path), "source_raw_sha256": source_status["raw_sha256"],
                                      "recovered_parse_failures": recovered, "quality_flips": quality_flips,
                                      "audit_sha256": sha(OUT / "AUDIT.jsonl"), "new_generations": 0})
    print(json.dumps({"recovered_parse_failures": recovered, "quality_flips": quality_flips,
                      "audit_records": len(audits), "labels_sha256": sha(labels_path)}, indent=2))


if __name__ == "__main__":
    main()
