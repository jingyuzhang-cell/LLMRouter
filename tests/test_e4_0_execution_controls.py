from collections import Counter

from phase_e4_0.execution_controls import *
from run_e4_0_b_v2_controlled import checkpoint_target, frozen_state_from, node_timeout


def record(success, model="m", node="N1", task="t", trajectory="tr", valid=None):
    return {
        "task_id": task,
        "trajectory_id": trajectory,
        "node_id": node,
        "selected_model": model,
        "post_action_outcome": {
            "provider_success": success,
            "json_parse_valid": success if valid is None else valid,
            "node_schema_valid": success if valid is None else valid,
            "total_latency_ms": 10,
            "provider_latency_ms": 10,
        },
    }


def telemetry_event(**overrides):
    event = {
        "task_id": "t",
        "trajectory_id": "tr",
        "node_id": "N1",
        "selected_model": "m",
        "cost_usd": 0.01,
        "provider_success": True,
        "provider_error": None,
        "json_parse_valid": True,
        "node_schema_valid": True,
        "generation_ceiling_binding": False,
        "requested_model_alias": "m",
        "provider_returned_model": "provider-m",
        "provider": "provider",
        "provider_endpoint": "https://provider.invalid/chat/completions",
        "execution_control_version": "E4.0-B-execution-amendment-005",
        "configured_context_limit": 1000,
        "max_tokens": 100,
        "thinking_mode": "provider_default_unchanged",
        "finish_reason": "stop",
        "attempt": 1,
        "provider_latency_ms": 10,
        "retry_backoff_ms": 0,
        "scheduler_queue_wait_ms": 1,
        "timeout_seconds": 240,
        "tokens": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        "execution_timestamp": "2026-09-03T00:00:00+00:00",
        "collection_block": 50,
    }
    event.update(overrides)
    return event


def test_resume_states_and_binding():
    failed = record(False)
    assert classify(None, 0) == PENDING
    assert classify(failed, 2) == PENDING
    assert classify(failed, 3) == PERMANENT_FAILURE
    assert classify(record(True), 1) == SUCCESS
    assert generation_ceiling_binding("length", {}, 2400)
    assert generation_ceiling_binding("stop", {"completion_tokens": 2400}, 2400)


def test_dependency_and_balance():
    plan = {"task_id": "t", "trajectory_id": "tr"}
    first = record(True, node="N1")
    outcomes = {outcome_key(first): first}
    attempts = Counter({outcome_key(first): 1})
    node, key, previous = dependency_ready(plan, outcomes, attempts, ("N1", "N2"))
    assert node == "N2"
    assert previous == [first]
    assert balanced("a", Counter(a=19, b=0), ("a", "b"))
    assert not balanced("a", Counter(a=20, b=0), ("a", "b"))


def test_node_schema_validity_is_stricter_than_json_parse():
    assert node_schema_valid("N1", {"evidence_items": [], "confidence": 0.5})
    assert not node_schema_valid("N1", {"answer": "wrong node", "confidence": 0.5})
    assert node_schema_valid("N2", {"fields": {}, "missing": [], "confidence": 0.5})
    assert node_schema_valid(
        "N3",
        {"intermediate_result": 1, "assumptions": [], "evidence_links": [], "confidence": 0.5},
    )
    assert node_schema_valid("N4", {"answer": "1", "citations": [], "confidence": 0.5})
    assert not node_schema_valid("N4", {"answer": "", "citations": [], "confidence": 0.5})


def test_provider_limited_batch_counts_shared_provider_once():
    candidates = [
        {"priority": "1", "plan": {"trajectory_id": "a"}, "provider": "qwen"},
        {"priority": "2", "plan": {"trajectory_id": "b"}, "provider": "qwen"},
        {"priority": "3", "plan": {"trajectory_id": "c"}, "provider": "deepseek"},
        {"priority": "4", "plan": {"trajectory_id": "d"}, "provider": "zhipu"},
    ]
    batch = select_provider_limited_batch(candidates, global_limit=4, per_provider_limit=1)
    assert [item["plan"]["trajectory_id"] for item in batch] == ["a", "c", "d"]
    assert len({item["provider"] for item in batch}) == len(batch)


def test_frozen_runtime_controls_and_state_contract():
    assert [node_timeout(node) for node in ("N1", "N2", "N3", "N4")] == [240.0, 120.0, 120.0, 120.0]
    assert checkpoint_target(0, 640) == 50
    assert checkpoint_target(50, 640) == 100
    state = frozen_state_from([], 0, 10)
    assert set(state) == {
        "upstream_provider_success",
        "upstream_schema_valid",
        "upstream_output_length",
        "upstream_evidence_count",
        "upstream_extraction_field_count",
        "upstream_confidence",
        "upstream_latency_ms",
        "cumulative_cost_usd",
        "remaining_budget_usd",
        "retry_count",
    }


