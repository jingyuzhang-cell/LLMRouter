"""Small dependency-free compatibility layer for legacy subtask routing modules.

This module has no provider client and cannot make model or network calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Protocol


JSONValue = Any


@dataclass(frozen=True)
class SubtaskNode:
    node_id: str
    kind: str
    prompt: str
    depends_on: tuple[str, ...] = ()
    observable_features: Mapping[str, JSONValue] = field(default_factory=dict)
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id or not self.kind or not self.prompt:
            raise ValueError("node_id, kind, and prompt must be non-empty")
        if self.node_id in self.depends_on:
            raise ValueError("a node cannot depend on itself")


@dataclass(frozen=True)
class RouteRequest:
    task_id: str
    node: SubtaskNode
    available_models: tuple[str, ...]
    upstream_outputs: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must be non-empty")
        if not self.available_models or len(set(self.available_models)) != len(self.available_models):
            raise ValueError("available_models must be non-empty and unique")


@dataclass(frozen=True)
class RouteResult:
    model_id: str
    policy: str
    scores: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)


class Router(Protocol):
    def route(self, request: RouteRequest) -> RouteResult: ...


class MockRouter:
    """Frozen deterministic router for plumbing tests, never a learned router."""

    def __init__(self, default_model: str, by_kind: Mapping[str, str] | None = None) -> None:
        self.default_model = default_model
        self.by_kind = dict(by_kind or {})

    def route(self, request: RouteRequest) -> RouteResult:
        selected = self.by_kind.get(request.node.kind, self.default_model)
        if selected not in request.available_models:
            raise ValueError(f"mock selection {selected!r} is not available")
        return RouteResult(selected, "mock_static_fixture", metadata={"offline_only": True})


class DAGExecutor:
    """Validate/plan a subtask DAG; execution is disabled unless explicitly enabled."""

    def __init__(
        self,
        router: Router,
        executors: Mapping[str, Callable[[SubtaskNode, RouteResult, Mapping[str, JSONValue]], JSONValue]] | None = None,
        *,
        allow_execution: bool = False,
    ) -> None:
        self.router = router
        self.executors = dict(executors or {})
        self.allow_execution = allow_execution

    @staticmethod
    def topological_order(nodes: Iterable[SubtaskNode]) -> tuple[SubtaskNode, ...]:
        nodes = tuple(nodes)
        by_id = {node.node_id: node for node in nodes}
        if len(by_id) != len(nodes):
            raise ValueError("node_id values must be unique")
        for node in nodes:
            missing = set(node.depends_on) - by_id.keys()
            if missing:
                raise ValueError(f"node {node.node_id!r} has missing dependencies: {sorted(missing)}")
        visiting, visited, ordered = set(), set(), []

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            if node_id in visiting:
                raise ValueError(f"cycle detected at {node_id!r}")
            visiting.add(node_id)
            for dependency in by_id[node_id].depends_on:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)
            ordered.append(by_id[node_id])

        for node in nodes:
            visit(node.node_id)
        return tuple(ordered)

    def plan(self, task_id: str, nodes: Iterable[SubtaskNode], available_models: Iterable[str]) -> tuple[dict[str, JSONValue], ...]:
        models = tuple(available_models)
        plan = []
        for node in self.topological_order(nodes):
            request = RouteRequest(task_id, node, models)
            result = self.router.route(request)
            plan.append({"node_id": node.node_id, "kind": node.kind, "depends_on": list(node.depends_on), "model_id": result.model_id, "policy": result.policy})
        return tuple(plan)

    def execute(self, task_id: str, nodes: Iterable[SubtaskNode], available_models: Iterable[str]) -> Mapping[str, JSONValue]:
        if not self.allow_execution:
            raise RuntimeError("DAG execution is frozen; use plan() during C10-prep")
        outputs: dict[str, JSONValue] = {}
        models = tuple(available_models)
        for node in self.topological_order(nodes):
            result = self.router.route(RouteRequest(task_id, node, models, {d: outputs[d] for d in node.depends_on}))
            executor = self.executors.get(node.kind)
            if executor is None:
                raise KeyError(f"no local executor for node kind {node.kind!r}")
            outputs[node.node_id] = executor(node, result, {d: outputs[d] for d in node.depends_on})
        return outputs
