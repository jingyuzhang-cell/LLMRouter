from llmrouter.solver import (
    DAGValidationError,
    IncrementalDAGSolver,
    NodeSpec,
    SQLiteNodeStore,
)


def test_reuses_nodes_from_any_previous_round_and_invalidates_downstream(tmp_path):
    calls = {"fetch": 0, "analyze": 0, "answer": 0}

    def fetch(inputs, dependencies):
        calls["fetch"] += 1
        return {"facts": [inputs["topic"], "stable"]}

    def analyze(inputs, dependencies):
        calls["analyze"] += 1
        source = next(iter(dependencies.values()))
        return {
            "facts": source["facts"],
            "budget": inputs["budget"],
        }

    def answer(inputs, dependencies):
        calls["answer"] += 1
        analysis = next(iter(dependencies.values()))
        return f"{analysis['budget']}:{inputs['format']}"

    store = SQLiteNodeStore(tmp_path / "solver.sqlite3")
    solver = IncrementalDAGSolver(
        {"fetch": fetch, "analyze": analyze, "answer": answer}, store
    )

    first = solver.run(
        "conversation-1",
        "制定方案",
        [
            NodeSpec("source", "research/topic", "fetch", {"topic": "DAG"}),
            NodeSpec(
                "analysis",
                "analysis/budget",
                "analyze",
                {"budget": 100},
                ("source",),
            ),
            NodeSpec(
                "answer",
                "answer/render",
                "answer",
                {"format": "short"},
                ("analysis",),
            ),
        ],
    )
    assert [node.status for node in first.nodes] == ["NEW", "NEW", "NEW"]

    second = solver.run(
        "conversation-1",
        "预算改为 80",
        [
            NodeSpec("source2", "research/topic", "fetch", {"topic": "DAG"}),
            NodeSpec(
                "analysis2",
                "analysis/budget",
                "analyze",
                {"budget": 80},
                ("source2",),
            ),
            NodeSpec(
                "answer2",
                "answer/render",
                "answer",
                {"format": "short"},
                ("analysis2",),
            ),
        ],
    )
    assert [node.status for node in second.nodes] == [
        "REUSE",
        "RECOMPUTE",
        "RECOMPUTE",
    ]

    # Round three returns to the original constraint. It reuses round one,
    # proving lookup is over the entire session rather than only the last turn.
    third = solver.run(
        "conversation-1",
        "还是使用最初预算，但输出详细版",
        [
            NodeSpec("s", "research/topic", "fetch", {"topic": "DAG"}),
            NodeSpec(
                "a", "analysis/budget", "analyze", {"budget": 100}, ("s",)
            ),
            NodeSpec(
                "final",
                "answer/render",
                "answer",
                {"format": "long"},
                ("a",),
            ),
        ],
    )
    assert [node.status for node in third.nodes] == [
        "REUSE",
        "REUSE",
        "RECOMPUTE",
    ]
    assert third.nodes[1].reused_from_round == 1
    assert calls == {"fetch": 1, "analyze": 2, "answer": 3}
    assert len({row["round_number"] for row in store.history("conversation-1")}) == 3


def test_version_and_cacheable_flags_force_recomputation():
    calls = {"count": 0}

    def execute(inputs, dependencies):
        calls["count"] += 1
        return calls["count"]

    solver = IncrementalDAGSolver({"execute": execute})
    base = NodeSpec("n", "operation", "execute")
    assert solver.run("s", "one", [base]).nodes[0].status == "NEW"
    assert solver.run("s", "two", [base]).nodes[0].status == "REUSE"

    changed = NodeSpec(
        "n", "operation", "execute", implementation_version="2"
    )
    assert solver.run("s", "three", [changed]).nodes[0].status == "RECOMPUTE"
    uncached = NodeSpec("n", "operation", "execute", cacheable=False)
    assert solver.run("s", "four", [uncached]).nodes[0].status == "RECOMPUTE"


def test_rejects_missing_dependencies_and_cycles():
    solver = IncrementalDAGSolver({})

    try:
        solver.run("s", "missing", [NodeSpec("a", "a", "x", depends_on=("b",))])
    except DAGValidationError as error:
        assert "missing dependencies" in str(error)
    else:
        raise AssertionError("missing dependency was accepted")

    cyclic = [
        NodeSpec("a", "a", "x", depends_on=("b",)),
        NodeSpec("b", "b", "x", depends_on=("a",)),
    ]
    try:
        solver.run("s", "cycle", cyclic)
    except DAGValidationError as error:
        assert "Cycle detected" in str(error)
    else:
        raise AssertionError("cycle was accepted")
