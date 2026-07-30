import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

import llmcalc
import llmcalc.api as api
from llmcalc.models import ModelPricing, RawModelPricing


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


def test_bool_token_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        api._get_usage_tokens({"prompt_tokens": True, "completion_tokens": False})


def test_camel_case_usage_keys_are_accepted() -> None:
    assert api._get_usage_tokens({"inputTokens": 10, "outputTokens": 5}) == (10, 5)
    assert api._get_usage_tokens({"promptTokens": 7, "completionTokens": 3}) == (7, 3)


def test_string_usage_explains_that_text_is_unsupported() -> None:
    with pytest.raises(ValueError, match="token counts, not text"):
        api._get_usage_tokens("hello world")


def test_messages_array_explains_that_text_is_unsupported() -> None:
    with pytest.raises(ValueError, match="token counts, not text"):
        api._get_usage_tokens([{"role": "user", "content": "hi"}])


def test_dict_with_messages_explains_that_text_is_unsupported() -> None:
    with pytest.raises(ValueError, match="token counts, not text"):
        api._get_usage_tokens({"messages": [{"role": "user", "content": "hi"}]})


def test_float_token_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        api._get_usage_tokens({"prompt_tokens": 1.5, "completion_tokens": 2})


def test_none_usage_is_rejected() -> None:
    with pytest.raises(ValueError):
        api._get_usage_tokens(None)


def test_empty_dict_is_rejected() -> None:
    with pytest.raises(ValueError):
        api._get_usage_tokens({})


def test_bool_rejected_by_cost(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    with pytest.raises(ValueError, match="must be an integer"):
        llmcalc.cost("gpt-5.1", input_tokens=True, output_tokens=5)


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "tiered_cases.json").read_text(encoding="utf-8")
)
ALL_TIER_CASES = [*FIXTURE["thresholds"], *FIXTURE["graduated"]]


def _stub_table(monkeypatch, pricing: dict) -> None:
    model_pricing = RawModelPricing.model_validate(pricing).to_model_pricing("test-model")

    async def _table(cache_timeout: int = 86400, **_kwargs):
        _ = cache_timeout
        return {"test-model": model_pricing}

    monkeypatch.setattr(api, "get_pricing_table", _table)


@pytest.mark.parametrize("case", ALL_TIER_CASES, ids=lambda c: c["name"])
async def test_cost_matches_fixture(monkeypatch, case: dict) -> None:
    _stub_table(monkeypatch, case["pricing"])

    result = await api.cost_async("test-model", case["input_tokens"], case["output_tokens"])

    assert result is not None
    assert str(result.input_cost) == case["expected"]["input_cost"]
    assert str(result.output_cost) == case["expected"]["output_cost"]
    assert str(result.total_cost) == case["expected"]["total_cost"]
    assert result.tier_applied == case["expected"]["tier_applied"]


async def test_total_is_computed_from_unrounded_legs(monkeypatch) -> None:
    # Each leg is 0.0000005, which alone rounds to 0.000001. Summed unrounded
    # the total is 0.000001, not the 0.000002 a double-round would produce.
    _stub_table(
        monkeypatch,
        {"input_cost_per_token": "0.0000005", "output_cost_per_token": "0.0000005"},
    )

    result = await api.cost_async("test-model", 1, 1)

    assert result is not None
    assert str(result.total_cost) == "0.000001"


async def test_usage_applies_tiers_like_cost(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {
            "input_cost_per_token": "0.000005",
            "output_cost_per_token": "0.00003",
            "input_cost_per_token_above_272k_tokens": "0.00001",
            "output_cost_per_token_above_272k_tokens": "0.000045",
        },
    )

    result = await api.usage_async(
        "test-model", {"prompt_tokens": 300000, "completion_tokens": 5000}
    )

    assert result is not None
    assert str(result.total_cost) == "3.225000"
    assert result.tier_applied == "above_272k_tokens"


async def test_unknown_model_returns_none(monkeypatch) -> None:
    async def _table(cache_timeout: int = 86400, **_kwargs):
        _ = cache_timeout
        return {}

    monkeypatch.setattr(api, "get_pricing_table", _table)
    assert await api.cost_async("test-model", 10, 5) is None
