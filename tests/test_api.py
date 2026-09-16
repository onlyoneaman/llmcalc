import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import SimpleNamespace

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


def test_cost_uses_half_up_rounding_at_50_significant_digits(monkeypatch) -> None:
    rate = "0." + "1" * 49 + "25"

    async def _table(cache_timeout: int = 86400):
        _ = cache_timeout
        return {
            "precision-model": ModelPricing(
                model="precision-model",
                input_cost_per_token=Decimal(rate),
                output_cost_per_token=Decimal("0"),
            )
        }

    monkeypatch.setattr(api, "get_pricing_table", _table)
    result = api.cost("precision-model", input_tokens=1, output_tokens=0)
    assert result is not None
    assert result.input_cost == Decimal("0." + "1" * 49 + "3")


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


@pytest.mark.parametrize(
    "env_value",
    ["bad-value", "0", "-1", "1_800", "١٨٠٠", str(2**53)],
)
def test_model_invalid_env_cache_timeout_falls_back(monkeypatch, env_value: str) -> None:
    captured = {"cache_timeout": None}

    async def _capture(cache_timeout: int = 0):
        captured["cache_timeout"] = cache_timeout
        return await _fake_pricing_table(cache_timeout=cache_timeout)

    monkeypatch.setattr(api, "get_pricing_table", _capture)
    monkeypatch.setenv("LLMCALC_CACHE_TIMEOUT", env_value)

    api.model("gpt-5.1")
    assert captured["cache_timeout"] == api.DEFAULT_CACHE_TIMEOUT


@pytest.mark.parametrize("cache_timeout", [0, -1, 0.5, True, 2**53])
def test_model_rejects_invalid_cache_timeout(monkeypatch, cache_timeout: object) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    with pytest.raises(ValueError):
        api.model("gpt-5.1", cache_timeout=cache_timeout)  # type: ignore[arg-type]


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
    assert api._get_usage_tokens({"inputTokens": 10, "outputTokens": 5}) == (10, 5, 0, 0, 0)
    assert api._get_usage_tokens({"promptTokens": 7, "completionTokens": 3}) == (7, 3, 0, 0, 0)


def test_null_usage_aliases_do_not_hide_later_values() -> None:
    assert api._get_usage_tokens(
        {
            "input_tokens": None,
            "prompt_tokens": 10,
            "output_tokens": None,
            "completion_tokens": 5,
        }
    ) == (10, 5, 0, 0, 0)


@pytest.mark.parametrize(
    "usage",
    [
        {
            "promptTokenCount": 100,
            "candidatesTokenCount": 20,
            "cachedContentTokenCount": 80,
            "thoughtsTokenCount": 10,
        },
        {
            "prompt_token_count": 100,
            "candidates_token_count": 20,
            "cached_content_token_count": 80,
            "thoughts_token_count": 10,
        },
        {
            "prompt_token_count": 100,
            "response_token_count": 20,
            "cached_content_token_count": 80,
            "thoughts_token_count": 10,
        },
    ],
)
def test_gemini_usage_shape_is_normalized(usage: dict[str, int]) -> None:
    assert api._get_usage_tokens(usage) == (100, 30, 80, 0, 10)


def test_gemini_tool_use_tokens_can_be_a_prompt_subset() -> None:
    assert api._get_usage_tokens(
        {
            "promptTokenCount": 100,
            "candidatesTokenCount": 20,
            "thoughtsTokenCount": 10,
            "toolUsePromptTokenCount": 30,
            "totalTokenCount": 130,
        }
    ) == (100, 30, 0, 0, 10)


def test_gemini_tool_use_tokens_can_be_additive() -> None:
    assert api._get_usage_tokens(
        {
            "prompt_token_count": 100,
            "candidates_token_count": 20,
            "thoughts_token_count": 10,
            "tool_use_prompt_token_count": 30,
            "total_token_count": 160,
        }
    ) == (130, 30, 0, 0, 10)


