from build_experiment_ledger import best_record, eligible_success


def test_best_record_does_not_let_later_failure_erase_success():
    rows = [
        {"model": "qwen-plus", "provider_success": True, "format_valid": True, "timestamp": "2026-01-01"},
        {"model": "qwen-plus", "provider_success": False, "format_valid": False, "timestamp": "2026-01-02"},
    ]
    assert best_record(rows)["provider_success"] is True


def test_glm_requires_frozen_inference_profile():
    old = {"model": "glm-5.2", "provider_success": True, "inference_profile": "default"}
    frozen = {"model": "glm-5.2", "provider_success": True, "inference_profile": "thinking_disabled"}
    assert eligible_success(old) is False
    assert eligible_success(frozen) is True
