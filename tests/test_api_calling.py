from types import SimpleNamespace

import pytest

from llmrouter.utils import api_calling


@pytest.fixture
def captured_completion(monkeypatch):
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="4"))],
            usage=SimpleNamespace(
                total_tokens=12,
                prompt_tokens=10,
                completion_tokens=2,
            ),
        )

    monkeypatch.setattr(api_calling, "completion", fake_completion)
    return calls


def make_request(**overrides):
    request = {
        "api_endpoint": "https://api.example.test/v1",
        "query": "Question: What is 2+2?",
        "model_name": "test-model",
        "api_name": "provider/test-model",
    }
    request.update(overrides)
    return request


def test_call_api_sends_system_message_before_user(captured_completion):
    result = api_calling.call_api(
        make_request(system_prompt="Answer step by step."),
        api_keys_env='["test-key"]',
    )

    assert captured_completion[0]["messages"] == [
        {"role": "system", "content": "Answer step by step."},
        {"role": "user", "content": "Question: What is 2+2?"},
    ]
    assert result["response"] == "4"
    assert result["prompt_tokens"] == 10


def test_call_api_omits_empty_system_message(captured_completion):
    api_calling.call_api(make_request(), api_keys_env='["test-key"]')

    assert captured_completion[0]["messages"] == [
        {"role": "user", "content": "Question: What is 2+2?"}
    ]
