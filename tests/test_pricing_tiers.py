import json
from decimal import Decimal
from pathlib import Path

import pytest

from llmcalc.pricing_tiers import (
    graduated_cost,
    parse_thresholds,
    parse_tiers,
    resolve_rates,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "tiered_cases.json").read_text(encoding="utf-8")
)


def _decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@pytest.mark.parametrize("case", FIXTURE["thresholds"], ids=lambda c: c["name"])
def test_threshold_rates(case: dict) -> None:
    pricing = case["pricing"]
    thresholds = parse_thresholds(pricing)

    input_rate, output_rate, tier = resolve_rates(
        _decimal_or_none(pricing.get("input_cost_per_token")),
        _decimal_or_none(pricing.get("output_cost_per_token")),
        thresholds,
        case["input_tokens"],
    )

    assert tier == case["expected"]["tier_applied"]
    assert input_rate is not None and output_rate is not None

    input_cost = (Decimal(case["input_tokens"]) * input_rate).quantize(Decimal("0.000001"))
    output_cost = (Decimal(case["output_tokens"]) * output_rate).quantize(Decimal("0.000001"))
    assert str(input_cost) == case["expected"]["input_cost"]
    assert str(output_cost) == case["expected"]["output_cost"]


@pytest.mark.parametrize("case", FIXTURE["graduated"], ids=lambda c: c["name"])
def test_graduated_costs(case: dict) -> None:
    tiers = parse_tiers(case["pricing"]["tiered_pricing"])
    assert tiers, "tiers should parse"

    input_cost = graduated_cost(case["input_tokens"], tiers, "input").quantize(Decimal("0.000001"))
    output_cost = graduated_cost(case["output_tokens"], tiers, "output").quantize(
        Decimal("0.000001")
    )

    assert str(input_cost) == case["expected"]["input_cost"]
    assert str(output_cost) == case["expected"]["output_cost"]


def test_thresholds_are_sorted_descending() -> None:
    thresholds = parse_thresholds(
        {
            "input_cost_per_token_above_128k_tokens": "0.000002",
            "input_cost_per_token_above_272k_tokens": "0.000004",
        }
    )
    assert [t.threshold for t in thresholds] == [272000, 128000]


def test_query_priced_tiers_are_not_token_tiers() -> None:
    assert (
        parse_tiers(
            [
                {"input_cost_per_query": 0.005, "max_results_range": [0, 25]},
                {"input_cost_per_query": 0.025, "max_results_range": [26, 100]},
            ]
        )
        == ()
    )


def test_tiers_missing_cost_key_contribute_zero() -> None:
    tiers = parse_tiers([{"range": [0, 100], "input_cost_per_token": "0.000001"}])
    assert graduated_cost(50, tiers, "output") == Decimal("0")


def test_parse_tiers_tolerates_garbage() -> None:
    assert parse_tiers(None) == ()
    assert parse_tiers("nonsense") == ()
    assert parse_tiers([{"range": [0]}]) == ()
    assert parse_tiers([{"range": ["a", "b"], "input_cost_per_token": "1"}]) == ()


def test_parse_thresholds_ignores_negative_and_unparseable_rates() -> None:
    thresholds = parse_thresholds(
        {
            "input_cost_per_token_above_128k_tokens": "-0.5",
            "output_cost_per_token_above_272k_tokens": "not-a-number",
        }
    )
    assert thresholds == ()


def test_graduated_cost_is_zero_for_no_tiers() -> None:
    assert graduated_cost(1000, (), "input") == Decimal("0")


def test_threshold_key_preserves_the_k_suffix_form() -> None:
    thresholds = parse_thresholds({"input_cost_per_token_above_272k_tokens": "0.00001"})
    assert thresholds[0].key == "above_272k_tokens"
    assert thresholds[0].threshold == 272000

    literal = parse_thresholds({"input_cost_per_token_above_128_tokens": "0.00001"})
    assert literal[0].key == "above_128_tokens"
    assert literal[0].threshold == 128
