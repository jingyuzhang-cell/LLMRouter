from openclaw_router.ensemble import (
    FinRoME, ModelEstimate, RouterPrediction, RouterTrustStore, TaskRiskProfiler,
)


def pred(name, model, scores, confidence=.9, uncertainty=.05, **kwargs):
    return RouterPrediction(name, model, scores, confidence, uncertainty, **kwargs)


def estimates():
    return {
        "small": ModelEstimate(.65, .85, .001, 300),
        "large": ModelEstimate(.92, .98, .02, 1500),
    }


def test_profile_is_risk_and_task_aware():
    profile = TaskRiskProfiler().profile("请审计并计算该公司的估值")
    assert profile.risk_level == "high"
    assert profile.requires_math is True
    assert profile.task_type == "financial_reasoning"


def test_dynamic_fusion_selects_consensus_model():
    engine = FinRoME(largest_model="large", thresholds={"low": .8, "medium": .8, "high": .8})
    predictions = {
        "knnrouter": pred("knnrouter", "small", {"small": .8, "large": .2}, evidence_count=10),
        "mlprouter": pred("mlprouter", "small", {"small": .7, "large": .3}),
        "graphrouter": pred("graphrouter", "large", {"small": .4, "large": .6}),
    }
    decision = engine.decide("普通金融概念解释", ["small", "large"], predictions, estimates())
    assert decision.selected_model == "small"
    assert len(decision.safe_routers) == 3
    assert abs(sum(decision.router_weights.values()) - 1) < 1e-9


def test_high_risk_disagreement_uses_largest_and_review():
    engine = FinRoME(largest_model="large", thresholds={"low": .8, "medium": .8, "high": .8})
    predictions = {
        "knnrouter": pred("knnrouter", "small", {"small": .8, "large": .2}, evidence_count=10),
        "graphrouter": pred("graphrouter", "large", {"small": .2, "large": .8}),
    }
    decision = engine.decide("审计这项收入确认是否合规", ["small", "large"], predictions, estimates())
    assert decision.selected_model == "large"
    assert decision.fallback == "high_risk_disagreement"
    assert decision.manual_review_required is True


def test_model_constraints_are_non_compensatory():
    engine = FinRoME(largest_model="large", thresholds={"low": .8, "medium": .8, "high": .8})
    predictions = {"graphrouter": pred("graphrouter", "small", {"small": .99, "large": .01})}
    model_metrics = estimates()
    model_metrics["small"] = ModelEstimate(.2, .99, 0, 1)
    decision = engine.decide("普通金融问题", ["small", "large"], predictions, model_metrics)
    assert decision.selected_model == "large"
    assert "small" not in decision.safe_models


def test_no_safe_router_falls_back():
    engine = FinRoME(largest_model="large", thresholds={"low": .01, "medium": .01, "high": .01})
    predictions = {"graphrouter": pred("graphrouter", "small", {"small": 1})}
    decision = engine.decide("普通问题", ["small", "large"], predictions, estimates())
    assert decision.selected_model == "large"
    assert decision.fallback == "no_safe_router"


def test_verified_feedback_updates_router_trust(tmp_path):
    store = RouterTrustStore(tmp_path / "trust.json")
    engine = FinRoME(largest_model="large", thresholds={"low": .8, "medium": .8, "high": .8}, trust_store=store)
    predictions = {"graphrouter": pred("graphrouter", "large", {"small": .1, "large": .9})}
    decision = engine.decide("普通金融问题", ["small", "large"], predictions, estimates())
    engine.record_verified_feedback(decision, reward=.9, failed=False)
    row = store.get("graphrouter", decision.profile.task_type, decision.profile.risk_level)
    assert row["count"] == 1
    assert row["reward"] == .9
