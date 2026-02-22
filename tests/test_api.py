from dataclasses import dataclass
from decimal import Decimal

import pytest

import llmcalc
import llmcalc.api as api
from llmcalc.models import ModelPricing


async def _fake_pricing_table(cache_timeout: int = 86400):
    _ = cache_timeout
    return {
        "gpt-5.1": ModelPricing(
            model="gpt-5.1",
            input_cost_per_token=Decimal("0.000001"),
            output_cost_per_token=Decimal("0.000002"),
            currency="USD",
        )
    }


def test_model_found(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = api.model("openai:gpt-5.1")
    assert result is not None
    assert result.model == "gpt-5.1"


@pytest.mark.asyncio
async def test_model_async_found(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = await api.model_async("openai:gpt-5.1")
    assert result is not None
    assert result.model == "gpt-5.1"


def test_cost(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = api.cost("gpt-5.1", input_tokens=1000, output_tokens=500)

    assert result is not None
    assert result.input_cost == Decimal("0.001000")
    assert result.output_cost == Decimal("0.001000")
    assert result.total_cost == Decimal("0.002000")


@pytest.mark.asyncio
async def test_cost_async(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = await api.cost_async("gpt-5.1", input_tokens=1000, output_tokens=500)

    assert result is not None
    assert result.input_cost == Decimal("0.001000")
    assert result.output_cost == Decimal("0.001000")
    assert result.total_cost == Decimal("0.002000")


def test_cost_unknown_model(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = api.cost("unknown", input_tokens=1, output_tokens=1)
    assert result is None


def test_usage_dict(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = api.usage("gpt-5.1", usage={"prompt_tokens": 1000, "completion_tokens": 1000})
    assert result is not None
    assert result.total_cost == Decimal("0.003000")


@dataclass
class UsageObj:
    input_tokens: int
    output_tokens: int


def test_usage_object(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = api.usage("gpt-5.1", usage=UsageObj(100, 100))
    assert result is not None
    assert result.total_cost == Decimal("0.000300")


@pytest.mark.asyncio
async def test_usage_async(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = await api.usage_async(
        "gpt-5.1",
        usage={"prompt_tokens": 100, "completion_tokens": 100},
    )
    assert result is not None
    assert result.total_cost == Decimal("0.000300")


def test_cost_negative_tokens(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    with pytest.raises(ValueError):
        api.cost("gpt-5.1", input_tokens=-1, output_tokens=1)


def test_model_uses_env_cache_timeout(monkeypatch) -> None:
    captured = {"cache_timeout": None}

    async def _capture(cache_timeout: int = 0):
        captured["cache_timeout"] = cache_timeout
        return await _fake_pricing_table(cache_timeout=cache_timeout)

    monkeypatch.setattr(api, "get_pricing_table", _capture)
    monkeypatch.setenv("LLMCALC_CACHE_TIMEOUT", "1800")

    api.model("gpt-5.1")
    assert captured["cache_timeout"] == 1800


def test_model_invalid_env_cache_timeout_falls_back(monkeypatch) -> None:
    captured = {"cache_timeout": None}

    async def _capture(cache_timeout: int = 0):
        captured["cache_timeout"] = cache_timeout
        return await _fake_pricing_table(cache_timeout=cache_timeout)

    monkeypatch.setattr(api, "get_pricing_table", _capture)
    monkeypatch.setenv("LLMCALC_CACHE_TIMEOUT", "bad-value")

    api.model("gpt-5.1")
    assert captured["cache_timeout"] == api.DEFAULT_CACHE_TIMEOUT


def test_model_rejects_non_positive_cache_timeout(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    with pytest.raises(ValueError):
        api.model("gpt-5.1", cache_timeout=0)


@pytest.mark.asyncio
async def test_sync_api_rejects_running_event_loop(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    with pytest.raises(RuntimeError, match="event loop"):
        api.cost("gpt-5.1", input_tokens=1, output_tokens=1)


def test_clear_cache_calls_cache(monkeypatch) -> None:
    called = {"value": False}

    def _clear() -> None:
        called["value"] = True

    monkeypatch.setattr(api, "clear_cache_file", _clear)
    api.clear_cache()
    assert called["value"] is True


def test_package_default_cost_is_sync(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = llmcalc.cost("gpt-5.1", input_tokens=10, output_tokens=5)
    assert result is not None
    assert result.total_cost == Decimal("0.000020")


@pytest.mark.asyncio
async def test_package_async_alias(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = await llmcalc.cost_async("gpt-5.1", input_tokens=10, output_tokens=5)
    assert result is not None
    assert result.total_cost == Decimal("0.000020")
