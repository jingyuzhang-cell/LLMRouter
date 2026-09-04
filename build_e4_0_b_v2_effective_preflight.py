#!/usr/bin/env python3
"""Build the outcome-blind per-model effective-preflight evidence artifact."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "phase_e4_0_v2"
ORIGINAL = OUT / "E4_0_B_V2_LONG_N1_PREFLIGHT.json"
CALIBRATION = OUT / "E4_0_B_V2_DS_GLM_ORIGINAL_PREFLIGHT_CALIBRATION.json"
EFFECTIVE = OUT / "E4_0_B_V2_EFFECTIVE_PREFLIGHT.json"
ORIGINAL_SHA256 = "cfee622a6d4532dd7b16a3cecd1ff64f6169410bc8c25fe5f6e8f7a43d1bbdc6"
CALIBRATION_SHA256 = "2c0b75e4dd95e381dc6cf51eb1394afe7d8f0ca8242aa01a8cd13f53c0aa2946"
TASK_ID = "c9_5520e79f10692ace1df3"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def passing(record):
    return (
        record.get("provider_success") is True
        and record.get("format_valid") is True
        and record.get("generation_ceiling_binding") is not True
        and record.get("finish_reason") == "stop"
    )


def build_effective(original_path=ORIGINAL, calibration_path=CALIBRATION,
                    original_sha=ORIGINAL_SHA256, calibration_sha=CALIBRATION_SHA256, source_root=ROOT):
    original_path, calibration_path = Path(original_path), Path(calibration_path)
    source_hashes_valid = sha256(original_path) == original_sha and sha256(calibration_path) == calibration_sha
    original = json.loads(original_path.read_text())
    calibration = json.loads(calibration_path.read_text())
    original_by_model = {row.get("model"): row for row in original.get("results", [])}
    calibration_by_model = {row.get("requested_model_alias"): row for row in calibration.get("results", [])}
    calibration_contract_valid = (
        calibration.get("status") == "PASS"
        and calibration.get("outcome_blind") is True
        and calibration.get("semantic_quality_accessed") is False
        and calibration.get("frozen_task_id") == TASK_ID
        and set(calibration_by_model) == {"deepseek-chat", "glm-5.2"}
    )
    specs = {
        "qwen-plus": (original_by_model.get("qwen-plus"), original_path, original_sha, "original_long_n1_preflight"),
        "qwen-turbo": (original_by_model.get("qwen-turbo"), original_path, original_sha, "original_long_n1_preflight"),
        "deepseek-chat": (calibration_by_model.get("deepseek-chat"), calibration_path, calibration_sha, "same_frozen_task_compatibility_calibration"),
        "glm-5.2": (calibration_by_model.get("glm-5.2"), calibration_path, calibration_sha, "same_frozen_task_compatibility_calibration"),
    }
    models = {}
    for model, (record, source, digest, evidence_type) in specs.items():
        valid = bool(record and passing(record))
        if model in {"deepseek-chat", "glm-5.2"}:
            valid = valid and calibration_contract_valid and record.get("task_id") == TASK_ID
        models[model] = {
            "status": "PASS" if valid and source_hashes_valid else "FAIL",
            "source_path": str(source.relative_to(Path(source_root))),
            "source_sha256": digest,
            "model": model,
            "pass_evidence_type": evidence_type,
            "calibration_amendment_provenance": "E4.0-B-execution-amendment-007",
        }
    passed = source_hashes_valid and set(models) == {"qwen-plus", "qwen-turbo", "deepseek-chat", "glm-5.2"} and all(x["status"] == "PASS" for x in models.values())
    return {
        "version": "E4.0-B-v2-effective-preflight-v1",
        "status": "PASS" if passed else "FAIL",
        "outcome_blind": True,
        "semantic_quality_accessed": False,
        "reserved_holdout_accessed": False,
        "external_api_calls_during_construction": 0,
        "frozen_long_n1_task_id": TASK_ID,
        "source_hashes_valid": source_hashes_valid,
        "models": models,
    }


def main():
    payload = build_effective()
    temporary = EFFECTIVE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(EFFECTIVE)
    print(json.dumps({"status": payload["status"], "models": {k: v["status"] for k, v in payload["models"].items()}, "external_api_calls": 0}))
    raise SystemExit(0 if payload["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
