"""Pydantic models for pricing and cost breakdown data."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llmcalc.pricing_tiers import (
    PricingThreshold,
    PricingTier,
    parse_thresholds,
    parse_tiers,
)


class CostBreakdown(BaseModel):
    """Cost result for a token usage calculation."""

    input_cost: Decimal = Field(ge=Decimal("0"))
    output_cost: Decimal = Field(ge=Decimal("0"))
    total_cost: Decimal = Field(ge=Decimal("0"))
    currency: str = "USD"
    tier_applied: str | None = None

    model_config = ConfigDict(frozen=True)


class ModelPricing(BaseModel):
    """Normalized token pricing for one model.

    Base rates are optional: models priced purely through `tiered_pricing`
    publish no flat per-token rate at all.
    """

    model: str
    input_cost_per_token: Decimal | None = None
    output_cost_per_token: Decimal | None = None
    thresholds: tuple[PricingThreshold, ...] = ()
    tiered_pricing: tuple[PricingTier, ...] = ()
    provider: str | None = None
    currency: str = "USD"
    last_updated: str | None = None

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    @field_validator("input_cost_per_token", "output_cost_per_token")
    @classmethod
    def reject_negative_rates(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < Decimal("0"):
            raise ValueError("pricing values must be non-negative")
        return value


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
        thresholds = parse_thresholds(self.model_extra or {})

        has_base_rates = input_cost is not None and output_cost is not None
        if not has_base_rates and not tiers:
            raise ValueError("Missing input/output token pricing fields")

        return ModelPricing(
            model=model,
            input_cost_per_token=input_cost,
            output_cost_per_token=output_cost,
            thresholds=thresholds,
            tiered_pricing=tiers,
            provider=self.provider,
            currency=self.currency or default_currency,
            last_updated=self.last_updated,
        )
