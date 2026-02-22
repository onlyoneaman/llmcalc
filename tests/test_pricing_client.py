from decimal import Decimal

import pytest

from llmcalc.errors import PricingFetchError, PricingSchemaError
from llmcalc.pricing_client import get_pricing_table, parse_pricing_payload


def test_parse_pricing_payload_direct_table() -> None:
    payload = {
        "gpt-4o-mini": {
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000002",
        }
    }

    table = parse_pricing_payload(payload)
    assert table["gpt-4o-mini"].input_cost_per_token == Decimal("0.000001")


def test_parse_pricing_payload_wrapped_table() -> None:
    payload = {
        "data": {
            "gpt-4o-mini": {
                "input_cost_per_million_tokens": "2",
                "output_cost_per_million_tokens": "4",
            }
        }
    }

    table = parse_pricing_payload(payload)
    assert table["gpt-4o-mini"].output_cost_per_token == Decimal("0.000004")


def test_parse_pricing_payload_raises_for_invalid() -> None:
    with pytest.raises(PricingSchemaError):
        parse_pricing_payload({"meta": {"foo": "bar"}})


def test_parse_pricing_payload_uses_env_currency_fallback(monkeypatch) -> None:
    monkeypatch.setenv("LLMCALC_CURRENCY", "inr")
    payload = {
        "gpt-4o-mini": {
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000002",
        }
    }

    table = parse_pricing_payload(payload)
    assert table["gpt-4o-mini"].currency == "INR"


def test_parse_pricing_payload_prefers_payload_currency_over_env(monkeypatch) -> None:
    monkeypatch.setenv("LLMCALC_CURRENCY", "inr")
    payload = {
        "gpt-4o-mini": {
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000002",
            "currency": "USD",
        }
    }

    table = parse_pricing_payload(payload)
    assert table["gpt-4o-mini"].currency == "USD"


@pytest.mark.asyncio
async def test_get_pricing_table_uses_cache(monkeypatch) -> None:
    cached = {
        "gpt-4o-mini": {
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000002",
        }
    }

    monkeypatch.setattr("llmcalc.pricing_client.load_cached_pricing", lambda _: cached)

    async def _never_fetch(pricing_url=None):
        _ = pricing_url
        raise AssertionError("fetch should not be called when cache is valid")

    monkeypatch.setattr("llmcalc.pricing_client.fetch_pricing_payload", _never_fetch)

    table = await get_pricing_table(cache_timeout=3600)
    assert "gpt-4o-mini" in table


@pytest.mark.asyncio
async def test_get_pricing_table_fetches_and_saves(monkeypatch) -> None:
    saved = {"payload": None}

    monkeypatch.setattr("llmcalc.pricing_client.load_cached_pricing", lambda _: None)

    async def _fetch(pricing_url=None):
        _ = pricing_url
        return {
            "gpt-4o-mini": {
                "input_cost_per_token": "0.000001",
                "output_cost_per_token": "0.000002",
            }
        }

    monkeypatch.setattr("llmcalc.pricing_client.fetch_pricing_payload", _fetch)
    monkeypatch.setattr(
        "llmcalc.pricing_client.save_cached_pricing",
        lambda payload: saved.update(payload=payload),
    )

    table = await get_pricing_table(cache_timeout=3600)
    assert "gpt-4o-mini" in table
    assert saved["payload"] is not None


@pytest.mark.asyncio
async def test_get_pricing_table_raises_when_fetch_fails_without_cache(monkeypatch) -> None:
    monkeypatch.setattr("llmcalc.pricing_client.load_cached_pricing", lambda _: None)

    async def _fetch(pricing_url=None):
        _ = pricing_url
        raise PricingFetchError("failed")

    monkeypatch.setattr("llmcalc.pricing_client.fetch_pricing_payload", _fetch)

    with pytest.raises(PricingFetchError):
        await get_pricing_table(cache_timeout=3600)
