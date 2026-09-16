"""Public API for llmcalc."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any, TypeVar

from llmcalc.cache import clear_cache as clear_cache_file
from llmcalc.config import DEFAULT_CACHE_TIMEOUT_SECONDS, resolve_cache_timeout
from llmcalc.cost_engine import (
    calculate_cost_components as _calculate_cost_components,
)
from llmcalc.cost_engine import normalize_processing_mode as _normalize_pricing_mode
from llmcalc.cost_engine import resolve_model_rates as _resolve_model_rates
from llmcalc.diagnostics import PricingParseResult
from llmcalc.models import CostBreakdown, ModelPricing
from llmcalc.normalize import resolve_model_key
from llmcalc.pricing_client import get_pricing_report, get_pricing_table
from llmcalc.pricing_tiers import select_query_tier_rate
from llmcalc.usage_normalization import TEXT_INPUT_MESSAGE as TEXT_INPUT_MESSAGE
from llmcalc.usage_normalization import get_usage_tokens as _get_usage_tokens  # noqa: F401
from llmcalc.usage_normalization import normalize_usage as _normalize_usage
from llmcalc.usage_normalization import validate_token_count as _validate_token_count

T = TypeVar("T")

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
    *,
    snapshot_at: str | None = None,
) -> ModelPricing | None:
    """Return per-token pricing for a model, or `None` if not found."""
    options: dict[str, Any] = {"cache_timeout": resolve_cache_timeout(cache_timeout)}
    if snapshot_at is not None:
        options["snapshot_at"] = snapshot_at
    table = await get_pricing_table(**options)
    resolved = resolve_model_key(model, table.keys())
    if resolved is None:
        return None
    return table[resolved]


def model(
    model: str,
    cache_timeout: int | None = None,
    *,
    snapshot_at: str | None = None,
) -> ModelPricing | None:
    """Return per-token pricing for a model, or `None` if not found."""
    return _run_sync(
        model_async(
            model=model,
            cache_timeout=cache_timeout,
            snapshot_at=snapshot_at,
        )
    )


async def pricing_report_async(
    cache_timeout: int | None = None,
    *,
    pricing_url: str | None = None,
    snapshot_at: str | None = None,
    strict: bool = False,
) -> PricingParseResult:
    """Return the pricing table together with parser diagnostics."""
    return await get_pricing_report(
        cache_timeout=resolve_cache_timeout(cache_timeout),
        pricing_url=pricing_url,
        snapshot_at=snapshot_at,
        strict=strict,
    )


def pricing_report(
    cache_timeout: int | None = None,
    *,
    pricing_url: str | None = None,
    snapshot_at: str | None = None,
    strict: bool = False,
) -> PricingParseResult:
    """Return the pricing table together with parser diagnostics."""
    return _run_sync(
        pricing_report_async(
            cache_timeout=cache_timeout,
            pricing_url=pricing_url,
            snapshot_at=snapshot_at,
            strict=strict,
        )
    )


async def cost_async(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_timeout: int | None = None,
    *,
    snapshot_at: str | None = None,
    cached_tokens: int = 0,
    cache_creation_tokens: int = 0,
    reasoning_tokens: int = 0,
    processing_mode: str | None = None,
    cache_creation_tokens_1h: int = 0,
    cache_creation_audio_tokens: int = 0,
    cached_audio_tokens: int = 0,
    cached_image_tokens: int = 0,
    input_audio_tokens: int = 0,
    output_audio_tokens: int = 0,
    input_image_tokens: int = 0,
    output_image_tokens: int = 0,
    query_count: int = 0,
    query_results: int | None = None,
    web_search_requests: int = 0,
    web_search_context: str = "medium",
    maps_grounding_requests: int = 0,
    region: str | None = None,
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
    _validate_token_count(cache_creation_tokens_1h, "cache_creation_tokens_1h")
    _validate_token_count(cache_creation_audio_tokens, "cache_creation_audio_tokens")
    _validate_token_count(cached_audio_tokens, "cached_audio_tokens")
    _validate_token_count(cached_image_tokens, "cached_image_tokens")
    _validate_token_count(input_audio_tokens, "input_audio_tokens")
    _validate_token_count(output_audio_tokens, "output_audio_tokens")
    _validate_token_count(input_image_tokens, "input_image_tokens")
    _validate_token_count(output_image_tokens, "output_image_tokens")
    _validate_token_count(query_count, "query_count")
    if query_results is not None:
        _validate_token_count(query_results, "query_results")
    _validate_token_count(web_search_requests, "web_search_requests")
    _validate_token_count(maps_grounding_requests, "maps_grounding_requests")
    active_mode = _normalize_pricing_mode(processing_mode)

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
    if cache_creation_tokens_1h > cache_creation_tokens:
        raise ValueError("cache_creation_tokens_1h must not exceed cache_creation_tokens")
    if cache_creation_audio_tokens + cache_creation_tokens_1h > cache_creation_tokens:
        raise ValueError(
            "cache_creation_audio_tokens + cache_creation_tokens_1h "
            "must not exceed cache_creation_tokens"
        )
    if cached_audio_tokens + cached_image_tokens > cached_tokens:
        raise ValueError(
            "cached_audio_tokens + cached_image_tokens must not exceed cached_tokens"
        )
    if cached_audio_tokens > input_audio_tokens:
        raise ValueError("cached_audio_tokens must not exceed input_audio_tokens")
    if cached_audio_tokens + cache_creation_audio_tokens > input_audio_tokens:
        raise ValueError(
            "cached_audio_tokens + cache_creation_audio_tokens "
            "must not exceed input_audio_tokens"
        )
    if cached_image_tokens > input_image_tokens:
        raise ValueError("cached_image_tokens must not exceed input_image_tokens")
    uncached_audio_tokens = (
        input_audio_tokens - cached_audio_tokens - cache_creation_audio_tokens
    )
    uncached_image_tokens = input_image_tokens - cached_image_tokens
    if (
        cached_tokens
        + cache_creation_tokens
        + uncached_audio_tokens
        + uncached_image_tokens
        > input_tokens
    ):
        raise ValueError("input token details must not exceed input_tokens")
    if reasoning_tokens + output_audio_tokens + output_image_tokens > output_tokens:
        raise ValueError("output token details must not exceed output_tokens")

    normalized_region = None if region is None else region.strip().lower()
    if normalized_region == "global":
        normalized_region = None
    if normalized_region not in {None, "us", "eu", "regional"}:
        raise ValueError("region must be 'global', 'regional', 'us', or 'eu'")
    normalized_search_context = web_search_context.strip().lower()
    if normalized_search_context not in {"low", "medium", "high"}:
        raise ValueError("web_search_context must be 'low', 'medium', or 'high'")

    model_costs = await model_async(
        model,
        cache_timeout=cache_timeout,
        snapshot_at=snapshot_at,
    )
    if model_costs is None:
        return None
    if active_mode != "standard" and active_mode not in model_costs.pricing_modes:
        raise ValueError(
            f"model {model_costs.model} does not declare {active_mode} pricing"
        )

    has_non_token_usage = query_count + web_search_requests + maps_grounding_requests > 0
    if input_tokens == 0 and output_tokens == 0 and not has_non_token_usage:
        return CostBreakdown(
            input_cost=Decimal("0"),
            output_cost=Decimal("0"),
            total_cost=Decimal("0"),
            currency=model_costs.currency,
            processing_mode=active_mode,
        )

    text_input = (
        input_tokens
        - cached_tokens
        - cache_creation_tokens
        - uncached_audio_tokens
        - uncached_image_tokens
    )
    text_output = output_tokens - reasoning_tokens - output_audio_tokens - output_image_tokens
    rates, tier_applied = _resolve_model_rates(model_costs, input_tokens, active_mode)
    if cache_creation_tokens_1h > 0 and rates.cache_creation_1h is None:
        raise ValueError(f"model {model_costs.model} does not declare one-hour cache pricing")
    if cache_creation_audio_tokens > 0 and rates.cache_creation_audio is None:
        raise ValueError(
            f"model {model_costs.model} does not declare audio cache-write pricing"
        )
    query_rate = model_costs.input_cost_per_query
    if model_costs.query_pricing:
        if query_count > 0 and query_results is None:
            raise ValueError("query_results is required for tiered per-query pricing")
        if query_results is not None:
            query_rate = select_query_tier_rate(model_costs.query_pricing, query_results)
            if query_rate is None:
                raise ValueError(
                    f"model {model_costs.model} does not declare pricing for "
                    f"query_results={query_results}"
                )
    elif query_results is not None:
        raise ValueError(f"model {model_costs.model} does not declare query-result tiers")
    if query_count > 0 and query_rate is None:
        raise ValueError(f"model {model_costs.model} does not declare per-query pricing")
    if (
        web_search_requests > 0
        and f"search_context_size_{normalized_search_context}"
        not in model_costs.search_context_cost_per_query
    ):
        raise ValueError(f"model {model_costs.model} does not declare web-search pricing")
    if maps_grounding_requests > 0 and model_costs.google_maps_grounding_cost_per_query is None:
        raise ValueError(f"model {model_costs.model} does not declare maps-grounding pricing")
    if (
        normalized_region is not None
        and normalized_region not in model_costs.regional_processing_uplift
    ):
        raise ValueError(
            f"model {model_costs.model} does not declare pricing for region "
            f"{normalized_region!r}"
        )
    regional_multiplier = (
        Decimal("1")
        if normalized_region is None
        else model_costs.regional_processing_uplift.get(normalized_region, Decimal("1"))
    )

    components = _calculate_cost_components(
        model_costs,
        rates,
        text_input,
        text_output,
        cached_tokens,
        cached_audio_tokens,
        cache_creation_tokens,
        cache_creation_audio_tokens,
        cache_creation_tokens_1h,
        reasoning_tokens,
        uncached_audio_tokens,
        output_audio_tokens,
        uncached_image_tokens,
        output_image_tokens,
        query_count,
        query_rate,
        web_search_requests,
        normalized_search_context,
        maps_grounding_requests,
        regional_multiplier,
    )
    if components is None:
        return None
    (
        raw_input,
        raw_output,
        raw_total,
        raw_cache_read,
        raw_cache_creation,
        raw_cache_creation_audio,
        raw_cache_creation_1h,
        raw_reasoning,
        raw_audio_input,
        raw_audio_output,
        raw_image_input,
        raw_image_output,
        raw_query,
    ) = components

    return CostBreakdown(
        input_cost=raw_input,
        output_cost=raw_output,
        total_cost=raw_total,
        currency=model_costs.currency,
        tier_applied=tier_applied,
        cache_read_cost=raw_cache_read,
        cache_creation_cost=raw_cache_creation,
        cache_creation_audio_cost=raw_cache_creation_audio,
        cache_creation_1h_cost=raw_cache_creation_1h,
        reasoning_cost=raw_reasoning,
        audio_input_cost=raw_audio_input,
        audio_output_cost=raw_audio_output,
        image_input_cost=raw_image_input,
        image_output_cost=raw_image_output,
        query_cost=raw_query,
        processing_mode=active_mode,
        regional_multiplier=regional_multiplier,
    )


def cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_timeout: int | None = None,
    *,
    snapshot_at: str | None = None,
    cached_tokens: int = 0,
    cache_creation_tokens: int = 0,
    reasoning_tokens: int = 0,
    processing_mode: str | None = None,
    cache_creation_tokens_1h: int = 0,
    cache_creation_audio_tokens: int = 0,
    cached_audio_tokens: int = 0,
    cached_image_tokens: int = 0,
    input_audio_tokens: int = 0,
    output_audio_tokens: int = 0,
    input_image_tokens: int = 0,
    output_image_tokens: int = 0,
    query_count: int = 0,
    query_results: int | None = None,
    web_search_requests: int = 0,
    web_search_context: str = "medium",
    maps_grounding_requests: int = 0,
    region: str | None = None,
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
            snapshot_at=snapshot_at,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
            reasoning_tokens=reasoning_tokens,
            processing_mode=processing_mode,
            cache_creation_tokens_1h=cache_creation_tokens_1h,
            cache_creation_audio_tokens=cache_creation_audio_tokens,
            cached_audio_tokens=cached_audio_tokens,
            cached_image_tokens=cached_image_tokens,
            input_audio_tokens=input_audio_tokens,
            output_audio_tokens=output_audio_tokens,
            input_image_tokens=input_image_tokens,
            output_image_tokens=output_image_tokens,
            query_count=query_count,
            query_results=query_results,
            web_search_requests=web_search_requests,
            web_search_context=web_search_context,
            maps_grounding_requests=maps_grounding_requests,
            region=region,
        )
    )


async def usage_async(
    model: str,
    usage: object,
    cache_timeout: int | None = None,
    *,
    snapshot_at: str | None = None,
    processing_mode: str | None = None,
    query_results: int | None = None,
    web_search_context: str = "medium",
    region: str | None = None,
) -> CostBreakdown | None:
    """Calculate cost from an object that includes usage token fields.

    Cache and reasoning token counts are picked up automatically from either the
    Anthropic or OpenAI usage shape when present.
    """
    normalized = _normalize_usage(usage)
    return await cost_async(
        model=model,
        input_tokens=normalized.input_tokens,
        output_tokens=normalized.output_tokens,
        cache_timeout=cache_timeout,
        snapshot_at=snapshot_at,
        cached_tokens=normalized.cached_tokens,
        cache_creation_tokens=normalized.cache_creation_tokens,
        reasoning_tokens=normalized.reasoning_tokens,
        processing_mode=normalized.processing_mode or processing_mode,
        cache_creation_tokens_1h=normalized.cache_creation_tokens_1h,
        cache_creation_audio_tokens=normalized.cache_creation_audio_tokens,
        cached_audio_tokens=normalized.cached_audio_tokens,
        cached_image_tokens=normalized.cached_image_tokens,
        input_audio_tokens=normalized.input_audio_tokens,
        output_audio_tokens=normalized.output_audio_tokens,
        input_image_tokens=normalized.input_image_tokens,
        output_image_tokens=normalized.output_image_tokens,
        query_count=normalized.query_count,
        query_results=query_results,
        web_search_requests=normalized.web_search_requests,
        web_search_context=web_search_context,
        maps_grounding_requests=normalized.maps_grounding_requests,
        region=region,
    )


def usage(
    model: str,
    usage: object,
    cache_timeout: int | None = None,
    *,
    snapshot_at: str | None = None,
    processing_mode: str | None = None,
    query_results: int | None = None,
    web_search_context: str = "medium",
    region: str | None = None,
) -> CostBreakdown | None:
    """Calculate cost from an object that includes usage token fields."""
    return _run_sync(
        usage_async(
            model=model,
            usage=usage,
            cache_timeout=cache_timeout,
            snapshot_at=snapshot_at,
            processing_mode=processing_mode,
            query_results=query_results,
            web_search_context=web_search_context,
            region=region,
        )
    )


def clear_cache() -> None:
    """Clear local pricing cache file."""
    clear_cache_file()


DEFAULT_CACHE_TIMEOUT = DEFAULT_CACHE_TIMEOUT_SECONDS
