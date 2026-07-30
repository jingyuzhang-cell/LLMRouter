"""Multi-turn DAG execution with node-level reuse.

The planner is intentionally outside this module: it may be an LLM, a rules
engine, or application code.  This module owns the deterministic part:
validation, fingerprinting, persistence, reuse, and incremental execution.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


JSONValue = Any
Executor = Callable[[Mapping[str, JSONValue], Mapping[str, JSONValue]], JSONValue]


class DAGValidationError(ValueError):
    """Raised when a plan contains missing dependencies, duplicates, or cycles."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NodeSpec:
    """A planned unit of work.

    ``id`` is local to one round. ``semantic_key`` is stable across rounds and
    describes the operation (for example ``web.search/company_profile``).
    """

    id: str
    semantic_key: str
    executor: str
    inputs: Mapping[str, JSONValue] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    implementation_version: str = "1"
    model_version: str = ""
    prompt_version: str = ""
    ttl_seconds: float | None = None
    cacheable: bool = True


@dataclass(frozen=True)
class NodeExecution:
    node_id: str
    semantic_key: str
    status: str
    output: JSONValue
    fingerprint: str
    reused_from_round: int | None = None


@dataclass(frozen=True)
class RoundResult:
    session_id: str
    round_number: int
    question: str
    nodes: tuple[NodeExecution, ...]

    @property
    def outputs(self) -> dict[str, JSONValue]:
        return {node.node_id: node.output for node in self.nodes}

    @property
    def reused_count(self) -> int:
        return sum(node.status == "REUSE" for node in self.nodes)


