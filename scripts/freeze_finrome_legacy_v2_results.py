#!/usr/bin/env python3
"""Create a read-only, content-addressed snapshot of the completed formal run."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/finance_router/finrome_legacy_v2_confirmatory"
ARCHIVES = ROOT / "run_logs/finrome_legacy_v2_confirmatory/archives"

REQUIRED = (
    "tasks.jsonl",
    "responses.jsonl",
    "judges.jsonl",
    "scored_responses.jsonl",
    "utility_matrix.jsonl",
    "matrix_report.json",
    "manual_review_pending.jsonl",
    "high_disagreement_pending.jsonl",
    "high_risk_uncertainty_pending.jsonl",
    "judge_parse_failures_pending.jsonl",
    "PREREGISTRATION.json",
    "PREREGISTRATION.sha256",
    "FROZEN_POLICY.json",
    "EXECUTION_SEAL.json",
    "EXECUTION_SEAL.sha256",
    "FORMAL_AUTHORIZATION.json",
    "CODE_SEAL.json",
    "CODE_SEAL.sha256",
    "formal_run.log",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonl_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(bool(line.strip()) for line in handle)


def jsonl_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    missing = [name for name in REQUIRED if not (SOURCE / name).is_file()]
    if missing:
        raise SystemExit(f"Missing required artifacts: {', '.join(missing)}")

    report = json.loads((SOURCE / "matrix_report.json").read_text())
    expected_derived = {
        "scored_responses.jsonl": 9600,
        "utility_matrix.jsonl": 3200,
        "manual_review_pending.jsonl": 1752,
        "judge_parse_failures_pending.jsonl": 0,
    }
    observed_derived = {name: jsonl_count(SOURCE / name) for name in expected_derived}
    if observed_derived != expected_derived:
        raise SystemExit(
            f"Derived-artifact mismatch: expected={expected_derived}, observed={observed_derived}"
        )
    responses = jsonl_rows(SOURCE / "responses.jsonl")
    response_latest = {
        (row["task_id"], row["model"], row["repeat"]): row for row in responses
    }
    valid_response_keys = sum(
        bool(row.get("success") and str(row.get("answer") or "").strip())
        for row in response_latest.values()
    )
    judges = jsonl_rows(SOURCE / "judges.jsonl")
    judge_latest = {
        (row["task_id"], row["candidate_model"], row["repeat"], row["judge_model"]): row
        for row in judges
    }
    valid_judge_keys = sum(bool(row.get("parsed")) for row in judge_latest.values())
    if valid_response_keys != 9600 or valid_judge_keys != 12600:
        raise SystemExit(
            f"Unique-key mismatch: responses={valid_response_keys}/9600, judges={valid_judge_keys}/12600"
        )
    if report.get("judge_rows") != 12600 or report.get("complete_tasks") != 800:
        raise SystemExit(f"Matrix report is incomplete: {report}")
    matrix_sha = sha256(SOURCE / "utility_matrix.jsonl")
    if matrix_sha != report.get("matrix_sha256"):
        raise SystemExit("utility_matrix.jsonl does not match matrix_report.json")

    snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = ARCHIVES / snapshot_id
    destination.mkdir(parents=True, exist_ok=False)
    files = []
    for name in REQUIRED:
        src = SOURCE / name
        dst = destination / name
        shutil.copy2(src, dst)
        files.append({"path": name, "bytes": dst.stat().st_size, "sha256": sha256(dst)})

    for src in sorted(SOURCE.glob("*quarantine*.jsonl")):
        dst = destination / src.name
        shutil.copy2(src, dst)
        files.append({"path": src.name, "bytes": dst.stat().st_size, "sha256": sha256(dst)})

    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(SOURCE.relative_to(ROOT)),
        "status": "FORMAL_COLLECTION_COMPLETE_READ_ONLY_SNAPSHOT",
        "validated_counts": observed_derived
        | {
            "responses_raw_rows": len(responses),
            "responses_valid_unique": valid_response_keys,
            "judges_raw_rows": len(judges),
            "judges_valid_unique": valid_judge_keys,
            "complete_tasks": 800,
        },
        "utility_matrix_sha256": matrix_sha,
        "files": sorted(files, key=lambda item: item["path"]),
    }
    manifest_path = destination / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (destination / "MANIFEST.sha256").write_text(
        f"{sha256(manifest_path)}  MANIFEST.json\n"
    )
    for path in destination.iterdir():
        path.chmod(0o444)
    destination.chmod(0o555)
    print(json.dumps({"snapshot": str(destination), **manifest["validated_counts"], "matrix_sha256": matrix_sha}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
