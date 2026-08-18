"""Risk-aware mixture of heterogeneous LLM routers.

The module is deliberately independent from HTTP execution.  It turns router
predictions into an auditable decision that the existing server can execute.
Every stage is deterministic and side-effect free except ``RouterTrustStore``.
"""
from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalise(values: Mapping[str, float], models: Sequence[str]) -> Dict[str, float]:
    clean = {m: max(0.0, float(values.get(m, 0.0))) for m in models}
    total = sum(clean.values())
    if total <= 0:
        return {m: 1.0 / len(models) for m in models} if models else {}
    return {m: value / total for m, value in clean.items()}


@dataclass(frozen=True)
class TaskRiskProfile:
    task_type: str
    risk_level: str
    risk_score: float
    complexity: float
    requires_math: bool
    requires_code: bool
    requires_long_context: bool
    likely_ood: bool
    query_length: int
    budget_usd: Optional[float] = None
    latency_sla_ms: Optional[int] = None


class TaskRiskProfiler:
    """Transparent baseline profiler; replaceable by a trained classifier."""

    HIGH_RISK = ("审计", "合规", "监管", "投资建议", "交易建议", "估值", "反洗钱", "税务", "法律")
    MATH = ("计算", "收益率", "利率", "var", "波动率", "回撤", "估值", "概率", "公式")
    CODE = ("代码", "python", "sql", "程序", "函数", "debug")
    LONG = ("报告", "年报", "招股书", "全文", "长文档", "合同")

    def profile(
        self, query: str, *, risk_level: Optional[str] = None,
        budget_usd: Optional[float] = None, latency_sla_ms: Optional[int] = None,
    ) -> TaskRiskProfile:
        text = (query or "").strip().lower()
        math = any(token in text for token in self.MATH) or bool(re.search(r"\d+[.%]?", text))
        code = any(token in text for token in self.CODE)
        long_context = any(token in text for token in self.LONG) or len(text) > 1800
        high = any(token in text for token in self.HIGH_RISK)
        requested = (risk_level or "").lower()
        risk = requested if requested in {"low", "medium", "high"} else ("high" if high else "medium" if math else "low")
        risk_score = {"low": 0.2, "medium": 0.55, "high": 0.9}[risk]
        signals = sum((math, code, long_context, len(text) > 500))
        complexity = _clamp(0.2 + 0.18 * signals + min(len(text), 1200) / 2400)
        if code:
            task_type = "code"
        elif math:
            task_type = "financial_reasoning"
        elif long_context:
            task_type = "long_document"
        else:
            task_type = "financial_qa"
        return TaskRiskProfile(
            task_type=task_type, risk_level=risk, risk_score=risk_score,
            complexity=round(complexity, 4), requires_math=math, requires_code=code,
            requires_long_context=long_context, likely_ood=False,
            query_length=len(text), budget_usd=budget_usd, latency_sla_ms=latency_sla_ms,
        )


@dataclass
class RouterPrediction:
    router_name: str
    predicted_model: str
    model_scores: Dict[str, float]
    confidence: float
    uncertainty: float
    ood_score: float = 0.0
    evidence_count: int = 0
    available: bool = True
    error: Optional[str] = None

    @classmethod
    def unavailable(cls, router_name: str, error: str) -> "RouterPrediction":
        return cls(router_name, "", {}, 0.0, 1.0, 1.0, 0, False, error)


@dataclass(frozen=True)
class RouterPerformance:
    expected_utility: float
    failure_probability: float
    expected_regret: float
    risk_upper_bound: float


@dataclass(frozen=True)
class ModelEstimate:
    quality_lcb: float = 0.5
    reliability_lcb: float = 0.8
    cost_ucb: float = 0.0
    latency_ucb_ms: float = 0.0


@dataclass
class EnsembleDecision:
    selected_model: str
    profile: TaskRiskProfile
    predictions: Dict[str, RouterPrediction]
    performances: Dict[str, RouterPerformance]
    eligible_routers: list[str]
    safe_routers: list[str]
    safe_models: list[str]
    router_weights: Dict[str, float]
    fused_model_scores: Dict[str, float]
    disagreement: float
    fallback: Optional[str] = None
    manual_review_required: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RouterApplicabilityGate:
    """Remove unavailable or clearly unsupported experts before fusion."""

    def eligible(self, profile: TaskRiskProfile, predictions: Mapping[str, RouterPrediction]) -> list[str]:
        output = []
        for name, prediction in predictions.items():
            if not prediction.available or not prediction.predicted_model:
                continue
            if name == "knnrouter" and prediction.evidence_count == 0 and prediction.confidence < 0.35:
                continue
            if prediction.ood_score > (0.65 if profile.risk_level == "high" else 0.85):
                continue
            output.append(name)
        return output


