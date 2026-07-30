from llmrouter.prompts import load_prompt_template
from llmrouter.utils import generate_task_query


def test_prompt_template_has_no_trailing_whitespace():
    assert load_prompt_template("task_gsm8k") == (
        "Answer the following math question step by step."
    )


def test_gsm8k_prompt_separates_system_and_user_messages():
    result = generate_task_query("gsm8k", {"query": "What is 2+2?"})

    assert result["system"] == "Answer the following math question step by step."
    assert result["user"] == "Question: What is 2+2?"

import pytest

from llmrouter.models.knnmultiroundrouter.router import KNNMultiRoundRouter
from llmrouter.models.llmmultiroundrouter.router import LLMMultiRoundRouter


@pytest.mark.parametrize("router_class", [KNNMultiRoundRouter, LLMMultiRoundRouter])
def test_multiround_batch_passes_separate_system_and_user_prompts(router_class):
    router = router_class.__new__(router_class)
    received = {}

    def fake_route_single(request):
        received.update(request)
        return {"response": "4", "success": True}

    router.route_single = fake_route_single
    result = router.route_batch([{"query": "What is 2+2?", "task_name": "gsm8k"}])

    assert received["query"] == "Question: What is 2+2?"
    assert received["system_prompt"] == "Answer the following math question step by step."
    assert result[0]["query"] == "What is 2+2?"


@pytest.mark.parametrize("router_class", [KNNMultiRoundRouter, LLMMultiRoundRouter])
def test_multiround_route_single_preserves_system_prompt(router_class, monkeypatch):
    router = router_class.__new__(router_class)
    calls = {}

    if router_class is KNNMultiRoundRouter:
        router._load_knn_model_if_needed = lambda: None
        router._decompose_query = lambda query: [query]
        router._route_sub_query = lambda query: "test-model"
    else:
        router._decompose_and_route = lambda query: [(query, "test-model")]

    def fake_execute(sub_query, model_name, system_prompt=None):
        calls["execute"] = system_prompt
        return {
            "response": "4",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "success": True,
        }

    def fake_aggregate(
        original_query, sub_queries, sub_responses, task_name=None, system_prompt=None
    ):
        calls["aggregate"] = system_prompt
        return "4"

    router._execute_sub_query = fake_execute
    router._aggregate_responses = fake_aggregate
    system_prompt = "Answer the following math question step by step."
    result = router.route_single(
        {"query": "Question: What is 2+2?", "system_prompt": system_prompt}
    )

    assert calls == {"execute": system_prompt, "aggregate": system_prompt}
    assert result["response"] == "4"
