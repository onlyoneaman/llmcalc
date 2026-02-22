"""Pydantic models for pricing and cost breakdown data."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CostBreakdown(BaseModel):
    """Cost result for a token usage calculation."""

    input_cost: Decimal = Field(ge=Decimal("0"))
    output_cost: Decimal = Field(ge=Decimal("0"))
    total_cost: Decimal = Field(ge=Decimal("0"))
    currency: str = "USD"

    model_config = ConfigDict(frozen=True)


class ModelPricing(BaseModel):
    """Normalized token pricing for one model."""

    model: str
    input_cost_per_token: Decimal = Field(ge=Decimal("0"))
    output_cost_per_token: Decimal = Field(ge=Decimal("0"))
    provider: str | None = None
    currency: str = "USD"
    last_updated: str | None = None

    model_config = ConfigDict(frozen=True)


class RawModelPricing(BaseModel):
    """Flexible upstream schema model from llmlite pricing JSON."""

    input_cost_per_token: Decimal | None = None
    output_cost_per_token: Decimal | None = None

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

        if input_cost is None or output_cost is None:
            raise ValueError("Missing input/output token pricing fields")

        return ModelPricing(
            model=model,
            input_cost_per_token=input_cost,
            output_cost_per_token=output_cost,
            provider=self.provider,
            currency=self.currency or default_currency,
            last_updated=self.last_updated,
        )
