from decimal import Decimal

import pytest

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


def test_tiered_model_without_base_rates_is_priceable() -> None:
    raw = RawModelPricing.model_validate(
        {
            "tiered_pricing": [
                {
                    "range": [0, 256000],
                    "input_cost_per_token": 5e-08,
                    "output_cost_per_token": 4e-07,
                }
            ],
            "litellm_provider": "dashscope",
        }
    )
    pricing = raw.to_model_pricing("dashscope/qwen3-max")

    assert pricing.input_cost_per_token is None
    assert pricing.output_cost_per_token is None
    assert len(pricing.tiered_pricing) == 1


def test_threshold_fields_are_parsed_and_sorted() -> None:
    raw = RawModelPricing.model_validate(
        {
            "input_cost_per_token": 5e-06,
            "output_cost_per_token": 3e-05,
            "input_cost_per_token_above_272k_tokens": 1e-05,
            "output_cost_per_token_above_272k_tokens": 4.5e-05,
        }
    )
    pricing = raw.to_model_pricing("gpt-5.5")

    assert [t.threshold for t in pricing.thresholds] == [272000]
    assert pricing.thresholds[0].key == "above_272k_tokens"


def test_model_with_no_pricing_at_all_is_rejected() -> None:
    with pytest.raises(ValueError, match="Missing input/output token pricing"):
        RawModelPricing.model_validate({"litellm_provider": "dashscope"}).to_model_pricing("x")


def test_query_priced_tiers_do_not_make_a_model_priceable() -> None:
    with pytest.raises(ValueError, match="Missing input/output token pricing"):
        RawModelPricing.model_validate(
            {"tiered_pricing": [{"input_cost_per_query": 0.005, "max_results_range": [0, 25]}]}
        ).to_model_pricing("exa_ai/search")


def test_corrupt_thresholds_fall_back_to_base_rates_without_raising() -> None:
    raw = RawModelPricing.model_validate(
        {
            "input_cost_per_token": 5e-06,
            "output_cost_per_token": 3e-05,
            "input_cost_per_token_above_abc_tokens": "not-a-number",
        }
    )
    pricing = raw.to_model_pricing("gpt-5.5")

    assert pricing.thresholds == ()
    assert pricing.input_cost_per_token == Decimal("0.000005")


def test_base_rate_only_model_is_unchanged() -> None:
    pricing = RawModelPricing.model_validate(
        {"input_cost_per_token": 2.5e-06, "output_cost_per_token": 1e-05}
    ).to_model_pricing("gpt-4o")

    assert pricing.input_cost_per_token == Decimal("0.0000025")
    assert pricing.thresholds == ()
    assert pricing.tiered_pricing == ()
