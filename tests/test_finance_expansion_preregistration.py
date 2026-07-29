import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "run_logs" / "finance_expansion_preregistration"


def test_expansion_is_locked_and_has_no_answer_leakage():
    manifest = json.loads((OUT / "candidate_manifest.json").read_text())
    protocol = json.loads((OUT / "protocol.json").read_text())

    assert (manifest["base_tasks"], manifest["new_tasks"], manifest["combined_tasks"]) == (100, 40, 140)
    assert manifest["candidate_counts"] == {
        "FinQA": 10,
        "TAT-QA": 10,
        "ObliQA": 10,
        "FinReflectKG-EvalBench-derived": 10,
    }
    assert manifest["existing_four_model_answer_coverage"] == 0
    assert manifest["required_new_calls"] == {
        "answer_calls": 480,
        "minimum_judge_attempts_if_two_per_answer": 960,
        "api_execution_authorized": False,
    }
    assert protocol["frozen_before_answers"] is True
    assert protocol["split_counts"] == {"train": 84, "validation": 28, "test": 28}

    splits = protocol["split_task_ids"]
    split_sets = {name: set(ids) for name, ids in splits.items()}
    assert split_sets["train"].isdisjoint(split_sets["validation"])
    assert split_sets["train"].isdisjoint(split_sets["test"])
    assert split_sets["validation"].isdisjoint(split_sets["test"])
    assert len(set.union(*split_sets.values())) == 140
    assert set(manifest["candidate_ids"]).issubset(set.union(*split_sets.values()))
