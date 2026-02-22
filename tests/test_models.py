from decimal import Decimal

from llmcalc.models import RawModelPricing


def test_raw_model_pricing_from_alias_fields() -> None:
    raw = RawModelPricing(
        prompt_cost_per_token="0.000001",
        completion_cost_per_token="0.000002",
        provider="openai",
    )

    model = raw.to_model_pricing("gpt-5.1")
    assert model.input_cost_per_token == Decimal("0.000001")
    assert model.output_cost_per_token == Decimal("0.000002")
    assert model.provider == "openai"


def test_raw_model_pricing_from_per_million_fields() -> None:
    raw = RawModelPricing(
        input_cost_per_million_tokens="2",
        output_cost_per_million_tokens="4",
    )

    model = raw.to_model_pricing("gpt-5.1")
    assert model.input_cost_per_token == Decimal("0.000002")
    assert model.output_cost_per_token == Decimal("0.000004")
