import pytest

from llmcalc.config import DEFAULT_PRICING_URL
from llmcalc.pricing_client import fetch_pricing_payload, parse_pricing_payload


def test_default_pricing_url_points_at_litellm() -> None:
    assert DEFAULT_PRICING_URL == (
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    )


@pytest.mark.network
async def test_default_pricing_url_is_fetchable_and_parses() -> None:
    payload = await fetch_pricing_payload()
    table = parse_pricing_payload(payload)

    assert "gpt-4o" in table
    assert "gpt-5.5" in table
    assert len(table) > 2000
