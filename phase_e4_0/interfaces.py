"""Frozen E4.0 DAG and pre-route state contracts; no provider client."""
from dataclasses import dataclass, field
from typing import Any, Mapping

@dataclass(frozen=True)
class RuntimeState:
    upstream_provider_success: bool | None = None
    upstream_format_valid: bool | None = None
    upstream_output_length: int = 0
    upstream_evidence_count: int = 0
    upstream_extraction_field_count: int = 0
    upstream_confidence: float | None = None
    upstream_latency_ms: float = 0.0
    cumulative_cost_usd: float = 0.0
    remaining_budget_usd: float | None = None
    retry_count: int = 0

    def __post_init__(self):
        if min(self.upstream_output_length,self.upstream_evidence_count,self.upstream_extraction_field_count,self.retry_count)<0:
            raise ValueError("state counts must be nonnegative")
        if self.upstream_latency_ms<0 or self.cumulative_cost_usd<0:
            raise ValueError("state cost/latency must be nonnegative")
        if self.upstream_confidence is not None and not 0<=self.upstream_confidence<=1:
            raise ValueError("confidence must be in [0,1]")

@dataclass(frozen=True)
class DAGNode:
    node_id: str
    node_type: str
    depends_on: tuple[str,...]
    prompt_template: str
    output_schema: Mapping[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class StateAwareRouteRequest:
    task_id: str
    node: DAGNode
    observable_task_features: Mapping[str,Any]
    state: RuntimeState
    available_models: tuple[str,...]

    def __post_init__(self):
        forbidden={'reference_answer','gold_answer','gold_evidence','judge_score','current_latency_ms','current_provider_success'}
        leaked=forbidden & set(self.observable_task_features)
        if leaked: raise ValueError(f"forbidden pre-route features: {sorted(leaked)}")
        if not self.available_models: raise ValueError("available_models must be nonempty")
