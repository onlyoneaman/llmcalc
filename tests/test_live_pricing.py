from decimal import Decimal

import pytest

from llmcalc.api import cost_async
from llmcalc.config import DEFAULT_PRICING_URL
from llmcalc.pricing_client import (
    fetch_pricing_payload,
    parse_pricing_payload,
    parse_pricing_payload_with_diagnostics,
)
from llmcalc.pricing_history import get_historical_pricing_payload
from llmcalc.pricing_tiers import RATE_FIELDS


def test_default_pricing_url_points_at_litellm() -> None:
    assert DEFAULT_PRICING_URL == (
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    )


@pytest.mark.network
async def test_fixed_historical_snapshot_is_fetchable() -> None:
    payload = await get_historical_pricing_payload("2024-01-01")

    assert "gpt-3.5-turbo" in payload
    assert len(payload) > 100


@pytest.mark.network
async def test_default_pricing_url_is_fetchable_and_parses() -> None:
    payload = await fetch_pricing_payload()
    table = parse_pricing_payload(payload)
    report = parse_pricing_payload_with_diagnostics(payload, strict=True)

    assert report.models == table
    assert all(item.severity == "info" for item in report.diagnostics)
    assert "gpt-4o" in table
    assert "gpt-5.5" in table
    assert len(table) > 2000
    assert all(pricing.provider for pricing in table.values())

    range_models = {
        name
        for name, raw in payload.items()
        if isinstance(name, str)
        and isinstance(raw, dict)
        and isinstance(raw.get("tiered_pricing"), list)
        and any(
            isinstance(tier, dict) and "range" in tier
            for tier in raw["tiered_pricing"]
        )
    }
    missing_tiers = sorted(
        name
        for name in range_models
        if name not in table or not table[name].tiered_pricing
    )
    assert not missing_tiers

    assert any(pricing.thresholds for pricing in table.values())
    assert any(pricing.cache_read_cost_per_token is not None for pricing in table.values())
    assert any(
        pricing.input_cost_per_token is not None
        and pricing.output_cost_per_token is None
        for pricing in table.values()
    )

    raw_models = {
        name: raw
        for name, raw in payload.items()
        if isinstance(name, str) and name != "sample_spec" and isinstance(raw, dict)
    }
    for mode, suffix in {
        "batch": "_batches",
        "priority": "_priority",
        "flex": "_flex",
    }.items():
        declared = {
            name
            for name, raw in raw_models.items()
            if any(f"{field}{suffix}" in raw for field in RATE_FIELDS.values())
        }
        assert declared
        assert not sorted(
            name
            for name in declared
            if name not in table or mode not in table[name].pricing_modes
        )

    direct_rates = {
        "cache_creation_input_token_cost_above_1hr": "cache_creation_1h_cost_per_token",
        "cache_creation_input_audio_token_cost": "cache_creation_audio_cost_per_token",
        "input_cost_per_audio_token": "input_audio_cost_per_token",
        "output_cost_per_audio_token": "output_audio_cost_per_token",
        "input_cost_per_image_token": "input_image_cost_per_token",
        "output_cost_per_image_token": "output_image_cost_per_token",
        "input_cost_per_query": "input_cost_per_query",
        "google_maps_grounding_cost_per_query": "google_maps_grounding_cost_per_query",
    }
    for raw_field, normalized_field in direct_rates.items():
        declared = {name for name, raw in raw_models.items() if raw.get(raw_field) is not None}
        assert declared
        assert not sorted(
            name
            for name in declared
            if name not in table or getattr(table[name], normalized_field) is None
        )

    one_hour_threshold_models = {
        name
        for name, raw in raw_models.items()
        if any(
            key.startswith("cache_creation_input_token_cost_above_1hr_above_")
            for key in raw
        )
    }
    assert one_hour_threshold_models
    assert not sorted(
        name
        for name in one_hour_threshold_models
        if name not in table
        or not any(
            threshold.rates.cache_creation_1h is not None
            for threshold in table[name].thresholds
        )
    )

    search_models = {
        name
        for name, raw in raw_models.items()
        if isinstance(raw.get("search_context_cost_per_query"), dict)
    }
    assert search_models
    assert not sorted(
        name
        for name in search_models
        if name not in table or not table[name].search_context_cost_per_query
    )

    for region in ("us", "eu"):
        field = f"regional_processing_uplift_multiplier_{region}"
        declared = {name for name, raw in raw_models.items() if raw.get(field) is not None}
        assert declared
        assert not sorted(
            name
            for name in declared
            if name not in table or region not in table[name].regional_processing_uplift
        )

    query_tier_models = {
        name
        for name, raw in raw_models.items()
        if isinstance(raw.get("tiered_pricing"), list)
        and any(
            isinstance(tier, dict) and "max_results_range" in tier
            for tier in raw["tiered_pricing"]
        )
    }
    assert query_tier_models
    assert not sorted(
        name
        for name in query_tier_models
        if name not in table or not table[name].query_pricing
    )

    regional_models = {
        name
        for name, raw in raw_models.items()
        if raw.get("regional_endpoint_uplift_multiplier") is not None
    }
    assert regional_models
    assert not sorted(
        name
        for name in regional_models
        if name not in table or "regional" not in table[name].regional_processing_uplift
    )

    provider_us_models = {
        name
        for name, raw in raw_models.items()
        if isinstance(raw.get("provider_specific_entry"), dict)
        and raw["provider_specific_entry"].get("us") is not None
    }
    assert provider_us_models
    assert not sorted(
        name
        for name in provider_us_models
        if name not in table or "us" not in table[name].regional_processing_uplift
    )

    provider_fast_models = {
        name
        for name, raw in raw_models.items()
        if isinstance(raw.get("provider_specific_entry"), dict)
        and raw["provider_specific_entry"].get("fast") is not None
    }
    assert provider_fast_models
    assert not sorted(
        name
        for name in provider_fast_models
        if name not in table or "priority" not in table[name].pricing_modes
    )

    batch_long = await cost_async(
        "claude-sonnet-4-5-20250929-v1:0",
        200_001,
        1_000,
        processing_mode="batch",
    )
    assert batch_long is not None
    assert batch_long.total_cost == Decimal("0.611253")

    query_tier = await cost_async(
        "exa_ai/search", 0, 0, query_count=2, query_results=26
    )
    assert query_tier is not None
    assert query_tier.query_cost == Decimal("0.05")

    audio_cache = await cost_async(
        "gpt-realtime",
        10,
        0,
        cache_creation_tokens=10,
        cache_creation_audio_tokens=10,
        input_audio_tokens=10,
    )
    assert audio_cache is not None
    assert audio_cache.cache_creation_audio_cost == Decimal("0.000004")
