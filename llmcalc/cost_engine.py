"""Pure cost-rate selection and component arithmetic."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

from llmcalc.models import COST_DECIMAL_PRECISION, ModelPricing
from llmcalc.pricing_tiers import (
    PricingMode,
    TokenRates,
    resolve_mode_rates,
    resolve_rates,
    resolve_tier_rates,
    select_tier_rates,
)

_STANDARD_MODES = {"standard", "default", "on_demand", "auto", "0"}
_MODE_ALIASES: dict[str, PricingMode] = {
    "batch": "batch",
    "batches": "batch",
    "priority": "priority",
    "fast": "priority",
    "flex": "flex",
}


def normalize_processing_mode(value: str | None) -> PricingMode:
    normalized = "standard" if value is None else value.strip().lower().replace("-", "_")
    if normalized in _STANDARD_MODES:
        return "standard"
    mode = _MODE_ALIASES.get(normalized)
    if mode is None:
        raise ValueError(f"unsupported pricing mode: {value!s}")
    return mode


def resolve_model_rates(
    pricing: ModelPricing,
    input_tokens: int,
    processing_mode: PricingMode,
) -> tuple[TokenRates, str | None]:
    standard_base = pricing.base_rates()
    base = standard_base
    tier_applied: str | None = None
    if pricing.tiered_pricing:
        selected = select_tier_rates(pricing.tiered_pricing, input_tokens)
        if selected is not None:
            base = resolve_tier_rates(base, selected)
            tier_applied = "tiered_pricing"

    profile = pricing.pricing_modes.get(processing_mode)
    if profile is not None and processing_mode != "batch":
        base = resolve_mode_rates(base, profile, processing_mode)
    rates, threshold_applied = resolve_rates(
        base, pricing.thresholds, input_tokens, pricing.provider
    )
    tier_applied = threshold_applied or tier_applied
    if profile is not None:
        if processing_mode == "batch":
            rates = resolve_mode_rates(
                rates,
                profile,
                processing_mode,
                standard_base=standard_base,
                provider=pricing.provider,
            )
        rates, mode_tier = resolve_rates(
            rates,
            profile.thresholds,
            input_tokens,
            pricing.provider,
        )
        tier_applied = mode_tier or tier_applied
    return rates, tier_applied


def _component_cost(count: int, rate: Decimal | None) -> Decimal | None:
    if count == 0:
        return Decimal("0")
    if rate is None:
        return None
    with localcontext() as context:
        context.prec = COST_DECIMAL_PRECISION
        context.rounding = ROUND_HALF_UP
        return Decimal(count) * rate


def calculate_cost_components(
    pricing: ModelPricing,
    rates: TokenRates,
    text_input: int,
    text_output: int,
    cached_tokens: int,
    cached_audio_tokens: int,
    cache_creation_tokens: int,
    cache_creation_audio_tokens: int,
    cache_creation_tokens_1h: int,
    reasoning_tokens: int,
    input_audio_tokens: int,
    output_audio_tokens: int,
    input_image_tokens: int,
    output_image_tokens: int,
    query_count: int,
    query_rate: Decimal | None,
    web_search_requests: int,
    web_search_context: str,
    maps_grounding_requests: int,
    regional_multiplier: Decimal,
) -> tuple[Decimal, ...] | None:
    cache_creation_5m = (
        cache_creation_tokens
        - cache_creation_tokens_1h
        - cache_creation_audio_tokens
    )
    cached_non_audio = cached_tokens - cached_audio_tokens
    costs = (
        _component_cost(text_input, rates.get("input")),
        _component_cost(text_output, rates.get("output")),
        _component_cost(cached_non_audio, rates.get("cache_read")),
        _component_cost(cached_audio_tokens, rates.get("cache_read_audio")),
        _component_cost(cache_creation_5m, rates.get("cache_creation")),
        _component_cost(cache_creation_audio_tokens, rates.cache_creation_audio),
        _component_cost(cache_creation_tokens_1h, rates.cache_creation_1h),
        _component_cost(reasoning_tokens, rates.get("reasoning")),
        _component_cost(input_audio_tokens, rates.get("input_audio")),
        _component_cost(output_audio_tokens, rates.get("output_audio")),
        _component_cost(input_image_tokens, rates.get("input_image")),
        _component_cost(output_image_tokens, rates.get("output_image")),
        _component_cost(query_count, query_rate),
    )
    if any(cost is None for cost in costs):
        return None

    web_rate = pricing.search_context_cost_per_query.get(
        f"search_context_size_{web_search_context}"
    )
    web_billable = (
        1
        if web_search_requests > 0 and pricing.web_search_billing_unit == "per_prompt"
        else web_search_requests
    )
    maps_billable = (
        1
        if maps_grounding_requests > 0 and pricing.web_search_billing_unit == "per_prompt"
        else maps_grounding_requests
    )
    web_cost = _component_cost(web_billable, web_rate)
    maps_cost = _component_cost(
        maps_billable, pricing.google_maps_grounding_cost_per_query
    )
    if web_cost is None or maps_cost is None:
        return None

    (
        raw_text_input,
        raw_text_output,
        raw_cache_read,
        raw_cached_audio,
        raw_cache_creation_5m,
        raw_cache_creation_audio,
        raw_cache_creation_1h,
        raw_reasoning,
        raw_audio_input,
        raw_audio_output,
        raw_image_input,
        raw_image_output,
        raw_query,
    ) = (cost for cost in costs if cost is not None)

    with localcontext() as context:
        context.prec = COST_DECIMAL_PRECISION
        context.rounding = ROUND_HALF_UP
        cache_read_cost = (raw_cache_read + raw_cached_audio) * regional_multiplier
        cache_creation_1h_cost = raw_cache_creation_1h * regional_multiplier
        cache_creation_cost = (
            raw_cache_creation_5m
            + raw_cache_creation_audio
            + raw_cache_creation_1h
        ) * regional_multiplier
        cache_creation_audio_cost = raw_cache_creation_audio * regional_multiplier
        reasoning_cost = raw_reasoning * regional_multiplier
        audio_input_cost = raw_audio_input * regional_multiplier
        audio_output_cost = raw_audio_output * regional_multiplier
        image_input_cost = raw_image_input * regional_multiplier
        image_output_cost = raw_image_output * regional_multiplier
        query_cost = raw_query * regional_multiplier + web_cost + maps_cost
        input_cost = (
            raw_text_input * regional_multiplier
            + cache_read_cost
            + cache_creation_cost
            + audio_input_cost
            + image_input_cost
            + query_cost
        )
        output_cost = (
            raw_text_output * regional_multiplier
            + reasoning_cost
            + audio_output_cost
            + image_output_cost
        )
        total_cost = input_cost + output_cost

    return (
        input_cost,
        output_cost,
        total_cost,
        cache_read_cost,
        cache_creation_cost,
        cache_creation_audio_cost,
        cache_creation_1h_cost,
        reasoning_cost,
        audio_input_cost,
        audio_output_cost,
        image_input_cost,
        image_output_cost,
        query_cost,
    )
