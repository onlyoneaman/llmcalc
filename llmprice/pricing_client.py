"""Pricing data fetch and normalization against llmlite pricing source."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from llmprice.cache import load_cached_pricing, save_cached_pricing
from llmprice.config import (
    DEFAULT_CACHE_TIMEOUT_SECONDS,
    get_default_currency,
    get_pricing_url,
    get_user_agent,
)
from llmprice.errors import PricingFetchError, PricingSchemaError
from llmprice.models import ModelPricing, RawModelPricing


async def fetch_pricing_payload(pricing_url: str | None = None) -> dict[str, Any]:
    """Fetch pricing payload from configured remote source."""
    source = get_pricing_url(pricing_url)

    try:
        async with httpx.AsyncClient(
            timeout=10,
            headers={"User-Agent": get_user_agent()},
        ) as client:
            response = await client.get(source)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PricingFetchError(f"failed to fetch pricing data from {source}") from exc

    if not isinstance(payload, dict):
        raise PricingSchemaError("pricing payload must be a JSON object")

    return payload


def parse_pricing_payload(payload: Mapping[str, Any]) -> dict[str, ModelPricing]:
    """Parse raw pricing JSON into normalized `ModelPricing` objects."""
    raw_table: Mapping[str, Any]
    default_currency = get_default_currency()

    wrapped_data = payload.get("data")
    raw_table = wrapped_data if isinstance(wrapped_data, Mapping) else payload

    parsed: dict[str, ModelPricing] = {}
    for model_name, model_data in raw_table.items():
        if not isinstance(model_name, str) or not isinstance(model_data, Mapping):
            continue

        try:
            raw_model = RawModelPricing.model_validate(model_data)
            parsed[model_name] = raw_model.to_model_pricing(
                model_name,
                default_currency=default_currency,
            )
        except Exception:
            # Some payloads contain non-pricing metadata entries; skip them.
            continue

    if not parsed:
        raise PricingSchemaError("no valid model pricing entries found")

    return parsed


async def get_pricing_table(
    cache_timeout: int = DEFAULT_CACHE_TIMEOUT_SECONDS,
    pricing_url: str | None = None,
) -> dict[str, ModelPricing]:
    """Get model pricing table using cache-first strategy with remote refresh fallback."""
    cached_data = load_cached_pricing(cache_timeout)
    if cached_data is not None:
        try:
            return parse_pricing_payload(cached_data)
        except PricingSchemaError:
            pass

    try:
        fetched_payload = await fetch_pricing_payload(pricing_url=pricing_url)
    except PricingFetchError:
        if cached_data is not None:
            return parse_pricing_payload(cached_data)
        raise

    parsed = parse_pricing_payload(fetched_payload)
    save_cached_pricing(fetched_payload)
    return parsed