class RouterPerformancePredictor:
    """Cold-start performance estimate, optionally corrected by verified trust."""

    def predict(
        self, profile: TaskRiskProfile, prediction: RouterPrediction,
        trust: Optional[Mapping[str, float]] = None,
    ) -> RouterPerformance:
        history_reward = float((trust or {}).get("reward", 0.5))
        history_failure = float((trust or {}).get("failure_rate", 0.5))
        support = min(1.0, float((trust or {}).get("count", 0.0)) / 20.0)
        confidence = _clamp(prediction.confidence)
        uncertainty = _clamp(prediction.uncertainty)
        utility = _clamp((1 - support) * (0.55 * confidence + 0.45 * (1 - uncertainty)) + support * history_reward)
        failure = _clamp((1 - support) * (0.55 * uncertainty + 0.25 * prediction.ood_score + 0.20 * (1 - confidence)) + support * history_failure)
        regret = _clamp(1.0 - utility)
        # Conservative finite-sample margin; calibrated quantiles can override it.
        margin = 0.08 + 0.10 * profile.risk_score + 0.08 / math.sqrt(max(1, prediction.evidence_count))
        return RouterPerformance(utility, failure, regret, _clamp(failure + margin))


class RiskConditionalConformalGate:
    """Risk-stratified upper-risk gate with optional calibrated thresholds."""

    def __init__(self, thresholds: Optional[Mapping[str, float]] = None):
        self.thresholds = dict(thresholds or {"low": 0.45, "medium": 0.32, "high": 0.22})

    def safe(self, profile: TaskRiskProfile, performances: Mapping[str, RouterPerformance], eligible: Iterable[str]) -> list[str]:
        limit = float(self.thresholds[profile.risk_level])
        return [name for name in eligible if performances[name].risk_upper_bound <= limit]


def top1_disagreement(predictions: Mapping[str, RouterPrediction], routers: Sequence[str]) -> float:
    if len(routers) < 2:
        return 0.0
    counts: Dict[str, int] = {}
    for name in routers:
        model = predictions[name].predicted_model
        counts[model] = counts.get(model, 0) + 1
    return round(1.0 - max(counts.values()) / len(routers), 4)


class DynamicRouterFusion:
    def fuse(
        self, models: Sequence[str], predictions: Mapping[str, RouterPrediction],
        performances: Mapping[str, RouterPerformance], safe_routers: Sequence[str],
    ) -> tuple[Dict[str, float], Dict[str, float]]:
        if not safe_routers:
            return {}, {}
        raw_weights = {
            name: math.exp(2.0 * performances[name].expected_utility
                           - performances[name].expected_regret
                           - 2.0 * performances[name].failure_probability)
            for name in safe_routers
        }
        weight_sum = sum(raw_weights.values())
        weights = {name: value / weight_sum for name, value in raw_weights.items()}
        fused = {model: 0.0 for model in models}
        for name in safe_routers:
            scores = _normalise(predictions[name].model_scores, models)
            for model in models:
                fused[model] += weights[name] * scores[model]
        return weights, _normalise(fused, models)


class ModelSafetyFilter:
    LIMITS = {
        "low": (0.45, 0.70),
        "medium": (0.60, 0.82),
        "high": (0.75, 0.92),
    }

    def filter(self, profile: TaskRiskProfile, estimates: Mapping[str, ModelEstimate]) -> list[str]:
        min_quality, min_reliability = self.LIMITS[profile.risk_level]
        output = []
        for model, estimate in estimates.items():
            if estimate.quality_lcb < min_quality or estimate.reliability_lcb < min_reliability:
                continue
            if profile.budget_usd is not None and estimate.cost_ucb > profile.budget_usd:
                continue
            if profile.latency_sla_ms is not None and estimate.latency_ucb_ms > profile.latency_sla_ms:
                continue
            output.append(model)
        return output


