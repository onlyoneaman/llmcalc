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
) -> CostBreakdown | None:
    """Calculate model usage cost from token counts, or return `None` if model is unavailable."""
    _validate_token_count(input_tokens, "input_tokens")
    _validate_token_count(output_tokens, "output_tokens")

    model_costs = await model_async(model, cache_timeout=cache_timeout)
    if model_costs is None:
        return None

    input_cost = _round_money(Decimal(input_tokens) * model_costs.input_cost_per_token)
    output_cost = _round_money(Decimal(output_tokens) * model_costs.output_cost_per_token)
    total_cost = _round_money(input_cost + output_cost)

    return CostBreakdown(
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total_cost,
        currency=model_costs.currency,
    )


def cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_timeout: int | None = None,
) -> CostBreakdown | None:
    """Calculate model usage cost from token counts, or return `None` if model is unavailable."""
    return _run_sync(
        cost_async(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_timeout=cache_timeout,
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


def _get_usage_tokens(usage: Any) -> tuple[int, int]:
    if isinstance(usage, (str, list, tuple)):
        raise ValueError(TEXT_INPUT_MESSAGE)

    if isinstance(usage, dict):
        if "messages" in usage:
            raise ValueError(TEXT_INPUT_MESSAGE)
        input_tokens = _value_from_mapping(usage, _INPUT_KEYS, "input_tokens")
        output_tokens = _value_from_mapping(usage, _OUTPUT_KEYS, "output_tokens")
    else:
        input_tokens = _attr_token(usage, _INPUT_KEYS, "input_tokens")
        output_tokens = _attr_token(usage, _OUTPUT_KEYS, "output_tokens")

    if input_tokens is None or output_tokens is None:
        raise ValueError("usage must provide input/prompt tokens and output/completion tokens")

    _validate_token_count(input_tokens, "input_tokens")
    _validate_token_count(output_tokens, "output_tokens")

    return input_tokens, output_tokens


async def usage_async(
    model: str,
    usage: UsageLike | dict[str, Any],
    cache_timeout: int | None = None,
) -> CostBreakdown | None:
    """Calculate cost from an object that includes usage token fields."""
    input_tokens, output_tokens = _get_usage_tokens(usage)
    return await cost_async(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_timeout=cache_timeout,
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