def test_gemini_tool_use_tokens_require_consistent_total() -> None:
    usage = {
        "promptTokenCount": 100,
        "candidatesTokenCount": 20,
        "toolUsePromptTokenCount": 30,
    }
    with pytest.raises(ValueError, match="total_token_count is required"):
        api._get_usage_tokens(usage)

    with pytest.raises(ValueError, match="inconsistent"):
        api._get_usage_tokens({**usage, "totalTokenCount": 140})


def test_gemini_usage_rejects_negative_component() -> None:
    with pytest.raises(ValueError, match="candidates_token_count must be non-negative"):
        api._get_usage_tokens(
            {
                "promptTokenCount": 100,
                "candidatesTokenCount": -1,
                "thoughtsTokenCount": 1,
            }
        )


def test_bedrock_usage_cache_counts_are_additive() -> None:
    assert api._get_usage_tokens(
        {
            "inputTokens": 100,
            "outputTokens": 20,
            "cacheReadInputTokens": 50,
            "cacheWriteInputTokens": 30,
        }
    ) == (180, 20, 50, 30, 0)


@pytest.mark.parametrize(
    "usage",
    [
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_creation_input_tokens": 30,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 20,
                "ephemeral_1h_input_tokens": 10,
            },
        },
        {
            "inputTokens": 100,
            "outputTokens": 20,
            "cacheWriteInputTokens": 30,
            "cacheDetails": [
                {"ttl": "5m", "inputTokens": 20},
                {"ttl": "1h", "inputTokens": 10},
            ],
        },
    ],
)
def test_one_hour_cache_writes_are_normalized(usage: dict[str, object]) -> None:
    normalized = api._normalize_usage(usage)
    assert normalized.cache_creation_tokens == 30
    assert normalized.cache_creation_tokens_1h == 10


def test_cache_duration_details_must_match_aggregate() -> None:
    with pytest.raises(ValueError, match="must sum"):
        api._normalize_usage(
            {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_creation_input_tokens": 30,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 20,
                    "ephemeral_1h_input_tokens": 5,
                },
            }
        )


def test_gemini_media_and_cached_modalities_are_normalized() -> None:
    normalized = api._normalize_usage(
        {
            "promptTokenCount": 100,
            "responseTokenCount": 50,
            "cachedContentTokenCount": 20,
            "promptTokensDetails": [
                {"modality": "AUDIO", "tokenCount": 30},
                {"modality": "DOCUMENT", "tokenCount": 20},
                {"modality": "TEXT", "tokenCount": 50},
            ],
            "cacheTokensDetails": [
                {"modality": "AUDIO", "tokenCount": 10},
                {"modality": "DOCUMENT", "tokenCount": 5},
            ],
            "responseTokensDetails": [
                {"modality": "AUDIO", "tokenCount": 10},
                {"modality": "IMAGE", "tokenCount": 5},
            ],
        }
    )

    assert normalized.input_audio_tokens == 30
    assert normalized.input_image_tokens == 20
    assert normalized.cached_audio_tokens == 10
    assert normalized.cached_image_tokens == 5
    assert normalized.output_audio_tokens == 10
    assert normalized.output_image_tokens == 5


def test_query_and_xai_tool_usage_are_normalized() -> None:
    normalized = api._normalize_usage(
        {
            "inputTokens": 10,
            "outputTokens": 5,
            "searchUnits": 2,
            "serverSideToolUsageDetails": {"webSearchCalls": 3},
            "googleMapsGroundingRequests": 4,
        }
    )

    assert normalized.query_count == 2
    assert normalized.web_search_requests == 3
    assert normalized.maps_grounding_requests == 4


def test_service_tiers_are_normalized() -> None:
    assert api._normalize_usage(
        {"input_tokens": 100, "output_tokens": 20, "service_tier": "flex"}
    ).processing_mode == "flex"
    for service_tier in ("standard", "unspecified"):
        assert api._get_usage_tokens(
            {"input_tokens": 100, "output_tokens": 20, "service_tier": service_tier}
        ) == (100, 20, 0, 0, 0)


@pytest.mark.parametrize(
    "usage",
    [
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "input_tokens_details": {"audio_tokens": 10},
        },
        {
            "promptTokenCount": 100,
            "responseTokenCount": 20,
            "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": 10}],
        },
    ],
)
def test_non_text_token_details_are_normalized(usage: dict[str, object]) -> None:
    assert api._normalize_usage(usage).input_audio_tokens == 10


