"""Feature contracts for fair request-only vs state-aware E4 comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


NODES = ("N1", "N2", "N3", "N4")
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo")
STATE_FIELDS = (
    "upstream_provider_success",
    "upstream_schema_valid",
    "upstream_evidence_count",
    "upstream_extraction_field_count",
    "upstream_confidence",
    "upstream_output_length",
    "upstream_latency_ms",
    "cumulative_cost_usd",
    "remaining_budget_usd",
    "retry_count",
)


def _number(value: Any, missing: float = -1.0) -> float:
    if value is None:
        return missing
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return missing


def _one_hot(value: str, vocabulary: tuple[str, ...]) -> list[float]:
    return [float(value == item) for item in vocabulary]


def flatten_request_features(features: dict[str, Any]) -> list[float]:
    """Deterministically flatten only numeric/bool observable request fields."""
    return [_number(features[name]) for name in sorted(features) if isinstance(features[name], (bool, int, float))]


def request_only_vector(record: dict[str, Any]) -> list[float]:
    return (
        flatten_request_features(record.get("request_features") or {})
        + _one_hot(record["node_id"], NODES)
        + _one_hot(record["selected_model"], MODELS)
    )


def state_vector(record: dict[str, Any]) -> list[float]:
    state = record.get("pre_action_state") or {}
    return request_only_vector(record) + [_number(state.get(name)) for name in STATE_FIELDS]


@dataclass(frozen=True)
class ProgressViews:
    coarse_regime: float
    structural_completion: float
    state_quality: float
    budget_headroom: float

    @property
    def score(self) -> float:
        return (
            0.35 * self.coarse_regime
            + 0.25 * self.structural_completion
            + 0.25 * self.state_quality
            + 0.15 * self.budget_headroom
        )


def progress_views(record: dict[str, Any]) -> ProgressViews:
    """Outcome-blind, pre-action ProgRouter-lite progress views in [0, 1]."""
    state = record.get("pre_action_state") or {}
    node_index = NODES.index(record["node_id"])
    if node_index == 0:
        coarse = 0.0
    elif state.get("upstream_provider_success") is False:
        coarse = 0.0
    elif state.get("upstream_schema_valid") is False:
        coarse = 0.25
    else:
        coarse = node_index / len(NODES)
    structural = node_index / len(NODES)
    confidence = _number(state.get("upstream_confidence"), missing=0.0)
    state_quality = max(0.0, min(1.0, confidence))
    remaining = _number(state.get("remaining_budget_usd"), missing=0.0)
    cumulative = _number(state.get("cumulative_cost_usd"), missing=0.0)
    total = remaining + cumulative
    budget = remaining / total if total > 0 else 0.0
    return ProgressViews(coarse, structural, state_quality, max(0.0, min(1.0, budget)))

