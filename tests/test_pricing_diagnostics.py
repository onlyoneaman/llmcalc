import json
from pathlib import Path

import pytest

import llmcalc
from llmcalc.errors import PricingSchemaError
from llmcalc.pricing_client import parse_pricing_payload_with_diagnostics

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "pricing_diagnostics_cases.json").read_text()
)


def test_pricing_reports_and_errors_are_exported() -> None:
    assert llmcalc.pricing_report is not None
    assert llmcalc.pricing_report_async is not None
    assert llmcalc.PricingSchemaError is PricingSchemaError
    assert issubclass(llmcalc.PricingHistoryError, llmcalc.PricingError)


def test_pricing_diagnostics_match_shared_contract() -> None:
    report = parse_pricing_payload_with_diagnostics(FIXTURE["payload"])

    assert list(report.models) == FIXTURE["parsed_models"]
    assert [item.to_dict() for item in report.diagnostics] == FIXTURE["diagnostics"]


def test_strict_pricing_parser_reports_all_problems() -> None:
    with pytest.raises(PricingSchemaError) as caught:
        parse_pricing_payload_with_diagnostics(FIXTURE["payload"], strict=True)

    assert str(caught.value) == "pricing payload contains invalid entries"
    assert [item.to_dict() for item in caught.value.diagnostics] == FIXTURE["diagnostics"]


def test_strict_pricing_parser_allows_informational_exclusions() -> None:
    report = parse_pricing_payload_with_diagnostics(
        {
            "valid": {"input_cost_per_token": "0.01"},
            "unsupported": {"output_cost_per_image": "0.02"},
        },
        strict=True,
    )

    assert list(report.models) == ["valid"]
    assert [item.severity for item in report.diagnostics] == ["info"]


def test_empty_parse_error_includes_diagnostics() -> None:
    with pytest.raises(PricingSchemaError) as caught:
        parse_pricing_payload_with_diagnostics({"broken": "not an object"})

    assert [item.code for item in caught.value.diagnostics] == ["entry_not_object"]
