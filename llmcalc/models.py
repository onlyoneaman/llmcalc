"""Pydantic models for pricing and cost breakdown data."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llmcalc.pricing_tiers import (
    PricingMode,
    PricingModeProfile,
    PricingThreshold,
    PricingTier,
    QueryPricingTier,
    TokenRates,
    parse_base_rates,
    parse_pricing_modes,
    parse_query_tiers,
    parse_thresholds,
    parse_tiers,
)

COST_DECIMAL_PRECISION = 50


def _per_million_to_per_token(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = COST_DECIMAL_PRECISION
        context.rounding = ROUND_HALF_UP
        return value / Decimal("1000000")


def _to_positive_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed > Decimal("0") else None


class CostBreakdown(BaseModel):
    """Cost result for a token usage calculation.

    `input_cost` covers every prompt token, including any cache-read and
    cache-creation portion; `output_cost` likewise includes reasoning tokens.
    `total_cost` is their sum, so it always accounts for all token kinds passed.
    """

    input_cost: Decimal = Field(ge=Decimal("0"))
    output_cost: Decimal = Field(ge=Decimal("0"))
    total_cost: Decimal = Field(ge=Decimal("0"))
    currency: str = "USD"
    tier_applied: str | None = None
    cache_read_cost: Decimal = Decimal("0")
    cache_creation_cost: Decimal = Decimal("0")
    cache_creation_audio_cost: Decimal = Decimal("0")
    cache_creation_1h_cost: Decimal = Decimal("0")
    reasoning_cost: Decimal = Decimal("0")
    audio_input_cost: Decimal = Decimal("0")
    audio_output_cost: Decimal = Decimal("0")
    image_input_cost: Decimal = Decimal("0")
    image_output_cost: Decimal = Decimal("0")
    query_cost: Decimal = Decimal("0")
    processing_mode: PricingMode = "standard"
    regional_multiplier: Decimal = Decimal("1")

    model_config = ConfigDict(frozen=True)


class ModelPricing(BaseModel):
    """Normalized token pricing for one model.

    Base rates are optional: models priced purely through `tiered_pricing`
    publish no flat per-token rate at all.
    """

    model: str
    input_cost_per_token: Decimal | None = None
    output_cost_per_token: Decimal | None = None
    cache_read_cost_per_token: Decimal | None = None
    cache_read_audio_cost_per_token: Decimal | None = None
    cache_creation_cost_per_token: Decimal | None = None
    cache_creation_audio_cost_per_token: Decimal | None = None
    cache_creation_1h_cost_per_token: Decimal | None = None
    reasoning_cost_per_token: Decimal | None = None
    input_audio_cost_per_token: Decimal | None = None
    output_audio_cost_per_token: Decimal | None = None
    input_image_cost_per_token: Decimal | None = None
    output_image_cost_per_token: Decimal | None = None
    input_cost_per_query: Decimal | None = None
    search_context_cost_per_query: dict[str, Decimal] = Field(default_factory=dict)
    google_maps_grounding_cost_per_query: Decimal | None = None
    web_search_billing_unit: Literal["per_prompt", "per_query"] = "per_prompt"
    regional_processing_uplift: dict[str, Decimal] = Field(default_factory=dict)
    thresholds: tuple[PricingThreshold, ...] = ()
    tiered_pricing: tuple[PricingTier, ...] = ()
    query_pricing: tuple[QueryPricingTier, ...] = ()
    pricing_modes: dict[PricingMode, PricingModeProfile] = Field(default_factory=dict)
    provider: str | None = None
    currency: str = "USD"
    last_updated: str | None = None

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    @field_validator(
        "input_cost_per_token",
        "output_cost_per_token",
        "cache_read_cost_per_token",
        "cache_read_audio_cost_per_token",
        "cache_creation_cost_per_token",
        "cache_creation_audio_cost_per_token",
        "cache_creation_1h_cost_per_token",
        "reasoning_cost_per_token",
        "input_audio_cost_per_token",
        "output_audio_cost_per_token",
        "input_image_cost_per_token",
        "output_image_cost_per_token",
        "input_cost_per_query",
        "google_maps_grounding_cost_per_query",
    )
    @classmethod
    def reject_negative_rates(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < Decimal("0"):
            raise ValueError("pricing values must be non-negative")
        return value

    @field_validator("search_context_cost_per_query")
    @classmethod
    def reject_negative_search_rates(
        cls, value: dict[str, Decimal]
    ) -> dict[str, Decimal]:
        if any(rate < Decimal("0") for rate in value.values()):
            raise ValueError("pricing values must be non-negative")
        return value

    @field_validator("regional_processing_uplift")
    @classmethod
    def reject_invalid_uplifts(
        cls, value: dict[str, Decimal]
    ) -> dict[str, Decimal]:
        if any(multiplier <= Decimal("0") for multiplier in value.values()):
            raise ValueError("regional uplift multipliers must be positive")
        return value

    def base_rates(self) -> TokenRates:
        """Bundle the declared rates for `pricing_tiers` to resolve against."""
        return TokenRates(
            input=self.input_cost_per_token,
            output=self.output_cost_per_token,
            cache_read=self.cache_read_cost_per_token,
            cache_read_audio=self.cache_read_audio_cost_per_token,
            cache_creation=self.cache_creation_cost_per_token,
            cache_creation_audio=self.cache_creation_audio_cost_per_token,
            cache_creation_1h=self.cache_creation_1h_cost_per_token,
            reasoning=self.reasoning_cost_per_token,
            input_audio=self.input_audio_cost_per_token,
            output_audio=self.output_audio_cost_per_token,
            input_image=self.input_image_cost_per_token,
            output_image=self.output_image_cost_per_token,
        )


class RawModelPricing(BaseModel):
    """Flexible upstream schema model from litellm pricing JSON."""

    # extra="allow" keeps the above_{N}_tokens threshold keys reachable via
    # model_extra so parse_thresholds can see them.
    model_config = ConfigDict(extra="allow")

    input_cost_per_token: Decimal | None = None
    output_cost_per_token: Decimal | None = None
    tiered_pricing: list[Any] | None = None

    # Common aliases used by some pricing datasets.
    prompt_cost_per_token: Decimal | None = None
    completion_cost_per_token: Decimal | None = None
    input_cost_per_million_tokens: Decimal | None = None
    output_cost_per_million_tokens: Decimal | None = None

    cache_read_input_token_cost: Decimal | None = None
    cache_read_input_audio_token_cost: Decimal | None = None
    cache_creation_input_token_cost: Decimal | None = None
    cache_creation_input_audio_token_cost: Decimal | None = None
    cache_creation_input_token_cost_above_1hr: Decimal | None = None
    output_cost_per_reasoning_token: Decimal | None = None
    input_cost_per_audio_token: Decimal | None = None
    output_cost_per_audio_token: Decimal | None = None
    input_cost_per_image_token: Decimal | None = None
    output_cost_per_image_token: Decimal | None = None
    input_cost_per_query: Decimal | None = None
    search_context_cost_per_query: dict[str, Decimal] | None = None
    google_maps_grounding_cost_per_query: Decimal | None = None
    web_search_billing_unit: Literal["per_prompt", "per_query"] | None = None
    regional_processing_uplift_multiplier_us: Decimal | None = None
    regional_processing_uplift_multiplier_eu: Decimal | None = None
    regional_endpoint_uplift_multiplier: Decimal | None = None
    provider_specific_entry: dict[str, Any] | None = None

    provider: str | None = None
    litellm_provider: str | None = None
    currency: str | None = None
    last_updated: str | None = None

    @field_validator("input_cost_per_token", "output_cost_per_token", mode="before")
    @classmethod
    def normalize_numeric_str(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("prompt_cost_per_token", "completion_cost_per_token", mode="before")
    @classmethod
    def normalize_alias_numeric_str(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(
        "input_cost_per_million_tokens",
        "output_cost_per_million_tokens",
        mode="before",
    )
    @classmethod
    def normalize_million_numeric_str(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    def to_model_pricing(self, model: str, default_currency: str = "USD") -> ModelPricing:
        input_cost = self.input_cost_per_token
        output_cost = self.output_cost_per_token

        if input_cost is None:
            input_cost = self.prompt_cost_per_token
        if output_cost is None:
            output_cost = self.completion_cost_per_token
        if input_cost is None and self.input_cost_per_million_tokens is not None:
            input_cost = _per_million_to_per_token(self.input_cost_per_million_tokens)
        if output_cost is None and self.output_cost_per_million_tokens is not None:
            output_cost = _per_million_to_per_token(self.output_cost_per_million_tokens)

        extra = self.model_extra or {}
        raw_values = self.model_dump(exclude_none=True)
        raw_values.update(extra)
        tiers = parse_tiers(self.tiered_pricing)
        query_tiers = parse_query_tiers(self.tiered_pricing)
        thresholds = parse_thresholds(raw_values)
        aux = parse_base_rates(raw_values)
        pricing_modes = parse_pricing_modes(raw_values)
        fast_multiplier = _to_positive_decimal(
            (self.provider_specific_entry or {}).get("fast")
        )
        if fast_multiplier is not None and "priority" not in pricing_modes:
            def scaled(rate: Decimal | None) -> Decimal | None:
                return None if rate is None else rate * fast_multiplier

            pricing_modes["priority"] = PricingModeProfile(
                rates=TokenRates(
                    input=scaled(input_cost),
                    output=scaled(output_cost),
                    cache_read=scaled(aux.cache_read),
                    cache_read_audio=scaled(aux.cache_read_audio),
                    cache_creation=scaled(aux.cache_creation),
                    cache_creation_audio=scaled(aux.cache_creation_audio),
                    cache_creation_1h=scaled(aux.cache_creation_1h),
                    reasoning=scaled(aux.reasoning),
                    input_audio=scaled(aux.input_audio),
                    output_audio=scaled(aux.output_audio),
                    input_image=scaled(aux.input_image),
                    output_image=scaled(aux.output_image),
                ),
                thresholds=(),
            )
        search_costs = {
            key: value
            for key, value in (self.search_context_cost_per_query or {}).items()
            if key
            in {
                "search_context_size_low",
                "search_context_size_medium",
                "search_context_size_high",
            }
        }

        has_base_rate = input_cost is not None or output_cost is not None
        has_unit_rate = any(
            value is not None
            for value in (
                aux.cache_read,
                aux.cache_read_audio,
                aux.cache_creation,
                aux.cache_creation_audio,
                aux.cache_creation_1h,
                aux.reasoning,
                aux.input_audio,
                aux.output_audio,
                aux.input_image,
                aux.output_image,
                self.input_cost_per_query,
                self.google_maps_grounding_cost_per_query,
            )
        ) or bool(search_costs) or bool(pricing_modes)
        if not has_base_rate and not tiers and not query_tiers and not has_unit_rate:
            raise ValueError("Missing supported pricing fields")
        regional_uplift = {
            region: value
            for region, value in (
                ("us", self.regional_processing_uplift_multiplier_us),
                ("eu", self.regional_processing_uplift_multiplier_eu),
            )
            if value is not None
        }
        provider_us = _to_positive_decimal((self.provider_specific_entry or {}).get("us"))
        if "us" not in regional_uplift and provider_us is not None:
            regional_uplift["us"] = provider_us
        if self.regional_endpoint_uplift_multiplier is not None:
            regional_uplift["regional"] = self.regional_endpoint_uplift_multiplier

        return ModelPricing(
            model=model,
            input_cost_per_token=input_cost,
            output_cost_per_token=output_cost,
            cache_read_cost_per_token=aux.cache_read,
            cache_read_audio_cost_per_token=aux.cache_read_audio,
            cache_creation_cost_per_token=aux.cache_creation,
            cache_creation_audio_cost_per_token=aux.cache_creation_audio,
            cache_creation_1h_cost_per_token=aux.cache_creation_1h,
            reasoning_cost_per_token=aux.reasoning,
            input_audio_cost_per_token=aux.input_audio,
            output_audio_cost_per_token=aux.output_audio,
            input_image_cost_per_token=aux.input_image,
            output_image_cost_per_token=aux.output_image,
            input_cost_per_query=self.input_cost_per_query,
            search_context_cost_per_query=search_costs,
            google_maps_grounding_cost_per_query=self.google_maps_grounding_cost_per_query,
            web_search_billing_unit=self.web_search_billing_unit or "per_prompt",
            regional_processing_uplift=regional_uplift,
            thresholds=thresholds,
            tiered_pricing=tiers,
            query_pricing=query_tiers,
            pricing_modes=pricing_modes,
            provider=self.litellm_provider or self.provider,
            currency=self.currency or default_currency,
            last_updated=self.last_updated,
        )