class SQLiteNodeStore:
    """SQLite persistence shared by every turn of a conversation."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS solver_rounds (
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                round_id TEXT NOT NULL UNIQUE,
                question TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (session_id, round_number)
            );
            CREATE TABLE IF NOT EXISTS solver_nodes (
                execution_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                node_id TEXT NOT NULL,
                semantic_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                output_json TEXT NOT NULL,
                output_digest TEXT NOT NULL,
                status TEXT NOT NULL,
                source_execution_id TEXT,
                created_at REAL NOT NULL,
                expires_at REAL,
                FOREIGN KEY (session_id, round_number)
                    REFERENCES solver_rounds(session_id, round_number)
            );
            CREATE INDEX IF NOT EXISTS idx_solver_reuse
                ON solver_nodes(session_id, fingerprint, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_solver_semantic
                ON solver_nodes(session_id, semantic_key, created_at DESC);
            """
        )
        self._connection.commit()

    def next_round(self, session_id: str) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(round_number), 0) + 1 AS value "
            "FROM solver_rounds WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row["value"])

    def begin_round(self, session_id: str, round_number: int, question: str) -> None:
        self._connection.execute(
            "INSERT INTO solver_rounds VALUES (?, ?, ?, ?, ?)",
            (session_id, round_number, uuid.uuid4().hex, question, time.time()),
        )
        self._connection.commit()

    def find_reusable(
        self, session_id: str, fingerprint: str, now: float
    ) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT * FROM solver_nodes
            WHERE session_id = ? AND fingerprint = ?
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY round_number DESC, created_at DESC
            LIMIT 1
            """,
            (session_id, fingerprint, now),
        ).fetchone()

    def has_semantic_history(self, session_id: str, semantic_key: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM solver_nodes WHERE session_id = ? "
            "AND semantic_key = ? LIMIT 1",
            (session_id, semantic_key),
        ).fetchone()
        return row is not None

    def save_node(
        self,
        *,
        session_id: str,
        round_number: int,
        spec: NodeSpec,
        fingerprint: str,
        output: JSONValue,
        status: str,
        source_execution_id: str | None = None,
    ) -> None:
        created_at = time.time()
        expires_at = (
            created_at + spec.ttl_seconds
            if spec.ttl_seconds is not None
            else None
        )
        self._connection.execute(
            """
            INSERT INTO solver_nodes (
                execution_id, session_id, round_number, node_id, semantic_key,
                fingerprint, output_json, output_digest, status,
                source_execution_id, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                session_id,
                round_number,
                spec.id,
                spec.semantic_key,
                fingerprint,
                _canonical_json(output),
                _digest(output),
                status,
                source_execution_id,
                created_at,
                expires_at,
            ),
        )
        self._connection.commit()

    def history(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT r.round_number, r.question, n.node_id, n.semantic_key,
                   n.status, n.source_execution_id, n.created_at
            FROM solver_rounds r
            LEFT JOIN solver_nodes n
              ON r.session_id = n.session_id
             AND r.round_number = n.round_number
            WHERE r.session_id = ?
            ORDER BY r.round_number, n.created_at
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._connection.close()


class IncrementalDAGSolver:
    """Execute every turn against all valid node results in session history."""

    def __init__(
        self,
        executors: Mapping[str, Executor],
        store: SQLiteNodeStore | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.executors = dict(executors)
        self.store = store or SQLiteNodeStore()
        self.clock = clock

    def run(
        self, session_id: str, question: str, nodes: Iterable[NodeSpec]
    ) -> RoundResult:
        ordered = self._topological_order(tuple(nodes))
        round_number = self.store.next_round(session_id)
        self.store.begin_round(session_id, round_number, question)
        outputs: dict[str, JSONValue] = {}
        output_digests: dict[str, str] = {}
        executions: list[NodeExecution] = []

        for spec in ordered:
            dependency_digests = [
                {
                    "semantic_key": next(
                        node.semantic_key for node in ordered
                        if node.id == dependency
                    ),
                    "output_digest": output_digests[dependency],
                }
                for dependency in spec.depends_on
            ]
            fingerprint = _digest(
                {
                    "semantic_key": spec.semantic_key,
                    "executor": spec.executor,
                    "inputs": spec.inputs,
                    "dependencies": dependency_digests,
                    "implementation_version": spec.implementation_version,
                    "model_version": spec.model_version,
                    "prompt_version": spec.prompt_version,
                }
            )
            cached = (
                self.store.find_reusable(session_id, fingerprint, self.clock())
                if spec.cacheable
                else None
            )
            if cached is not None:
                output = json.loads(cached["output_json"])
                status = "REUSE"
                reused_from_round = int(cached["round_number"])
                source_execution_id = str(cached["execution_id"])
            else:
                executor = self.executors.get(spec.executor)
                if executor is None:
                    raise KeyError(f"Unknown executor: {spec.executor!r}")
                dependency_outputs = {
                    dependency: outputs[dependency]
                    for dependency in spec.depends_on
                }
                output = executor(dict(spec.inputs), dependency_outputs)
                if inspect.isawaitable(output):
                    raise TypeError(
                        "Async executor returned an awaitable; use a synchronous "
                        "adapter with IncrementalDAGSolver"
                    )
                status = (
                    "RECOMPUTE"
                    if self.store.has_semantic_history(
                        session_id, spec.semantic_key
                    )
                    else "NEW"
                )
                reused_from_round = None
                source_execution_id = None

            outputs[spec.id] = output
            output_digests[spec.id] = _digest(output)
            self.store.save_node(
                session_id=session_id,
                round_number=round_number,
                spec=spec,
                fingerprint=fingerprint,
                output=output,
                status=status,
                source_execution_id=source_execution_id,
            )
            executions.append(
                NodeExecution(
                    node_id=spec.id,
                    semantic_key=spec.semantic_key,
                    status=status,
                    output=output,
                    fingerprint=fingerprint,
                    reused_from_round=reused_from_round,
                )
            )

        return RoundResult(
            session_id=session_id,
            round_number=round_number,
            question=question,
            nodes=tuple(executions),
        )

    @staticmethod
    def _topological_order(nodes: tuple[NodeSpec, ...]) -> tuple[NodeSpec, ...]:
        by_id = {node.id: node for node in nodes}
        if len(by_id) != len(nodes):
            raise DAGValidationError("Node ids must be unique within a round")

        for node in nodes:
            missing = set(node.depends_on) - by_id.keys()
            if missing:
                raise DAGValidationError(
                    f"Node {node.id!r} has missing dependencies: {sorted(missing)}"
                )

        visiting: set[str] = set()
        visited: set[str] = set()
        ordered: list[NodeSpec] = []

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            if node_id in visiting:
                raise DAGValidationError(f"Cycle detected at node {node_id!r}")
            visiting.add(node_id)
            for dependency in by_id[node_id].depends_on:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)
            ordered.append(by_id[node_id])

        for node in nodes:
            visit(node.id)
        return tuple(ordered)
