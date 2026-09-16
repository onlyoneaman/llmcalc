import json
from decimal import Decimal
from pathlib import Path

import pytest

from llmcalc.pricing_tiers import (
    parse_base_rates,
    parse_thresholds,
    parse_tiers,
    resolve_rates,
    resolve_tier_rates,
    select_tier_rates,
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

    rates, tier = resolve_rates(
        parse_base_rates(pricing),
        thresholds,
        case["input_tokens"],
        pricing.get("litellm_provider"),
    )

    assert tier == case["expected"]["tier_applied"]
    input_rate = rates.get("input")
    output_rate = rates.get("output")
    assert input_rate is not None and output_rate is not None

    input_cost = (Decimal(case["input_tokens"]) * input_rate).quantize(Decimal("0.000001"))
    output_cost = (Decimal(case["output_tokens"]) * output_rate).quantize(Decimal("0.000001"))
    assert str(input_cost) == case["expected"]["input_cost"]
    assert str(output_cost) == case["expected"]["output_cost"]


@pytest.mark.parametrize("case", FIXTURE["request_tiers"], ids=lambda c: c["name"])
def test_request_tier_rates(case: dict) -> None:
    tiers = parse_tiers(case["pricing"]["tiered_pricing"])
    assert tiers, "tiers should parse"

    selected = select_tier_rates(tiers, case["input_tokens"])
    if case["input_tokens"] == 0:
        assert selected is None
        return
    assert selected is not None
    rates = resolve_tier_rates(parse_base_rates(case["pricing"]), selected)
    input_rate = rates.get("input")
    output_rate = rates.get("output")
    assert input_rate is not None and output_rate is not None
    input_cost = (Decimal(case["input_tokens"]) * input_rate).quantize(Decimal("0.000001"))
    output_cost = (Decimal(case["output_tokens"]) * output_rate).quantize(Decimal("0.000001"))

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


def test_tiers_missing_cost_key_remain_missing() -> None:
    tiers = parse_tiers([{"range": [0, 100], "input_cost_per_token": "0.000001"}])
    rates = select_tier_rates(tiers, 50)
    assert rates is not None
    assert rates.get("output") is None


def test_output_only_tier_schedule_is_rejected() -> None:
    assert (
        parse_tiers([{"range": [0, 100], "output_cost_per_token": "0.000001"}])
        == ()
    )


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


def test_no_tier_rates_without_tiers() -> None:
    assert select_tier_rates((), 1000) is None


def test_positive_gap_between_tier_ranges_uses_last_tier() -> None:
    tiers = parse_tiers(
        [
            {"range": [0, 100], "input_cost_per_token": "0.000001"},
            {"range": [200, 300], "input_cost_per_token": "0.000003"},
        ]
    )
    rates = select_tier_rates(tiers, 150)
    assert rates is not None
    assert rates.input == Decimal("0.000003")


def test_zero_input_does_not_select_a_tier() -> None:
    tiers = parse_tiers([{"range": [0, 100], "input_cost_per_token": "0.000001"}])
    assert select_tier_rates(tiers, 0) is None


def test_parse_tiers_rejects_entire_malformed_schedule() -> None:
    assert (
        parse_tiers(
            [
                {"range": [0, 100], "input_cost_per_token": "0.000001"},
                {"range": [100], "input_cost_per_token": "0.000002"},
            ]
        )
        == ()
    )
    valid = {"range": [0, 100], "input_cost_per_token": "0.000001"}
    assert parse_tiers([valid, None]) == ()
    assert parse_tiers([valid, {"input_cost_per_token": "0.000002"}]) == ()


def test_parse_tiers_rejects_overlapping_schedule() -> None:
    assert (
        parse_tiers(
            [
                {"range": [0, 100], "input_cost_per_token": "0.000001"},
                {"range": [99, 200], "input_cost_per_token": "0.000002"},
            ]
        )
        == ()
    )


def test_parse_tiers_accepts_touching_ranges() -> None:
    tiers = parse_tiers(
        [
            {"range": [0, 100], "input_cost_per_token": "0.000001"},
            {"range": [100, 200], "input_cost_per_token": "0.000002"},
        ]
    )
    assert len(tiers) == 2
    assert select_tier_rates(tiers, 100) == tiers[0].rates


def test_threshold_key_preserves_the_k_suffix_form() -> None:
    thresholds = parse_thresholds({"input_cost_per_token_above_272k_tokens": "0.00001"})
    assert thresholds[0].key == "above_272k_tokens"
    assert thresholds[0].threshold == 272000

    literal = parse_thresholds({"input_cost_per_token_above_128_tokens": "0.00001"})
    assert literal[0].key == "above_128_tokens"
    assert literal[0].threshold == 128
