"""Public API for llmcalc."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol, runtime_checkable

from llmcalc.cache import clear_cache as clear_cache_file
from llmcalc.config import DEFAULT_CACHE_TIMEOUT_SECONDS, resolve_cache_timeout
from llmcalc.models import CostBreakdown, ModelPricing
from llmcalc.normalize import resolve_model_key
from llmcalc.pricing_client import get_pricing_table

DEFAULT_ROUNDING_PLACES = 6


@runtime_checkable
class UsageLike(Protocol):
    """Protocol for usage objects accepted by `calculate_usage_cost`."""

    prompt_tokens: int
    completion_tokens: int


def _round_money(amount: Decimal, places: int = DEFAULT_ROUNDING_PLACES) -> Decimal:
    quant = Decimal("1").scaleb(-places)
    return amount.quantize(quant, rounding=ROUND_HALF_UP)


def _validate_non_negative(value: int, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


async def get_model_costs(
    model: str,
    cache_timeout: int | None = None,
) -> ModelPricing | None:
    """Return per-token pricing for a model, or `None` if not found."""
    table = await get_pricing_table(cache_timeout=resolve_cache_timeout(cache_timeout))
    resolved = resolve_model_key(model, table.keys())
    if resolved is None:
        return None
    return table[resolved]


async def calculate_token_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_timeout: int | None = None,
) -> CostBreakdown | None:
    """Calculate model usage cost from token counts, or return `None` if model is unavailable."""
    _validate_non_negative(input_tokens, "input_tokens")
    _validate_non_negative(output_tokens, "output_tokens")

    model_costs = await get_model_costs(model, cache_timeout=cache_timeout)
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


def _value_from_mapping(usage: dict[str, Any], key_options: tuple[str, ...]) -> int | None:
    for key in key_options:
        value = usage.get(key)
        if isinstance(value, int):
            return value
    return None


def _get_usage_tokens(usage: Any) -> tuple[int, int]:
    if isinstance(usage, dict):
        input_tokens = _value_from_mapping(usage, ("input_tokens", "prompt_tokens"))
        output_tokens = _value_from_mapping(usage, ("output_tokens", "completion_tokens"))
    else:
        input_tokens = getattr(usage, "input_tokens", None)
        if not isinstance(input_tokens, int):
            input_tokens = getattr(usage, "prompt_tokens", None)

        output_tokens = getattr(usage, "output_tokens", None)
        if not isinstance(output_tokens, int):
            output_tokens = getattr(usage, "completion_tokens", None)

    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise ValueError("usage must provide input/prompt tokens and output/completion tokens")

    return input_tokens, output_tokens


async def calculate_usage_cost(
    model: str,
    usage: UsageLike | dict[str, Any],
    cache_timeout: int | None = None,
) -> CostBreakdown | None:
    """Calculate cost from an object that includes usage token fields."""
    input_tokens, output_tokens = _get_usage_tokens(usage)
    return await calculate_token_cost(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_timeout=cache_timeout,
    )


def clear_cache() -> None:
    """Clear local pricing cache file."""
    clear_cache_file()


DEFAULT_CACHE_TIMEOUT = DEFAULT_CACHE_TIMEOUT_SECONDS
