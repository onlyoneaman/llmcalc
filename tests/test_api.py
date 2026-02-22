from dataclasses import dataclass
from decimal import Decimal

import pytest

import llmprice.api as api
from llmprice.models import ModelPricing


async def _fake_pricing_table(cache_timeout: int = 86400):
    _ = cache_timeout
    return {
        "gpt-4o-mini": ModelPricing(
            model="gpt-4o-mini",
            input_cost_per_token=Decimal("0.000001"),
            output_cost_per_token=Decimal("0.000002"),
            currency="USD",
        )
    }


@pytest.mark.asyncio
async def test_get_model_costs_found(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = await api.get_model_costs("openai:gpt-4o-mini")
    assert result is not None
    assert result.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_calculate_token_cost(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = await api.calculate_token_cost("gpt-4o-mini", input_tokens=1000, output_tokens=500)

    assert result is not None
    assert result.input_cost == Decimal("0.001000")
    assert result.output_cost == Decimal("0.001000")
    assert result.total_cost == Decimal("0.002000")


@pytest.mark.asyncio
async def test_calculate_token_cost_unknown_model(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = await api.calculate_token_cost("unknown", input_tokens=1, output_tokens=1)
    assert result is None


@pytest.mark.asyncio
async def test_calculate_usage_cost_dict(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = await api.calculate_usage_cost(
        "gpt-4o-mini",
        usage={"prompt_tokens": 1000, "completion_tokens": 1000},
    )
    assert result is not None
    assert result.total_cost == Decimal("0.003000")


@dataclass
class UsageObj:
    input_tokens: int
    output_tokens: int


@pytest.mark.asyncio
async def test_calculate_usage_cost_object(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    result = await api.calculate_usage_cost("gpt-4o-mini", usage=UsageObj(100, 100))
    assert result is not None
    assert result.total_cost == Decimal("0.000300")


@pytest.mark.asyncio
async def test_calculate_token_cost_negative_tokens(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    with pytest.raises(ValueError):
        await api.calculate_token_cost("gpt-4o-mini", input_tokens=-1, output_tokens=1)


@pytest.mark.asyncio
async def test_get_model_costs_uses_env_cache_timeout(monkeypatch) -> None:
    captured = {"cache_timeout": None}

    async def _capture(cache_timeout: int = 0):
        captured["cache_timeout"] = cache_timeout
        return await _fake_pricing_table(cache_timeout=cache_timeout)

    monkeypatch.setattr(api, "get_pricing_table", _capture)
    monkeypatch.setenv("LLMPRICE_CACHE_TIMEOUT", "1800")

    await api.get_model_costs("gpt-4o-mini")
    assert captured["cache_timeout"] == 1800


@pytest.mark.asyncio
async def test_get_model_costs_invalid_env_cache_timeout_falls_back(monkeypatch) -> None:
    captured = {"cache_timeout": None}

    async def _capture(cache_timeout: int = 0):
        captured["cache_timeout"] = cache_timeout
        return await _fake_pricing_table(cache_timeout=cache_timeout)

    monkeypatch.setattr(api, "get_pricing_table", _capture)
    monkeypatch.setenv("LLMPRICE_CACHE_TIMEOUT", "bad-value")

    await api.get_model_costs("gpt-4o-mini")
    assert captured["cache_timeout"] == api.DEFAULT_CACHE_TIMEOUT


@pytest.mark.asyncio
async def test_get_model_costs_rejects_non_positive_cache_timeout(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    with pytest.raises(ValueError):
        await api.get_model_costs("gpt-4o-mini", cache_timeout=0)


def test_clear_cache_calls_cache(monkeypatch) -> None:
    called = {"value": False}

    def _clear() -> None:
        called["value"] = True

    monkeypatch.setattr(api, "clear_cache_file", _clear)
    api.clear_cache()
    assert called["value"] is True
