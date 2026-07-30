"""Pydantic models for pricing and cost breakdown data."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llmcalc.pricing_tiers import (
    PricingThreshold,
    PricingTier,
    TokenRates,
    parse_base_rates,
    parse_thresholds,
    parse_tiers,
)


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
    reasoning_cost: Decimal = Decimal("0")

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
    cache_creation_cost_per_token: Decimal | None = None
    reasoning_cost_per_token: Decimal | None = None
    thresholds: tuple[PricingThreshold, ...] = ()
    tiered_pricing: tuple[PricingTier, ...] = ()
    provider: str | None = None
    currency: str = "USD"
    last_updated: str | None = None

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    @field_validator(
        "input_cost_per_token",
        "output_cost_per_token",
        "cache_read_cost_per_token",
        "cache_creation_cost_per_token",
        "reasoning_cost_per_token",
    )
    @classmethod
    def reject_negative_rates(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < Decimal("0"):
            raise ValueError("pricing values must be non-negative")
        return value

    def base_rates(self) -> TokenRates:
        """Bundle the declared rates for `pricing_tiers` to resolve against."""
        return TokenRates(
            input=self.input_cost_per_token,
            output=self.output_cost_per_token,
            cache_read=self.cache_read_cost_per_token,
            cache_creation=self.cache_creation_cost_per_token,
            reasoning=self.reasoning_cost_per_token,
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

    provider: str | None = None
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
            input_cost = self.input_cost_per_million_tokens / Decimal("1000000")
        if output_cost is None and self.output_cost_per_million_tokens is not None:
            output_cost = self.output_cost_per_million_tokens / Decimal("1000000")

        tiers = parse_tiers(self.tiered_pricing)
        extra = self.model_extra or {}
        thresholds = parse_thresholds(extra)

        has_base_rates = input_cost is not None and output_cost is not None
        if not has_base_rates and not tiers:
            raise ValueError("Missing input/output token pricing fields")

        # Cache and reasoning rates live in model_extra, since they have no
        # declared field on this model.
        aux = parse_base_rates(extra)

        return ModelPricing(
            model=model,
            input_cost_per_token=input_cost,
            output_cost_per_token=output_cost,
            cache_read_cost_per_token=aux.cache_read,
            cache_creation_cost_per_token=aux.cache_creation,
            reasoning_cost_per_token=aux.reasoning,
            thresholds=thresholds,
            tiered_pricing=tiers,
            provider=self.provider,
            currency=self.currency or default_currency,
            last_updated=self.last_updated,
        )
