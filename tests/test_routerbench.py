from openclaw_router.routerbench import build_routerbench


def test_routerbench_builds_pareto_and_significance():
    payload = {
        "task_set": [
            {"id": "t1", "type": "qa", "dataset": "demo"},
            {"id": "t2", "type": "code", "dataset": "demo"},
        ],
        "strategies": [
            {"id": "a", "name": "Router A", "category": "test", "summary": {"quality": 0.9, "cost": 0.2, "latency": 0.2, "reliability": 0.9, "utility": 0.85}},
            {"id": "b", "name": "Router B", "category": "test", "summary": {"quality": 0.7, "cost": 0.3, "latency": 0.3, "reliability": 0.7, "utility": 0.65}},
        ],
        "routerbench_rows": [
            {"strategy_id": "a", "task_id": "t1", "task_type": "qa", "score": 0.9, "metrics": {"quality": 0.9, "cost": 0.2, "latency": 0.2, "reliability": 0.9}},
            {"strategy_id": "a", "task_id": "t2", "task_type": "code", "score": 0.8, "metrics": {"quality": 0.8, "cost": 0.2, "latency": 0.2, "reliability": 0.9}},
            {"strategy_id": "b", "task_id": "t1", "task_type": "qa", "score": 0.6, "metrics": {"quality": 0.6, "cost": 0.3, "latency": 0.3, "reliability": 0.7}},
            {"strategy_id": "b", "task_id": "t2", "task_type": "code", "score": 0.5, "metrics": {"quality": 0.5, "cost": 0.3, "latency": 0.3, "reliability": 0.7}},
        ],
    }

    report = build_routerbench(payload)

    assert report["strategy_count"] == 2
    assert report["best_strategy"] == "Router A"
    assert report["significance"]
    assert report["significance"][0]["n"] == 2
    assert any(item["name"] == "Router A" for item in report["pareto_front"])
