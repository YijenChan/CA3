import pytest

from ca3.metered_api import BudgetExhausted, MeteredAPI


def test_budget_reserves_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    c = {
        "agent": {
            "model": "gpt-5.1",
            "reasoning_effort": "none",
            "max_completion_tokens": 700,
            "api_base": "https://api.openai.com/v1",
            "timeout_seconds": 1,
        },
        "budget": {
            "input_usd_per_million": 1.25,
            "cached_input_usd_per_million": 0.125,
            "output_usd_per_million": 10,
            "max_cost_usd": 0.001,
        },
    }
    client = MeteredAPI(c, tmp_path / "calls")
    with pytest.raises(BudgetExhausted):
        client.call([{"role": "user", "content": "test"}], "test")
    assert not client.records


def test_failed_request_reservation_survives(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    c = {
        "agent": {
            "model": "gpt-5.1",
            "reasoning_effort": "none",
            "max_completion_tokens": 700,
            "api_base": "https://api.openai.com/v1",
            "timeout_seconds": 1,
        },
        "budget": {
            "input_usd_per_million": 1.25,
            "cached_input_usd_per_million": 0.125,
            "output_usd_per_million": 10,
            "max_cost_usd": 4,
        },
    }

    def fail(*args, **kwargs):
        raise TimeoutError("uncertain transport failure")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    client = MeteredAPI(c, tmp_path / "calls")
    with pytest.raises(TimeoutError):
        client.call([{"role": "user", "content": "test"}], "test")
    assert MeteredAPI(c, tmp_path / "calls").reserved_or_spent > 0