class NonCompensatoryModelSelector:
    """Safety is hard; fused fit breaks reliability/quality/cost ties."""

    def select(
        self, safe_models: Sequence[str], fused: Mapping[str, float],
        estimates: Mapping[str, ModelEstimate],
    ) -> Optional[str]:
        if not safe_models:
            return None
        return max(safe_models, key=lambda model: (
            float(fused.get(model, 0.0)), estimates[model].reliability_lcb,
            estimates[model].quality_lcb, -estimates[model].cost_ucb,
            -estimates[model].latency_ucb_ms, model,
        ))


class RouterTrustStore:
    """Small persistent store for verified per-router rewards."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._rows: Dict[str, Dict[str, float]] = {}
        if self.path.exists():
            try:
                self._rows = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._rows = {}

    def get(self, router: str, task_type: str, risk_level: str) -> Dict[str, float]:
        return dict(self._rows.get(f"{router}|{task_type}|{risk_level}", {}))

    def update(self, router: str, task_type: str, risk_level: str, *, reward: float, failed: bool) -> None:
        key = f"{router}|{task_type}|{risk_level}"
        with self._lock:
            row = self._rows.setdefault(key, {"count": 0.0, "reward": 0.5, "failure_rate": 0.5})
            count = row["count"] + 1.0
            row["reward"] += (_clamp(reward) - row["reward"]) / count
            row["failure_rate"] += ((1.0 if failed else 0.0) - row["failure_rate"]) / count
            row["count"] = count
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class FinRoME:
    """End-to-end decision engine for steps 1--9 and escalation intent."""

    def __init__(
        self, *, largest_model: str, thresholds: Optional[Mapping[str, float]] = None,
        trust_store: Optional[RouterTrustStore] = None,
    ):
        self.largest_model = largest_model
        self.profiler = TaskRiskProfiler()
        self.applicability = RouterApplicabilityGate()
        self.performance = RouterPerformancePredictor()
        self.conformal = RiskConditionalConformalGate(thresholds)
        self.fusion = DynamicRouterFusion()
        self.safety = ModelSafetyFilter()
        self.selector = NonCompensatoryModelSelector()
        self.trust_store = trust_store

    def decide(
        self, query: str, models: Sequence[str], predictions: Mapping[str, RouterPrediction],
        model_estimates: Mapping[str, ModelEstimate], *, risk_level: Optional[str] = None,
        budget_usd: Optional[float] = None, latency_sla_ms: Optional[int] = None,
    ) -> EnsembleDecision:
        profile = self.profiler.profile(query, risk_level=risk_level, budget_usd=budget_usd, latency_sla_ms=latency_sla_ms)
        eligible = self.applicability.eligible(profile, predictions)
        performances = {}
        for name, prediction in predictions.items():
            trust = self.trust_store.get(name, profile.task_type, profile.risk_level) if self.trust_store else None
            performances[name] = self.performance.predict(profile, prediction, trust)
        safe_routers = self.conformal.safe(profile, performances, eligible)
        weights, fused = self.fusion.fuse(models, predictions, performances, safe_routers)
        safe_models = self.safety.filter(profile, model_estimates)
        selected = self.selector.select(safe_models, fused, model_estimates)
        disagreement = top1_disagreement(predictions, safe_routers)
        reasons: list[str] = []
        fallback = None
        manual = False
        if not safe_routers:
            selected, fallback = self.largest_model, "no_safe_router"
            reasons.append("No router passed the risk-conditional gate")
        elif selected is None:
            selected, fallback = self.largest_model, "no_safe_model"
            reasons.append("No model passed quality/reliability/SLA constraints")
        elif profile.risk_level == "high" and disagreement > 0:
            selected, fallback, manual = self.largest_model, "high_risk_disagreement", True
            reasons.append("High-risk router disagreement requires verification")
        return EnsembleDecision(
            selected, profile, dict(predictions), performances, eligible, safe_routers,
            safe_models, weights, fused, disagreement, fallback, manual, reasons,
        )

    def record_verified_feedback(self, decision: EnsembleDecision, *, reward: float, failed: bool) -> None:
        if not self.trust_store:
            return
        for name in decision.safe_routers:
            recommended = decision.predictions[name].predicted_model
            router_failed = failed or recommended != decision.selected_model
            self.trust_store.update(name, decision.profile.task_type, decision.profile.risk_level,
                                    reward=reward if not router_failed else min(reward, 0.35), failed=router_failed)

