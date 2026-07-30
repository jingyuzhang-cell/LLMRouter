from fastapi.testclient import TestClient

from llmrouter.serve.config import ServeConfig
from llmrouter.serve.server import create_app


def test_solver_round_api_reuses_across_multiple_rounds(tmp_path):
    calls = {"value": 0}

    def compute(inputs, dependencies):
        calls["value"] += 1
        return {"value": inputs["value"]}

    app = create_app(
        ServeConfig(),
        solver_executors={"compute": compute},
        solver_store_path=str(tmp_path / "api-solver.sqlite3"),
    )
    client = TestClient(app)

    def execute(value):
        return client.post(
            "/v1/solver/round",
            json={
                "session_id": "api-session",
                "question": f"value={value}",
                "nodes": [
                    {
                        "id": f"node-{value}",
                        "semantic_key": "demo/value",
                        "executor": "compute",
                        "inputs": {"value": value},
                    }
                ],
            },
        )

    first = execute(1)
    second = execute(2)
    third = execute(1)

    assert first.status_code == 200
    assert first.json()["nodes"][0]["status"] == "NEW"
    assert second.json()["nodes"][0]["status"] == "RECOMPUTE"
    assert third.json()["nodes"][0]["status"] == "REUSE"
    assert third.json()["nodes"][0]["reused_from_round"] == 1
    assert calls["value"] == 2

    history = client.get("/v1/solver/sessions/api-session/history")
    assert history.status_code == 200
    assert len(history.json()["history"]) == 3


def test_solver_api_requires_registered_executors():
    client = TestClient(create_app(ServeConfig()))
    response = client.post(
        "/v1/solver/round",
        json={"session_id": "s", "question": "q", "nodes": []},
    )
    assert response.status_code == 503
