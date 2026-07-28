from openclaw_router.experience import RoutingExperienceStore, automatic_verification, feedback_reward, utility_score


def event_payload(**overrides):
    base = dict(
        query="审计收入确认是否正确", user_id="u1", selected_model="qwen-plus",
        candidate_models=["qwen-plus", "deepseek-chat"], api_success=True,
        quality_score=0.9, cost_reward=0.9, latency_reward=0.8, reliability=1.0,
        estimated_regret=0.02, regret_epsilon=0.1, constraint_violation=False,
        fallback_count=0, risk_level="high", objective_score=1.0, quality_threshold=0.75,
    )
    base.update(overrides)
    return base


def test_reward_signs_are_directionally_correct():
    good = feedback_reward(automatic_quality=1, user_feedback=1, cost_reward=1, latency_reward=1, reliability=1)
    bad = feedback_reward(automatic_quality=0, user_feedback=0, cost_reward=0, latency_reward=0, reliability=0, constraint_violation=True)
    assert good == 1.0
    assert bad == 0.0
    assert utility_score(quality=1, cost_reward=1, latency_reward=1, reliability=1) == 1.0


def test_pending_is_not_retrieved_and_feedback_transitions(tmp_path):
    store = RoutingExperienceStore(tmp_path / "events.jsonl")
    pending = store.create(**event_payload())
    assert store.retrieve("审计收入确认") == []
    approved = store.apply_feedback(pending["request_id"], rating="up", reason="answer_correct")
    assert approved["verification_status"] == "verified_positive"
    assert approved["routing_correct"] is True
    assert store.retrieve("审计收入确认")[0]["selected_model"] == "qwen-plus"


def test_negative_feedback_prevents_positive_memory_and_persists(tmp_path):
    path = tmp_path / "events.jsonl"
    store = RoutingExperienceStore(path)
    event = store.create(**event_payload(selected_model="deepseek-chat"))
    rejected = store.apply_feedback(event["request_id"], rating="down", reason="wrong_model", preferred_model="qwen-plus")
    assert rejected["verification_status"] == "verified_negative"
    assert rejected["routing_correct"] is False
    assert rejected["reward"] == 0.0
    reloaded = RoutingExperienceStore(path)
    assert reloaded.get(event["request_id"])["preferred_model"] == "qwen-plus"
    stats = reloaded.model_statistics("审计收入确认", ["qwen-plus", "deepseek-chat"], user_id="u1")
    assert stats["deepseek-chat"]["negative_weight"] > 0


def test_high_risk_objective_failure_cannot_be_positive(tmp_path):
    store = RoutingExperienceStore(tmp_path / "events.jsonl")
    event = store.create(**event_payload(objective_score=0.0))
    reviewed = store.apply_feedback(event["request_id"], rating="up", reason="answer_correct")
    assert reviewed["routing_correct"] is False
    assert reviewed["verification_status"] == "disputed"


def test_expired_events_are_audited_but_excluded_from_metrics(tmp_path):
    store = RoutingExperienceStore(tmp_path / "events.jsonl")
    event = store.create(**event_payload())
    store.expire(event["request_id"], "test")
    metrics = store.metrics()
    assert metrics["events"] == 0
    assert metrics["audit_events"] == 1
    assert metrics["expired_events"] == 1


def test_config_version_isolation(tmp_path):
    store = RoutingExperienceStore(tmp_path / "events.jsonl")
    event = store.create(**event_payload(config_version="v1"))
    store.apply_feedback(event["request_id"], rating="up", reason="answer_correct")
    assert store.retrieve("审计收入确认", config_version="v1")
    assert store.retrieve("审计收入确认", config_version="v2") == []


def test_automatic_verification_without_user_feedback():
    positive = automatic_verification(
        api_success=True, quality_score=0.9, quality_threshold=0.75,
        risk_level="high", objective_score=1.0, constraint_violation=False,
        estimated_regret=0.02, regret_epsilon=0.1, manual_review_required=False,
        cost_reward=0.9, latency_reward=0.8, reliability=1.0,
    )
    assert positive["verification_status"] == "verified_positive"
    assert positive["routing_correct"] is True
    assert positive["reward"] > 0


def test_automatic_verification_guards_high_risk_and_disagreement():
    wrong = automatic_verification(
        api_success=True, quality_score=0.9, quality_threshold=0.75,
        risk_level="high", objective_score=0.0, constraint_violation=False,
        estimated_regret=0.02, regret_epsilon=0.1, manual_review_required=False,
        cost_reward=0.9, latency_reward=0.8, reliability=1.0,
    )
    disputed = automatic_verification(
        api_success=True, quality_score=0.9, quality_threshold=0.75,
        risk_level="high", objective_score=1.0, constraint_violation=False,
        estimated_regret=0.02, regret_epsilon=0.1, manual_review_required=True,
        cost_reward=0.9, latency_reward=0.8, reliability=1.0,
    )
    assert wrong["verification_status"] == "verified_negative"
    assert wrong["routing_correct"] is False
    assert disputed["verification_status"] == "disputed"
    assert disputed["routing_correct"] is None


def test_disputed_experience_is_not_used_for_routing(tmp_path):
    store = RoutingExperienceStore(tmp_path / "events.jsonl")
    event = store.create(**event_payload(verification_status="disputed", reward=0.95))
    assert store.retrieve("审计收入确认") == []
    stats = store.model_statistics("审计收入确认", ["qwen-plus", "deepseek-chat"], user_id="u1")
    assert stats["qwen-plus"]["history_count"] == 0


def test_negative_feedback_and_negative_experience_rates_are_distinct(tmp_path):
    store = RoutingExperienceStore(tmp_path / "events.jsonl")
    automatic_negative = store.create(**event_payload(verification_status="verified_negative", routing_correct=False))
    metrics = store.metrics()
    assert metrics["negative_feedback_rate"] == 0.0
    assert metrics["negative_experience_rate"] == 1.0
    store.apply_feedback(automatic_negative["request_id"], rating="down", reason="answer_wrong")
    metrics = store.metrics()
    assert metrics["negative_feedback_rate"] == 1.0
