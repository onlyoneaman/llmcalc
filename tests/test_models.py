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


def test_empty_litellm_provider_falls_back_to_provider() -> None:
    raw = RawModelPricing(
        input_cost_per_token="0.000001",
        litellm_provider="",
        provider="openai",
    )

    assert raw.to_model_pricing("model").provider == "openai"


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
    assert pricing.provider == "dashscope"
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
    with pytest.raises(ValueError, match="Missing supported pricing fields"):
        RawModelPricing.model_validate({"litellm_provider": "dashscope"}).to_model_pricing("x")


def test_model_with_only_mode_pricing_is_priceable() -> None:
    pricing = RawModelPricing.model_validate(
        {"input_cost_per_token_batches": "0.01"}
    ).to_model_pricing("batch-only")

    assert pricing.input_cost_per_token is None
    assert pricing.pricing_modes["batch"].rates.input == Decimal("0.01")


def test_model_with_only_cache_pricing_is_priceable() -> None:
    pricing = RawModelPricing.model_validate(
        {"cache_read_input_token_cost": "0.001"}
    ).to_model_pricing("cache-only")

    assert pricing.input_cost_per_token is None
    assert pricing.cache_read_cost_per_token == Decimal("0.001")


@pytest.mark.parametrize("value", [True, [], {}, ""])
def test_malformed_declared_rates_reject_the_model_atomically(value: object) -> None:
    with pytest.raises(ValueError):
        RawModelPricing.model_validate(
            {
                "input_cost_per_token": value,
                "output_cost_per_token": "0.000001",
            }
        ).to_model_pricing("x")

    with pytest.raises(ValueError):
        RawModelPricing.model_validate(
            {
                "input_cost_per_token": "0.000001",
                "output_cost_per_token": "0.000002",
                "prompt_cost_per_token": value,
            }
        ).to_model_pricing("x")


def test_input_only_token_model_is_priceable() -> None:
    pricing = RawModelPricing.model_validate(
        {"input_cost_per_token": "0.0000001", "litellm_provider": "mistral"}
    ).to_model_pricing("mistral/mistral-embed")

    assert pricing.input_cost_per_token == Decimal("0.0000001")
    assert pricing.output_cost_per_token is None


def test_query_priced_tiers_make_a_model_priceable() -> None:
    pricing = RawModelPricing.model_validate(
        {"tiered_pricing": [{"input_cost_per_query": 0.005, "max_results_range": [0, 25]}]}
    ).to_model_pricing("exa_ai/search")

    assert pricing.query_pricing[0].range_end == 25
    assert pricing.query_pricing[0].rate == Decimal("0.005")


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
