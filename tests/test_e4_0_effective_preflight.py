import hashlib
import json
from pathlib import Path

from build_e4_0_b_v2_effective_preflight import build_effective
from run_e4_0_b_v2_controlled import (
    AUTHORIZED_RECOLLECT_KEYS,
    F124_N2_KEY,
    PENDING_INITIAL_RECOVERY_KEY,
    amendment_009_escalation_allowed,
    amendment_010_escalation_allowed,
    amendment_011_escalation_allowed,
    amendment_011_binding_can_continue,
    amendment_011_next_level,
    CEILING_LADDERS,
    node_ceiling,
    in_execution_scope,
    preflight_passed,
    recovery_scope,
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence_files(tmp_path):
    passing = {"provider_success": True, "format_valid": True, "generation_ceiling_binding": False, "finish_reason": "stop"}
    original = tmp_path / "original.json"
    calibration = tmp_path / "calibration.json"
    original.write_text(json.dumps({"status": "FAIL", "results": [
        {"model": "qwen-plus", **passing}, {"model": "qwen-turbo", **passing},
        {"model": "deepseek-chat", "provider_success": False}, {"model": "glm-5.2", "provider_success": False},
    ]}))
    calibration.write_text(json.dumps({
        "status": "PASS", "outcome_blind": True, "semantic_quality_accessed": False,
        "frozen_task_id": "c9_5520e79f10692ace1df3", "results": [
            {"requested_model_alias": "deepseek-chat", "task_id": "c9_5520e79f10692ace1df3", **passing},
            {"requested_model_alias": "glm-5.2", "task_id": "c9_5520e79f10692ace1df3", **passing},
        ],
    }))
    return original, calibration


def build(tmp_path):
    original, calibration = evidence_files(tmp_path)
    payload = build_effective(original, calibration, digest(original), digest(calibration), tmp_path)
    effective = tmp_path / "effective.json"
    effective.write_text(json.dumps(payload))
    return original, calibration, effective, payload


def test_original_fail_plus_same_task_calibration_is_effective_pass(tmp_path):
    original, calibration, effective, payload = build(tmp_path)
    assert json.loads(original.read_text())["status"] == "FAIL"
    assert payload["status"] == "PASS"
    assert preflight_passed(effective, tmp_path)


def test_missing_any_model_evidence_fails(tmp_path):
    original, calibration = evidence_files(tmp_path)
    data = json.loads(original.read_text()); data["results"] = data["results"][:1]; original.write_text(json.dumps(data))
    assert build_effective(original, calibration, digest(original), digest(calibration), tmp_path)["status"] == "FAIL"


def test_source_sha_mismatch_fails(tmp_path):
    original, calibration = evidence_files(tmp_path)
    assert build_effective(original, calibration, "0" * 64, digest(calibration), tmp_path)["status"] == "FAIL"


def test_calibration_model_mismatch_fails(tmp_path):
    original, calibration = evidence_files(tmp_path)
    data = json.loads(calibration.read_text()); data["results"][1]["requested_model_alias"] = "wrong"; calibration.write_text(json.dumps(data))
    assert build_effective(original, calibration, digest(original), digest(calibration), tmp_path)["status"] == "FAIL"


def test_source_files_remain_byte_identical(tmp_path):
    original, calibration = evidence_files(tmp_path); before = digest(original), digest(calibration)
    build_effective(original, calibration, *before, tmp_path)
    assert (digest(original), digest(calibration)) == before


def test_construction_is_outcome_blind_and_has_no_provider_call(tmp_path):
    *_, payload = build(tmp_path)
    assert payload["outcome_blind"] is True
    assert payload["semantic_quality_accessed"] is False
    assert payload["external_api_calls_during_construction"] == 0


def test_runner_rejects_tampered_source(tmp_path):
    original, calibration, effective, _ = build(tmp_path)
    original.write_text(original.read_text() + " ")
    assert not preflight_passed(effective, tmp_path)


def test_recovery_scope_uses_only_manifest_authorized_keys():
    keys = {F124_N2_KEY, ("a", "a:t", "N1")}
    assert recovery_scope(keys) == keys


def test_recovery_scope_rejects_empty_or_malformed_scope():
    import pytest
    with pytest.raises(RuntimeError):
        recovery_scope(set())
    with pytest.raises(RuntimeError):
        recovery_scope({("a", "a:t", "N9")})


def test_amendment_009_glm_n2_ceiling_ladder_and_evidence_gate():
    assert [node_ceiling("N2", "glm-5.2", escalation_level=level) for level in range(3)] == [4096, 8192, 16384]
    assert not amendment_009_escalation_allowed(F124_N2_KEY, [{"finish_reason": "stop", "generation_ceiling_binding": True}])
    history = [{"finish_reason": "length", "generation_ceiling_binding": True}]
    assert amendment_009_escalation_allowed(F124_N2_KEY, history)
    history.extend({"execution_reason": "ENGINEERING_CEILING_ESCALATION"} for _ in range(2))
    assert not amendment_009_escalation_allowed(F124_N2_KEY, history)


def test_amendment_010_node_ladders_are_exact_and_model_independent():
    for model in ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo"):
        assert [node_ceiling("N3", model, escalation_level=n) for n in range(3)] == [1600, 3200, 6400]
        assert [node_ceiling("N4", model, escalation_level=n) for n in range(3)] == [1200, 2400, 4800]


def test_amendment_010_requires_both_engineering_signals_and_caps_at_two():
    assert not amendment_010_escalation_allowed("N3", [{"finish_reason": "stop", "generation_ceiling_binding": True}])
    assert not amendment_010_escalation_allowed("N3", [{"finish_reason": "length", "generation_ceiling_binding": False}])
    binding = {"finish_reason": "length", "generation_ceiling_binding": True, "node_schema_valid": True}
    assert amendment_010_escalation_allowed("N3", [binding])
    assert not amendment_010_escalation_allowed("N2", [binding])
    history = [binding] + [
        {"execution_reason": "ENGINEERING_CEILING_ESCALATION", "execution_control_version": "E4.0-B-execution-amendment-010"}
        for _ in range(2)
    ]
    assert not amendment_010_escalation_allowed("N4", history)


def test_amendment_011_unified_ladders_and_first_binding_control():
    assert CEILING_LADDERS == {
        "N1": (16384, 32768, 65536),
        "N2": (4096, 8192, 16384, 32768),
        "N3": (1600, 3200, 6400, 12800),
        "N4": (1200, 2400, 4800, 9600),
    }
    for node, ladder in CEILING_LADDERS.items():
        for model in ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo"):
            assert [node_ceiling(node, model, escalation_level=i) for i in range(len(ladder))] == list(ladder)
        first = {"finish_reason": "length", "generation_ceiling_binding": True, "max_tokens": ladder[0]}
        assert amendment_011_binding_can_continue(node, first)
        assert amendment_011_escalation_allowed(node, [first])
        assert amendment_011_next_level(node, [first]) == 1
        final = {**first, "max_tokens": ladder[-1]}
        assert not amendment_011_binding_can_continue(node, final)
        assert not amendment_011_escalation_allowed(node, [final])


def test_amendment_011_ignores_quality_schema_and_task_identity():
    base = {"finish_reason": "stop", "generation_ceiling_binding": False, "max_tokens": 1600}
    for extra in ({"semantic_quality": 0}, {"node_schema_valid": False}, {"task_id": "special"}):
        assert not amendment_011_escalation_allowed("N3", [{**base, **extra}])


def test_schema_and_semantic_fields_cannot_trigger_amendment_010():
    event = {
        "finish_reason": "stop", "generation_ceiling_binding": False,
        "node_schema_valid": False, "semantic_quality": 0, "confidence": 0,
    }
    assert not amendment_010_escalation_allowed("N3", [event])