def test_non_text_sdk_detail_object_is_normalized() -> None:
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=20,
        prompt_tokens_details=SimpleNamespace(audio_tokens=10),
    )
    assert api._normalize_usage(usage).input_audio_tokens == 10


def test_openai_responses_cache_writes_are_a_subset() -> None:
    assert api._get_usage_tokens(
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "input_tokens_details": {"cached_tokens": 30, "cache_write_tokens": 20},
        }
    ) == (100, 20, 30, 20, 0)


def test_anthropic_thinking_tokens_are_reasoning() -> None:
    assert api._get_usage_tokens(
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "output_tokens_details": {"thinking_tokens": 10},
        }
    ) == (100, 20, 0, 0, 10)


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


def test_token_counts_above_javascript_safe_integer_are_rejected(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_pricing_table", _fake_pricing_table)
    with pytest.raises(ValueError, match=str(2**53 - 1)):
        api.cost("gpt-5.1", input_tokens=2**53, output_tokens=0)


def test_normalized_token_total_must_be_a_safe_integer() -> None:
    with pytest.raises(ValueError, match=str(2**53 - 1)):
        api._get_usage_tokens(
            {
                "inputTokens": 2**53 - 1,
                "outputTokens": 0,
                "cacheReadInputTokens": 1,
            }
        )


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "tiered_cases.json").read_text(encoding="utf-8")
)
DIMENSIONS_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "pricing_dimensions.json").read_text(
        encoding="utf-8"
    )
)
ALL_TIER_CASES = [*FIXTURE["thresholds"], *FIXTURE["request_tiers"]]


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")


def _stub_table(monkeypatch, pricing: dict) -> None:
    model_pricing = RawModelPricing.model_validate(pricing).to_model_pricing("test-model")

    async def _table(cache_timeout: int = 86400, **_kwargs):
        _ = cache_timeout
        return {"test-model": model_pricing}

    monkeypatch.setattr(api, "get_pricing_table", _table)


def test_gemini_usage_costs_cached_content_and_thoughts(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {
            "input_cost_per_token": "0.01",
            "output_cost_per_token": "0.02",
            "cache_read_input_token_cost": "0.001",
            "output_cost_per_reasoning_token": "0.03",
        },
    )

    result = api.usage(
        "test-model",
        {
            "promptTokenCount": 100,
            "candidatesTokenCount": 20,
            "cachedContentTokenCount": 80,
            "thoughtsTokenCount": 10,
        },
    )

    assert result is not None
    assert result.input_cost == Decimal("0.280000")
    assert result.output_cost == Decimal("0.700000")
    assert result.total_cost == Decimal("0.980000")


@pytest.mark.asyncio
async def test_input_only_model_accepts_zero_output(monkeypatch) -> None:
    _stub_table(monkeypatch, {"input_cost_per_token": "0.000001"})

    result = await api.cost_async("test-model", 1000, 0)

    assert result is not None
    assert result.total_cost == Decimal("0.001000")


@pytest.mark.parametrize("case", ALL_TIER_CASES, ids=lambda c: c["name"])
async def test_cost_matches_fixture(monkeypatch, case: dict) -> None:
    _stub_table(monkeypatch, case["pricing"])

    result = await api.cost_async("test-model", case["input_tokens"], case["output_tokens"])

    assert result is not None
    assert _money(result.input_cost) == case["expected"]["input_cost"]
    assert _money(result.output_cost) == case["expected"]["output_cost"]
    assert _money(result.total_cost) == case["expected"]["total_cost"]
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
    assert result.input_cost == Decimal("0.0000005")
    assert result.output_cost == Decimal("0.0000005")
    assert result.total_cost == Decimal("0.000001")
    assert result.input_cost + result.output_cost == result.total_cost


async def test_cost_uses_fifty_digit_decimal_context(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {"input_cost_per_token": "0.12345678901234567890123456789"},
    )

    result = await api.cost_async("test-model", 2**53 - 1, 0)

    assert result is not None
    assert result.total_cost == Decimal("1111999897984715.76533637057653252505775537899")


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
    assert result.total_cost == Decimal("3.225000")
    assert result.tier_applied == "above_272k_tokens"


