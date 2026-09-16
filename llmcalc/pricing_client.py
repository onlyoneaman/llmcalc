"""Pricing data fetch and normalization against litellm pricing source."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from typing import Any

import httpx

from llmcalc.cache import load_cached_pricing, save_cached_pricing
from llmcalc.config import (
    DEFAULT_CACHE_TIMEOUT_SECONDS,
    DEFAULT_CURRENCY,
    DEFAULT_PRICING_URL,
    get_default_currency,
    get_pricing_url,
    get_user_agent,
)
from llmcalc.diagnostics import PricingDiagnostic, PricingParseResult
from llmcalc.errors import PricingFetchError, PricingSchemaError
from llmcalc.models import ModelPricing
from llmcalc.pricing_history import get_historical_pricing_payload
from llmcalc.pricing_parser import inspect_model_pricing


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
    except (httpx.HTTPError, ValueError):
        raise PricingFetchError("failed to fetch pricing data") from None

    if not isinstance(payload, dict):
        raise PricingSchemaError("pricing payload must be a JSON object")

    return payload


def parse_pricing_payload(
    payload: Mapping[str, Any],
    *,
    default_currency: str = DEFAULT_CURRENCY,
) -> dict[str, ModelPricing]:
    """Parse raw pricing JSON into normalized `ModelPricing` objects."""
    return parse_pricing_payload_with_diagnostics(
        payload,
        default_currency=default_currency,
    ).models


def parse_pricing_payload_with_diagnostics(
    payload: Mapping[str, Any],
    *,
    default_currency: str = DEFAULT_CURRENCY,
    strict: bool = False,
) -> PricingParseResult:
    """Parse pricing JSON and report every excluded or sanitized entry."""
    raw_table: Mapping[str, Any]

    wrapped_data = payload.get("data")
    raw_table = wrapped_data if isinstance(wrapped_data, Mapping) else payload

    parsed: dict[str, ModelPricing] = {}
    diagnostics: list[PricingDiagnostic] = []
    for model_name, model_data in raw_table.items():
        if not isinstance(model_name, str):
            continue
        if model_name == "sample_spec":
            diagnostics.append(
                PricingDiagnostic(
                    model=model_name,
                    severity="info",
                    code="excluded_metadata_entry",
                    action="skipped_entry",
                    path=(),
                    message="known pricing schema example was excluded",
                )
            )
            continue
        if not isinstance(model_data, Mapping):
            diagnostics.append(
                PricingDiagnostic(
                    model=model_name,
                    severity="error",
                    code="entry_not_object",
                    action="skipped_entry",
                    path=(),
                    message="pricing entry must be an object",
                )
            )
            continue

        pricing, entry_diagnostics = inspect_model_pricing(
            model_name,
            model_data,
            default_currency,
        )
        diagnostics.extend(entry_diagnostics)
        if pricing is not None:
            parsed[model_name] = pricing

    if not parsed:
        raise PricingSchemaError(
            "no valid model pricing entries found",
            tuple(diagnostics),
        )
    if strict and any(item.severity in {"warning", "error"} for item in diagnostics):
        raise PricingSchemaError(
            "pricing payload contains invalid entries",
            tuple(diagnostics),
        )

    return PricingParseResult(parsed, tuple(diagnostics))


async def get_pricing_report(
    cache_timeout: int = DEFAULT_CACHE_TIMEOUT_SECONDS,
    pricing_url: str | None = None,
    snapshot_at: str | None = None,
    *,
    strict: bool = False,
) -> PricingParseResult:
    """Get pricing models plus deterministic parser diagnostics."""
    source = get_pricing_url(pricing_url)
    default_currency = get_default_currency() if source != DEFAULT_PRICING_URL else DEFAULT_CURRENCY
    if snapshot_at is not None:
        if source != DEFAULT_PRICING_URL:
            raise ValueError(
                "snapshot_at is only supported with the default LiteLLM pricing source"
            )
        historical = await get_historical_pricing_payload(snapshot_at)
        return parse_pricing_payload_with_diagnostics(
            historical,
            default_currency=DEFAULT_CURRENCY,
            strict=strict,
        )

    cached_data = load_cached_pricing(cache_timeout, source_url=source)
    if cached_data is not None:
        try:
            return parse_pricing_payload_with_diagnostics(
                cached_data,
                default_currency=default_currency,
                strict=strict,
            )
        except PricingSchemaError:
            if strict:
                raise

    fetched_payload = await fetch_pricing_payload(pricing_url=source)
    report = parse_pricing_payload_with_diagnostics(
        fetched_payload,
        default_currency=default_currency,
        strict=strict,
    )
    with suppress(OSError, TypeError, ValueError):
        save_cached_pricing(fetched_payload, source_url=source)
    return report


async def get_pricing_table(
    cache_timeout: int = DEFAULT_CACHE_TIMEOUT_SECONDS,
    pricing_url: str | None = None,
    snapshot_at: str | None = None,
) -> dict[str, ModelPricing]:
    """Get model pricing table using cache-first strategy with remote refresh fallback."""
    report = await get_pricing_report(
        cache_timeout=cache_timeout,
        pricing_url=pricing_url,
        snapshot_at=snapshot_at,
    )
    return report.models
