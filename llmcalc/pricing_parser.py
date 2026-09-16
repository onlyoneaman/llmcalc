"""Deterministic per-entry pricing decoding with structured diagnostics."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from llmcalc.diagnostics import DiagnosticAction, DiagnosticSeverity, PricingDiagnostic
from llmcalc.models import ModelPricing, RawModelPricing
from llmcalc.pricing_tiers import RATE_FIELDS, parse_query_tiers, parse_tiers

_CORE_RATE_FIELDS = {
    "input_cost_per_token",
    "output_cost_per_token",
    "prompt_cost_per_token",
    "completion_cost_per_token",
    "input_cost_per_million_tokens",
    "output_cost_per_million_tokens",
    "input_cost_per_token_cache_hit",
    "input_cost_per_query",
    "google_maps_grounding_cost_per_query",
    "regional_processing_uplift_multiplier_us",
    "regional_processing_uplift_multiplier_eu",
    "regional_endpoint_uplift_multiplier",
    *RATE_FIELDS.values(),
}
_MODE_RATE = re.compile(
    r"^(?:" + "|".join(re.escape(field) for field in RATE_FIELDS.values()) + r")_"
    r"(?:batches|priority|flex)$"
)
_THRESHOLD_RATE = re.compile(
    r"^(?:input_cost_per_token|output_cost_per_token|cache_read_input_token_cost|"
    r"cache_creation_input_token_cost|cache_creation_input_token_cost_above_1hr)"
    r"_above_\d+k?_tokens(?:_(?:batches|priority|flex))?$"
)
_METADATA_FIELDS = ("provider", "litellm_provider", "currency")
_SEARCH_CONTEXT_KEYS = {
    "search_context_size_low",
    "search_context_size_medium",
    "search_context_size_high",
}


def _diagnostic(
    model: str,
    severity: DiagnosticSeverity,
    code: str,
    action: DiagnosticAction,
    path: tuple[str | int, ...],
    message: str,
) -> PricingDiagnostic:
    return PricingDiagnostic(
        model=model,
        severity=severity,
        code=code,
        action=action,
        path=path,
        message=message,
    )


def _valid_decimal(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return False
    return parsed.is_finite() and parsed >= Decimal("0")


def _valid_multiplier(value: Any) -> bool:
    if not _valid_decimal(value):
        return False
    return Decimal(str(value).strip()) > Decimal("0")


def _is_supported_rate(key: str) -> bool:
    return key in _CORE_RATE_FIELDS or _MODE_RATE.fullmatch(key) is not None


def _has_other_supported_pricing(raw: Mapping[str, Any]) -> bool:
    if parse_query_tiers(raw.get("tiered_pricing")):
        return True
    for key, value in raw.items():
        if key == "tiered_pricing":
            continue
        if (_is_supported_rate(key) or _THRESHOLD_RATE.fullmatch(key)) and _valid_decimal(value):
            return True
        if (
            key == "search_context_cost_per_query"
            and isinstance(value, Mapping)
            and any(
                context in _SEARCH_CONTEXT_KEYS and _valid_decimal(rate)
                for context, rate in value.items()
            )
        ):
            return True
    return False


def _unsupported_cost_field(key: str) -> bool:
    return (
        "cost" in key
        and key not in {"search_context_cost_per_query"}
        and not _is_supported_rate(key)
        and _THRESHOLD_RATE.fullmatch(key) is None
    )


def inspect_model_pricing(
    model: str,
    model_data: Mapping[str, Any],
    default_currency: str,
) -> tuple[ModelPricing | None, tuple[PricingDiagnostic, ...]]:
    diagnostics: list[PricingDiagnostic] = []
    sanitized = dict(model_data)

    for field in _METADATA_FIELDS:
        value = sanitized.get(field)
        if value is not None and not isinstance(value, str):
            return None, (
                _diagnostic(
                    model,
                    "error",
                    "invalid_metadata",
                    "skipped_entry",
                    (field,),
                    "pricing metadata must use the expected type",
                ),
            )

    last_updated = sanitized.get("last_updated")
    if last_updated is not None and not isinstance(last_updated, str):
        diagnostics.append(
            _diagnostic(
                model,
                "warning",
                "invalid_metadata",
                "ignored_field",
                ("last_updated",),
                "last_updated must be a string",
            )
        )
        sanitized.pop("last_updated")

    provider_specific = sanitized.get("provider_specific_entry")
    if isinstance(provider_specific, Mapping):
        cleaned_provider_specific = dict(provider_specific)
        for field in ("us", "fast"):
            value = cleaned_provider_specific.get(field)
            if value is not None and not _valid_multiplier(value):
                diagnostics.append(
                    _diagnostic(
                        model,
                        "warning",
                        "invalid_rate",
                        "ignored_field",
                        ("provider_specific_entry", field),
                        "provider pricing multiplier must be a finite positive decimal",
                    )
                )
                cleaned_provider_specific.pop(field)
        sanitized["provider_specific_entry"] = cleaned_provider_specific

    for key, value in tuple(sanitized.items()):
        if _THRESHOLD_RATE.fullmatch(key) is not None and not _valid_decimal(value):
            diagnostics.append(
                _diagnostic(
                    model,
                    "warning",
                    "invalid_threshold_rate",
                    "ignored_field",
                    (key,),
                    "long-context pricing rate is malformed",
                )
            )
            sanitized.pop(key)
        elif _is_supported_rate(key) and not _valid_decimal(value):
            return None, (
                *diagnostics,
                _diagnostic(
                    model,
                    "error",
                    "invalid_rate",
                    "skipped_entry",
                    (key,),
                    "supported pricing rate must be a finite non-negative decimal",
                ),
            )

    raw_tiers = sanitized.get("tiered_pricing")
    has_range_tiers = isinstance(raw_tiers, (list, tuple)) and any(
        isinstance(entry, Mapping) and "range" in entry for entry in raw_tiers
    )
    has_query_tiers = isinstance(raw_tiers, (list, tuple)) and any(
        isinstance(entry, Mapping) and "max_results_range" in entry
        for entry in raw_tiers
    )
    invalid_tiers = (has_range_tiers and not parse_tiers(raw_tiers)) or (
        has_query_tiers and not parse_query_tiers(raw_tiers)
    )
    if invalid_tiers:
        other_pricing = _has_other_supported_pricing(sanitized)
        diagnostic = _diagnostic(
            model,
            "warning" if other_pricing else "error",
            "invalid_tier_schedule",
            "ignored_field" if other_pricing else "skipped_entry",
            ("tiered_pricing",),
            "request-tier pricing schedule is malformed",
        )
        if not other_pricing:
            return None, (*diagnostics, diagnostic)
        diagnostics.append(diagnostic)
        sanitized.pop("tiered_pricing")

    try:
        raw_model = RawModelPricing.model_validate(sanitized)
        pricing = raw_model.to_model_pricing(model, default_currency=default_currency)
    except ValidationError:
        return None, (
            *diagnostics,
            _diagnostic(
                model,
                "error",
                "invalid_metadata",
                "skipped_entry",
                (),
                "pricing entry does not match the supported schema",
            ),
        )
    except ValueError as error:
        if str(error) != "Missing supported pricing fields":
            raise
        has_cost_field = any("cost" in key for key in sanitized)
        return None, (
            *diagnostics,
            _diagnostic(
                model,
                "info",
                "unsupported_pricing_unit" if has_cost_field else "missing_supported_pricing",
                "skipped_entry",
                (),
                (
                    "entry uses pricing units that llmcalc does not support"
                    if has_cost_field
                    else "entry has no supported pricing fields"
                ),
            ),
        )
    for key in sanitized:
        if _unsupported_cost_field(key):
            diagnostics.append(
                _diagnostic(
                    model,
                    "info",
                    "unsupported_pricing_unit",
                    "ignored_field",
                    (key,),
                    "pricing field uses a billing unit that llmcalc does not support",
                )
            )
    return pricing, tuple(diagnostics)