async def test_reported_processing_mode_overrides_requested_mode(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {
            "input_cost_per_token": "0.01",
            "input_cost_per_token_priority": "0.02",
            "input_cost_per_token_flex": "0.005",
        },
    )

    result = await api.usage_async(
        "test-model",
        {"input_tokens": 100, "output_tokens": 0, "service_tier": "flex"},
        processing_mode="priority",
    )

    assert result is not None
    assert result.processing_mode == "flex"
    assert result.total_cost == Decimal("0.5")


async def test_unknown_model_returns_none(monkeypatch) -> None:
    async def _table(cache_timeout: int = 86400, **_kwargs):
        _ = cache_timeout
        return {}

    monkeypatch.setattr(api, "get_pricing_table", _table)
    assert await api.cost_async("test-model", 10, 5) is None


@pytest.mark.parametrize(
    "case", FIXTURE["cache_and_reasoning"], ids=lambda c: c["name"]
)
async def test_cache_and_reasoning_matches_fixture(monkeypatch, case: dict) -> None:
    _stub_table(monkeypatch, case["pricing"])

    result = await api.cost_async(
        "test-model",
        case["input_tokens"],
        case["output_tokens"],
        cached_tokens=case.get("cached_tokens", 0),
        cache_creation_tokens=case.get("cache_creation_tokens", 0),
        reasoning_tokens=case.get("reasoning_tokens", 0),
    )

    assert result is not None
    expected = case["expected"]
    assert _money(result.input_cost) == expected["input_cost"]
    assert _money(result.output_cost) == expected["output_cost"]
    assert _money(result.total_cost) == expected["total_cost"]
    assert _money(result.cache_read_cost) == expected["cache_read_cost"]
    assert _money(result.cache_creation_cost) == expected["cache_creation_cost"]
    assert _money(result.reasoning_cost) == expected["reasoning_cost"]
    assert result.tier_applied == expected["tier_applied"]
    # The invariant that answers "is the total adding it up right?"
    assert result.input_cost + result.output_cost == result.total_cost


async def test_openai_usage_shape_treats_cached_as_a_subset(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {
            "input_cost_per_token": "0.000005",
            "output_cost_per_token": "0.00003",
            "cache_read_input_token_cost": "0.0000005",
        },
    )

    result = await api.usage_async(
        "test-model",
        {
            "prompt_tokens": 100_000,
            "completion_tokens": 1_000,
            "prompt_tokens_details": {"cached_tokens": 90_000},
        },
    )

    assert result is not None
    assert result.total_cost == Decimal("0.125000")
    assert result.cache_read_cost == Decimal("0.045000")


async def test_anthropic_usage_shape_treats_cache_as_additive(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {
            "input_cost_per_token": "0.000003",
            "output_cost_per_token": "0.000015",
            "cache_read_input_token_cost": "0.0000003",
            "cache_creation_input_token_cost": "0.00000375",
        },
    )

    result = await api.usage_async(
        "test-model",
        {
            "input_tokens": 1_000,
            "output_tokens": 500,
            "cache_read_input_tokens": 90_000,
            "cache_creation_input_tokens": 2_000,
        },
    )

    assert result is not None
    # 1000 text + 90000 read + 2000 creation are all billed.
    assert result.total_cost == Decimal("0.045000")
    assert result.cache_read_cost == Decimal("0.027000")
    assert result.cache_creation_cost == Decimal("0.007500")


async def test_reasoning_tokens_read_from_completion_details(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {
            "input_cost_per_token": "0.000005",
            "output_cost_per_token": "0.00003",
            "output_cost_per_reasoning_token": "0.00006",
        },
    )

    result = await api.usage_async(
        "test-model",
        {
            "prompt_tokens": 1_000,
            "completion_tokens": 5_000,
            "completion_tokens_details": {"reasoning_tokens": 4_000},
        },
    )

    assert result is not None
    assert result.total_cost == Decimal("0.275000")
    assert result.reasoning_cost == Decimal("0.240000")


