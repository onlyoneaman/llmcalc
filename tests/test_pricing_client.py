import traceback
from decimal import Decimal

import pytest

from llmcalc.errors import PricingFetchError, PricingSchemaError
from llmcalc.pricing_client import (
    fetch_pricing_payload,
    get_pricing_table,
    parse_pricing_payload,
)


def test_parse_pricing_payload_direct_table() -> None:
    payload = {
        "gpt-5.1": {
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000002",
        }
    }

    table = parse_pricing_payload(payload)
    assert table["gpt-5.1"].input_cost_per_token == Decimal("0.000001")


def test_parse_pricing_payload_wrapped_table() -> None:
    payload = {
        "data": {
            "gpt-5.1": {
                "input_cost_per_million_tokens": "2",
                "output_cost_per_million_tokens": "4",
            }
        }
    }

    table = parse_pricing_payload(payload)
    assert table["gpt-5.1"].output_cost_per_token == Decimal("0.000004")


def test_parse_pricing_payload_raises_for_invalid() -> None:
    with pytest.raises(PricingSchemaError):
        parse_pricing_payload({"meta": {"foo": "bar"}})


def test_parse_pricing_payload_defaults_to_usd_despite_env(monkeypatch) -> None:
    monkeypatch.setenv("LLMCALC_CURRENCY", "inr")
    payload = {
        "gpt-5.1": {
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000002",
        }
    }

    table = parse_pricing_payload(payload)
    assert table["gpt-5.1"].currency == "USD"


def test_parse_pricing_payload_prefers_payload_currency_over_env(monkeypatch) -> None:
    monkeypatch.setenv("LLMCALC_CURRENCY", "inr")
    payload = {
        "gpt-5.1": {
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000002",
            "currency": "USD",
        }
    }

    table = parse_pricing_payload(payload)
    assert table["gpt-5.1"].currency == "USD"


@pytest.mark.asyncio
async def test_fetch_error_does_not_expose_pricing_url_secret(monkeypatch) -> None:
    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, source: str):
            raise ValueError(source)

    monkeypatch.setattr(
        "llmcalc.pricing_client.httpx.AsyncClient",
        lambda **_kwargs: FailingClient(),
    )
    credential = "super-private-credential-7f4c2b"
    secret = f"https://example.com/prices.json?token={credential}"

    with pytest.raises(PricingFetchError) as caught:
        await fetch_pricing_payload(secret)

    assert credential not in str(caught.value)
    assert str(caught.value) == "failed to fetch pricing data"
    assert credential not in "".join(traceback.format_exception(caught.value))


@pytest.mark.asyncio
async def test_get_pricing_table_uses_cache(monkeypatch) -> None:
    cached = {
        "gpt-5.1": {
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000002",
        }
    }

    monkeypatch.setattr(
        "llmcalc.pricing_client.load_cached_pricing", lambda *_args, **_kwargs: cached
    )

    async def _never_fetch(pricing_url=None):
        _ = pricing_url
        raise AssertionError("fetch should not be called when cache is valid")

    monkeypatch.setattr("llmcalc.pricing_client.fetch_pricing_payload", _never_fetch)

    table = await get_pricing_table(cache_timeout=3600)
    assert "gpt-5.1" in table


@pytest.mark.asyncio
async def test_get_pricing_table_fetches_and_saves(monkeypatch) -> None:
    saved = {"payload": None}

    monkeypatch.setattr(
        "llmcalc.pricing_client.load_cached_pricing", lambda *_args, **_kwargs: None
    )

    async def _fetch(pricing_url=None):
        _ = pricing_url
        return {
            "gpt-5.1": {
                "input_cost_per_token": "0.000001",
                "output_cost_per_token": "0.000002",
            }
        }

    monkeypatch.setattr("llmcalc.pricing_client.fetch_pricing_payload", _fetch)
    monkeypatch.setattr(
        "llmcalc.pricing_client.save_cached_pricing",
        lambda payload, **_kwargs: saved.update(payload=payload),
    )

    table = await get_pricing_table(cache_timeout=3600)
    assert "gpt-5.1" in table
    assert saved["payload"] is not None


@pytest.mark.asyncio
async def test_get_pricing_table_raises_when_fetch_fails_without_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        "llmcalc.pricing_client.load_cached_pricing", lambda *_args, **_kwargs: None
    )

    async def _fetch(pricing_url=None):
        _ = pricing_url
        raise PricingFetchError("failed")

    monkeypatch.setattr("llmcalc.pricing_client.fetch_pricing_payload", _fetch)

    with pytest.raises(PricingFetchError):
        await get_pricing_table(cache_timeout=3600)


@pytest.mark.asyncio
async def test_get_pricing_table_does_not_use_expired_cache(monkeypatch) -> None:
    load_ages: list[int | None] = []

    def _load(max_age_seconds, **_kwargs):
        load_ages.append(max_age_seconds)
        return None

    async def _fetch(pricing_url=None):
        _ = pricing_url
        raise PricingFetchError("failed")

    monkeypatch.setattr("llmcalc.pricing_client.load_cached_pricing", _load)
    monkeypatch.setattr("llmcalc.pricing_client.fetch_pricing_payload", _fetch)

    with pytest.raises(PricingFetchError):
        await get_pricing_table(cache_timeout=3600)
    assert load_ages == [3600]


@pytest.mark.asyncio
async def test_get_pricing_table_uses_env_currency_only_for_custom_source(monkeypatch) -> None:
    payload = {
        "gpt-5.1": {
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000002",
        }
    }

    async def _fetch(pricing_url=None):
        _ = pricing_url
        return payload

    monkeypatch.setenv("LLMCALC_CURRENCY", "inr")
    monkeypatch.setattr(
        "llmcalc.pricing_client.load_cached_pricing", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr("llmcalc.pricing_client.fetch_pricing_payload", _fetch)
    monkeypatch.setattr(
        "llmcalc.pricing_client.save_cached_pricing", lambda *_args, **_kwargs: None
    )

    default_table = await get_pricing_table(cache_timeout=3600)
    custom_table = await get_pricing_table(
        cache_timeout=3600,
        pricing_url="https://example.com/pricing.json",
    )

    assert default_table["gpt-5.1"].currency == "USD"
    assert custom_table["gpt-5.1"].currency == "INR"


@pytest.mark.asyncio
async def test_get_pricing_table_ignores_cache_write_failure(monkeypatch) -> None:
    payload = {
        "gpt-5.1": {
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000002",
        }
    }

    async def _fetch(pricing_url=None):
        _ = pricing_url
        return payload

    def _fail_save(*_args, **_kwargs):
        raise OSError("read-only cache directory")

    monkeypatch.setattr(
        "llmcalc.pricing_client.load_cached_pricing", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr("llmcalc.pricing_client.fetch_pricing_payload", _fetch)
    monkeypatch.setattr("llmcalc.pricing_client.save_cached_pricing", _fail_save)

    table = await get_pricing_table(cache_timeout=3600)
    assert "gpt-5.1" in table
