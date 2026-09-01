import pytest

from c10_prep import DAGExecutor, MockRouter, RouteRequest, SubtaskNode


def test_mock_router_and_plan_are_deterministic_and_offline():
    nodes = [
        SubtaskNode("extract", "extract", "extract facts"),
        SubtaskNode("compute", "compute", "compute result", ("extract",)),
    ]
    router = MockRouter("small", {"compute": "large"})
    dag = DAGExecutor(router)
    assert [x["model_id"] for x in dag.plan("t1", nodes, ("small", "large"))] == ["small", "large"]
    with pytest.raises(RuntimeError, match="execution is frozen"):
        dag.execute("t1", nodes, ("small", "large"))


def test_contract_validation_and_cycle_detection():
    with pytest.raises(ValueError):
        RouteRequest("t", SubtaskNode("n", "k", "p"), ())
    cyclic = [SubtaskNode("a", "k", "a", ("b",)), SubtaskNode("b", "k", "b", ("a",))]
    with pytest.raises(ValueError, match="cycle"):
        DAGExecutor.topological_order(cyclic)
