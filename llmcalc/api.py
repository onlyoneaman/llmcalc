"""Public API for llmcalc."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol, TypeVar, runtime_checkable

from llmcalc.cache import clear_cache as clear_cache_file
from llmcalc.config import DEFAULT_CACHE_TIMEOUT_SECONDS, resolve_cache_timeout
from llmcalc.models import CostBreakdown, ModelPricing
from llmcalc.normalize import resolve_model_key
from llmcalc.pricing_client import get_pricing_table
from llmcalc.pricing_tiers import graduated_cost, resolve_rates

DEFAULT_ROUNDING_PLACES = 6
T = TypeVar("T")

TEXT_INPUT_MESSAGE = (
    "llmcalc takes token counts, not text. Pass integer input/output token counts, "
    "or the provider's usage object (for example response.usage). llmcalc does not "
    "tokenize strings or message lists."
)

_INPUT_KEYS = ("input_tokens", "prompt_tokens", "inputTokens", "promptTokens")
_OUTPUT_KEYS = ("output_tokens", "completion_tokens", "outputTokens", "completionTokens")


@runtime_checkable
class UsageLike(Protocol):
    """Protocol for usage objects accepted by `usage`."""

    prompt_tokens: int
    completion_tokens: int


def _round_money(amount: Decimal, places: int = DEFAULT_ROUNDING_PLACES) -> Decimal:
    quant = Decimal("1").scaleb(-places)
    return amount.quantize(quant, rounding=ROUND_HALF_UP)


def _validate_token_count(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _run_sync(awaitable: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    awaitable.close()
    raise RuntimeError(
        "Cannot use synchronous API while an event loop is running; "
        "use *_async API functions instead."
    )


async def model_async(
    model: str,
    cache_timeout: int | None = None,
) -> ModelPricing | None:
    """Return per-token pricing for a model, or `None` if not found."""
    table = await get_pricing_table(cache_timeout=resolve_cache_timeout(cache_timeout))
    resolved = resolve_model_key(model, table.keys())
    if resolved is None:
        return None
    return table[resolved]


def model(
    model: str,
    cache_timeout: int | None = None,
) -> ModelPricing | None:
    """Return per-token pricing for a model, or `None` if not found."""
    return _run_sync(model_async(model=model, cache_timeout=cache_timeout))


async def cost_async(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_timeout: int | None = None,
    *,
    cached_tokens: int = 0,
    cache_creation_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> CostBreakdown | None:
    """Calculate model usage cost from token counts, or return `None` if model is unavailable.

    `input_tokens` is the **total** prompt count, inclusive of `cached_tokens`
    and `cache_creation_tokens`; `output_tokens` is inclusive of
    `reasoning_tokens`. Those subsets are re-priced at their own rates, falling
    back to the plain input/output rate for models that do not declare them.
    """
    _validate_token_count(input_tokens, "input_tokens")
    _validate_token_count(output_tokens, "output_tokens")
    _validate_token_count(cached_tokens, "cached_tokens")
    _validate_token_count(cache_creation_tokens, "cache_creation_tokens")
    _validate_token_count(reasoning_tokens, "reasoning_tokens")

    if cached_tokens + cache_creation_tokens > input_tokens:
        raise ValueError(
            "cached_tokens + cache_creation_tokens must not exceed input_tokens; "
            "input_tokens is the total prompt count, inclusive of both"
        )
    if reasoning_tokens > output_tokens:
        raise ValueError(
            "reasoning_tokens must not exceed output_tokens; "
            "output_tokens is the total completion count, inclusive of reasoning"
        )

    model_costs = await model_async(model, cache_timeout=cache_timeout)
    if model_costs is None:
        return None

    text_input = input_tokens - cached_tokens - cache_creation_tokens
    text_output = output_tokens - reasoning_tokens

    if model_costs.tiered_pricing:
        tiers = model_costs.tiered_pricing
        raw_text_input = graduated_cost(text_input, tiers, "input")
        raw_cache_read = graduated_cost(cached_tokens, tiers, "cache_read")
        raw_cache_creation = graduated_cost(cache_creation_tokens, tiers, "cache_creation")
        raw_text_output = graduated_cost(text_output, tiers, "output")
        raw_reasoning = graduated_cost(reasoning_tokens, tiers, "reasoning")
        tier_applied: str | None = "tiered_pricing"
    else:
        rates, tier_applied = resolve_rates(
            model_costs.base_rates(), model_costs.thresholds, input_tokens
        )
        input_rate = rates.get("input")
        output_rate = rates.get("output")
        if input_rate is None or output_rate is None:
            return None
        raw_text_input = Decimal(text_input) * input_rate
        raw_cache_read = Decimal(cached_tokens) * (rates.get("cache_read") or input_rate)
        raw_cache_creation = Decimal(cache_creation_tokens) * (
            rates.get("cache_creation") or input_rate
        )
        raw_text_output = Decimal(text_output) * output_rate
        raw_reasoning = Decimal(reasoning_tokens) * (rates.get("reasoning") or output_rate)

    raw_input = raw_text_input + raw_cache_read + raw_cache_creation
    raw_output = raw_text_output + raw_reasoning

    # Round each emitted field once, and derive the total from the unrounded
    # legs so the parts cannot disagree with the whole.
    return CostBreakdown(
        input_cost=_round_money(raw_input),
        output_cost=_round_money(raw_output),
        total_cost=_round_money(raw_input + raw_output),
        currency=model_costs.currency,
        tier_applied=tier_applied,
        cache_read_cost=_round_money(raw_cache_read),
        cache_creation_cost=_round_money(raw_cache_creation),
        reasoning_cost=_round_money(raw_reasoning),
    )


def cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_timeout: int | None = None,
    *,
    cached_tokens: int = 0,
    cache_creation_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> CostBreakdown | None:
    """Calculate model usage cost from token counts, or return `None` if model is unavailable.

    `input_tokens` is the total prompt count, inclusive of `cached_tokens` and
    `cache_creation_tokens`; `output_tokens` is inclusive of `reasoning_tokens`.
    """
    return _run_sync(
        cost_async(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_timeout=cache_timeout,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
            reasoning_tokens=reasoning_tokens,
        )
    )


def _coerce_token_value(value: Any, field_name: str) -> int | None:
    """Return an int token count, or None when the key was absent.

    A key that is present but not an int is an error rather than a miss, so the
    caller hears about the type instead of a misleading "not provided" message.
    `bool` is excluded deliberately: it subclasses `int`, so `True` would
    otherwise bill as one token.
    """
    if value is None:
        return None
    if type(value) is int:
        return value
    raise ValueError(f"{field_name} must be an integer, got {type(value).__name__}")


def _value_from_mapping(
    usage: dict[str, Any], key_options: tuple[str, ...], field_name: str
) -> int | None:
    for key in key_options:
        if key in usage:
            return _coerce_token_value(usage[key], field_name)
    return None


def _attr_token(usage: Any, names: tuple[str, ...], field_name: str) -> int | None:
    for name in names:
        value = getattr(usage, name, None)
        if value is not None:
            return _coerce_token_value(value, field_name)
    return None


def _nested(usage: Any, container_keys: tuple[str, ...], names: tuple[str, ...]) -> int:
    """Read a token count out of a nested details object, dict or attribute."""
    for container_key in container_keys:
        container = (
            usage.get(container_key)
            if isinstance(usage, dict)
            else getattr(usage, container_key, None)
        )
        if container is None:
            continue
        value = (
            _value_from_mapping(container, names, container_key)
            if isinstance(container, dict)
            else _attr_token(container, names, container_key)
        )
        if value is not None:
            return value
    return 0


def _flat(usage: Any, names: tuple[str, ...], field_name: str) -> int | None:
    if isinstance(usage, dict):
        return _value_from_mapping(usage, names, field_name)
    return _attr_token(usage, names, field_name)


_PROMPT_DETAIL_KEYS = ("prompt_tokens_details", "promptTokensDetails", "input_tokens_details")
_COMPLETION_DETAIL_KEYS = (
    "completion_tokens_details",
    "completionTokensDetails",
    "output_tokens_details",
)
_CACHE_READ_KEYS = ("cache_read_input_tokens", "cacheReadInputTokens")
_CACHE_CREATION_KEYS = ("cache_creation_input_tokens", "cacheCreationInputTokens")
_CACHED_SUBSET_KEYS = ("cached_tokens", "cachedTokens")
_REASONING_KEYS = ("reasoning_tokens", "reasoningTokens")


def _get_usage_tokens(usage: Any) -> tuple[int, int, int, int, int]:
    """Normalize a provider usage object to inclusive token counts.

    Returns `(input_tokens, output_tokens, cached, cache_creation, reasoning)`
    where `input_tokens` is the total prompt count including both cache subsets
    and `output_tokens` includes reasoning.

    The two provider conventions are distinguished by key name, not by guessing:
    Anthropic reports `cache_read_input_tokens` *in addition to* `input_tokens`,
    while OpenAI reports `prompt_tokens_details.cached_tokens` as a subset of
    `prompt_tokens` already counted.
    """
    if isinstance(usage, (str, list, tuple)):
        raise ValueError(TEXT_INPUT_MESSAGE)

    if isinstance(usage, dict) and "messages" in usage:
        raise ValueError(TEXT_INPUT_MESSAGE)

    input_tokens = _flat(usage, _INPUT_KEYS, "input_tokens")
    output_tokens = _flat(usage, _OUTPUT_KEYS, "output_tokens")

    if input_tokens is None or output_tokens is None:
        raise ValueError("usage must provide input/prompt tokens and output/completion tokens")

    _validate_token_count(input_tokens, "input_tokens")
    _validate_token_count(output_tokens, "output_tokens")

    additive_read = _flat(usage, _CACHE_READ_KEYS, "cache_read_input_tokens")
    additive_creation = _flat(usage, _CACHE_CREATION_KEYS, "cache_creation_input_tokens")

    if additive_read is not None or additive_creation is not None:
        # Anthropic shape: cache counts sit outside input_tokens.
        cached = additive_read or 0
        creation = additive_creation or 0
        _validate_token_count(cached, "cache_read_input_tokens")
        _validate_token_count(creation, "cache_creation_input_tokens")
        input_tokens += cached + creation
    else:
        # OpenAI shape: cached_tokens is already inside prompt_tokens.
        cached = _nested(usage, _PROMPT_DETAIL_KEYS, _CACHED_SUBSET_KEYS)
        creation = 0

    reasoning = _nested(usage, _COMPLETION_DETAIL_KEYS, _REASONING_KEYS)

    return input_tokens, output_tokens, cached, creation, reasoning


async def usage_async(
    model: str,
    usage: UsageLike | dict[str, Any],
    cache_timeout: int | None = None,
) -> CostBreakdown | None:
    """Calculate cost from an object that includes usage token fields.

    Cache and reasoning token counts are picked up automatically from either the
    Anthropic or OpenAI usage shape when present.
    """
    input_tokens, output_tokens, cached, creation, reasoning = _get_usage_tokens(usage)
    return await cost_async(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_timeout=cache_timeout,
        cached_tokens=cached,
        cache_creation_tokens=creation,
        reasoning_tokens=reasoning,
    )


def usage(
    model: str,
    usage: UsageLike | dict[str, Any],
    cache_timeout: int | None = None,
) -> CostBreakdown | None:
    """Calculate cost from an object that includes usage token fields."""
    return _run_sync(
        usage_async(
            model=model,
            usage=usage,
            cache_timeout=cache_timeout,
        )
    )


def clear_cache() -> None:
    """Clear local pricing cache file."""
    clear_cache_file()


DEFAULT_CACHE_TIMEOUT = DEFAULT_CACHE_TIMEOUT_SECONDS