async def test_cached_tokens_cannot_exceed_input_tokens(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {"input_cost_per_token": "0.000005", "output_cost_per_token": "0.00003"},
    )

    with pytest.raises(ValueError, match="must not exceed input_tokens"):
        await api.cost_async("test-model", 100, 10, cached_tokens=101)

    with pytest.raises(ValueError, match="must not exceed input_tokens"):
        await api.cost_async("test-model", 100, 10, cached_tokens=60, cache_creation_tokens=60)


async def test_reasoning_tokens_cannot_exceed_output_tokens(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {"input_cost_per_token": "0.000005", "output_cost_per_token": "0.00003"},
    )

    with pytest.raises(ValueError, match="must not exceed output_tokens"):
        await api.cost_async("test-model", 100, 10, reasoning_tokens=11)


async def test_cache_kwargs_reject_bool_and_negative(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {"input_cost_per_token": "0.000005", "output_cost_per_token": "0.00003"},
    )

    with pytest.raises(ValueError, match="must be an integer"):
        await api.cost_async("test-model", 100, 10, cached_tokens=True)
    with pytest.raises(ValueError, match="non-negative"):
        await api.cost_async("test-model", 100, 10, cached_tokens=-1)


@pytest.mark.parametrize(
    "case", DIMENSIONS_FIXTURE["cases"], ids=lambda case: case["name"]
)
async def test_pricing_dimensions(monkeypatch, case: dict) -> None:
    _stub_table(monkeypatch, case.get("pricing", DIMENSIONS_FIXTURE["pricing"]))
    result = await api.cost_async(
        "test-model",
        case["input_tokens"],
        case["output_tokens"],
        **case["options"],
    )
    assert result is not None
    assert result.input_cost == Decimal(case["expected"]["input_cost"])
    assert result.output_cost == Decimal(case["expected"]["output_cost"])
    assert result.total_cost == Decimal(case["expected"]["total_cost"])
    if "query_cost" in case["expected"]:
        assert result.query_cost == Decimal(case["expected"]["query_cost"])
    if "cache_creation_audio_cost" in case["expected"]:
        assert result.cache_creation_audio_cost == Decimal(
            case["expected"]["cache_creation_audio_cost"]
        )


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (
            {"cache_creation_tokens": 1, "cache_creation_tokens_1h": 1},
            "does not declare one-hour cache pricing",
        ),
        (
            {
                "cache_creation_tokens": 1,
                "cache_creation_audio_tokens": 1,
                "input_audio_tokens": 1,
            },
            "does not declare audio cache-write pricing",
        ),
        ({"query_count": 1}, "does not declare per-query pricing"),
        ({"web_search_requests": 1}, "does not declare web-search pricing"),
        ({"maps_grounding_requests": 1}, "does not declare maps-grounding pricing"),
        ({"region": "regional"}, "does not declare pricing for region 'regional'"),
    ],
)
async def test_requested_dimensions_require_declared_rates(
    monkeypatch, options: dict, message: str
) -> None:
    _stub_table(monkeypatch, {"input_cost_per_token": "0.01"})

    with pytest.raises(ValueError, match=message):
        await api.cost_async("test-model", 1, 0, **options)


async def test_query_result_tiers_require_supported_result_count(monkeypatch) -> None:
    _stub_table(
        monkeypatch,
        {
            "tiered_pricing": [
                {"input_cost_per_query": "0.005", "max_results_range": [0, 25]}
            ]
        },
    )

    with pytest.raises(ValueError, match="query_results is required"):
        await api.cost_async("test-model", 0, 0, query_count=1)
    with pytest.raises(ValueError, match="query_results=26"):
        await api.cost_async("test-model", 0, 0, query_count=1, query_results=26)


@pytest.mark.parametrize("mode", ["batch", "priority", "flex"])
async def test_processing_modes_require_declared_pricing(monkeypatch, mode: str) -> None:
    _stub_table(monkeypatch, {"input_cost_per_token": "0.01"})

    with pytest.raises(ValueError, match=f"does not declare {mode} pricing"):
        await api.cost_async("test-model", 1, 0, processing_mode=mode)
