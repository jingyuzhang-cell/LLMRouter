from progrouter_reproduction.features import (
    MODELS,
    NODES,
    STATE_FIELDS,
    progress_views,
    request_only_vector,
    state_vector,
)


def record(node="N2"):
    return {
        "node_id": node,
        "selected_model": "qwen-plus",
        "request_features": {"tokens": 100, "has_table": True, "text": "excluded"},
        "pre_action_state": {
            "upstream_provider_success": True,
            "upstream_schema_valid": True,
            "upstream_evidence_count": 2,
            "upstream_extraction_field_count": 0,
            "upstream_confidence": 0.8,
            "upstream_output_length": 300,
            "upstream_latency_ms": 1000,
            "cumulative_cost_usd": 1,
            "remaining_budget_usd": 9,
            "retry_count": 0,
        },
    }


def test_state_vector_strictly_extends_request_only():
    row = record()
    request = request_only_vector(row)
    state = state_vector(row)
    assert state[: len(request)] == request
    assert len(state) == len(request) + len(STATE_FIELDS)
    assert len(request) == 2 + len(NODES) + len(MODELS)


def test_progress_views_are_bounded_and_pre_action_only():
    views = progress_views(record())
    assert 0 <= views.score <= 1
    assert views.budget_headroom == 0.9


def test_failed_upstream_maps_to_low_coarse_regime():
    row = record("N3")
    row["pre_action_state"]["upstream_provider_success"] = False
    assert progress_views(row).coarse_regime == 0.0