def test_provider_cooldown_and_passing_health_audit():
    health = ProviderHealth(cooldown_seconds=600)
    assert not health.observe("provider", 429, 100)
    assert not health.observe("provider", 429, 101)
    assert health.observe("provider", 429, 102)
    assert not health.available("provider", 200)
    assert health.available("provider", 702)
    rec = record(True)
    audit = health_audit(
        [telemetry_event()],
        {outcome_key(rec): rec},
        ("m",),
        ("N1",),
        1,
        records=[rec],
        model_to_provider={"m": "provider"},
        revalidation_completed=True,
        validator_implementation_verified=True,
    )
    assert audit["unique_final_outcomes"] == 1
    assert audit["semantic_quality_accessed"] is False
    assert audit["checkpoint_gate_pass"]


def test_health_audit_stops_on_missing_telemetry_and_bad_format():
    rec = record(True, valid=False)
    event = telemetry_event(json_parse_valid=False, node_schema_valid=False)
    event.pop("provider_returned_model")
    audit = health_audit(
        [event],
        {outcome_key(rec): rec},
        ("m",),
        ("N1",),
        1,
        records=[rec],
        revalidation_completed=True,
        validator_implementation_verified=True,
    )
    assert not audit["json_parse_gate_pass"]
    assert not audit["node_schema_gate_pass"]
    assert not audit["format_gate_pass"]
    assert not audit["telemetry_gate_pass"]
    assert not audit["checkpoint_gate_pass"]


def test_model_schema_failure_is_diagnostic_not_resume_gate():
    rec = record(True, valid=False)
    audit = health_audit(
        [telemetry_event(json_parse_valid=False, node_schema_valid=False)],
        {outcome_key(rec): rec},
        ("m",), ("N1",), 1,
        records=[rec],
        revalidation_completed=True,
        validator_implementation_verified=True,
    )
    assert not audit["node_schema_diagnostic_pass"]
    assert audit["checkpoint_gate_pass"]


def test_retained_terminal_artificial_ceiling_is_resume_gate():
    rec = record(True)
    rec["post_action_outcome"]["generation_ceiling_binding"] = True
    audit = health_audit(
        [telemetry_event(generation_ceiling_binding=True)],
        {outcome_key(rec): rec},
        ("m",), ("N1",), 1,
        records=[rec],
        revalidation_completed=True,
        validator_implementation_verified=True,
    )
    assert audit["terminal_engineering_binding_count"] == 1
    assert not audit["truncation_gate_pass"]
    assert not audit["checkpoint_gate_pass"]


def test_validator_contract_audit_passes_all_frozen_vectors():
    result = validator_contract_audit()
    assert result["verified"]
    assert result["check_count"] == 8


def test_duplicate_audit_preserves_history_but_gates_only_active_terminals():
    older = record(True)
    older["post_action_outcome"]["attempt"] = 1
    newer = record(True)
    newer["post_action_outcome"]["attempt"] = 2
    old_event = telemetry_event(attempt=1)
    new_event = telemetry_event(attempt=2)
    audit = health_audit(
        [old_event, new_event], {outcome_key(newer): newer}, ("m",), ("N1",), 1,
        records=[older, newer], revalidation_completed=True,
        validator_implementation_verified=True,
    )
    assert audit["historical_duplicate_record_count"] == 1
    assert audit["historical_duplicate_success_count"] == 1
    assert audit["active_duplicate_terminal_count"] == 0
    assert audit["duplicate_gate_pass"]

    competing = record(True)
    competing["post_action_outcome"]["attempt"] = 2
    competing_event = telemetry_event(attempt=2)
    failed = health_audit(
        [old_event, new_event, competing_event], {outcome_key(newer): newer}, ("m",), ("N1",), 1,
        records=[older, newer, competing], revalidation_completed=True,
        validator_implementation_verified=True,
    )
    assert failed["active_duplicate_terminal_count"] == 1
    assert not failed["duplicate_gate_pass"]


def test_plan_reconciliation_checks_assignments_and_transitions():
    plan = {
        "task_id": "t",
        "trajectory_id": "tr",
        "assignment": {"N1": "a", "N2": "b"},
    }
    first = record(True, model="a", node="N1")
    second = record(True, model="b", node="N2")
    outcomes = {outcome_key(first): first, outcome_key(second): second}
    result = plan_reconciliation([plan], outcomes, ("N1", "N2"))
    assert result["missing_key_count"] == 0
    assert result["assignment_mismatch_count"] == 0
    assert not result["complete_transition_gate_pass"]
    assert not result["transition_balance_gate_pass"]
