import json

import pytest
from typer.testing import CliRunner

from llmcalc import __version__
from llmcalc.cli import app
from llmcalc.diagnostics import PricingDiagnostic, PricingParseResult
from llmcalc.models import CostBreakdown, RawModelPricing

runner = CliRunner()


def _pricing_report() -> PricingParseResult:
    pricing = RawModelPricing.model_validate(
        {"input_cost_per_token": "0.01"}
    ).to_model_pricing("valid")
    return PricingParseResult(
        models={"valid": pricing},
        diagnostics=(
            PricingDiagnostic(
                model="broken",
                severity="warning",
                code="invalid_rate",
                action="ignored_field",
                path=("input_cost_per_token_above_1k_tokens",),
                message="long-context pricing rate is malformed",
            ),
        ),
    )


def test_cli_version_long_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"llmcalc {__version__}" in result.stdout


def test_cli_version_short_flag() -> None:
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert f"llmcalc {__version__}" in result.stdout


def test_pricing_check_emits_structured_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr("llmcalc.cli.pricing_report", lambda **_kwargs: _pricing_report())

    result = runner.invoke(app, ["pricing", "check", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["model_count"] == 1
    assert payload["diagnostics"][0]["path"] == [
        "input_cost_per_token_above_1k_tokens"
    ]


def test_pricing_check_strict_exits_nonzero_after_reporting(monkeypatch) -> None:
    monkeypatch.setattr("llmcalc.cli.pricing_report", lambda **_kwargs: _pricing_report())

    result = runner.invoke(app, ["pricing", "check", "--strict", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["diagnostic_count"] == 1


def test_quote_reports_tier_applied(monkeypatch) -> None:
    def _cost(**_kwargs):
        return CostBreakdown(
            input_cost="3.000000",
            output_cost="0.225000",
            total_cost="3.225000",
            currency="USD",
            tier_applied="above_272k_tokens",
        )

    monkeypatch.setattr("llmcalc.cli.cost", _cost)

    result = runner.invoke(
        app,
        ["quote", "--model", "gpt-5.5", "--input", "300000", "--output", "5000", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["tier_applied"] == "above_272k_tokens"


def test_quote_reports_no_tier_for_base_rates(monkeypatch) -> None:
    def _cost(**_kwargs):
        return CostBreakdown(
            input_cost="0.500000",
            output_cost="0.030000",
            total_cost="0.530000",
            currency="USD",
        )

    monkeypatch.setattr("llmcalc.cli.cost", _cost)

    result = runner.invoke(
        app,
        ["quote", "--model", "gpt-5.5", "--input", "100000", "--output", "1000", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["tier_applied"] is None


def test_quote_total_equals_displayed_input_plus_output(monkeypatch) -> None:
    def _cost(**_kwargs):
        return CostBreakdown(
            input_cost="0.0000005",
            output_cost="0.0000005",
            total_cost="0.000001",
            currency="USD",
        )

    monkeypatch.setattr("llmcalc.cli.cost", _cost)

    result = runner.invoke(
        app,
        ["quote", "--model", "tiny", "--input", "1", "--output", "1", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["input_cost"] == "0.000001"
    assert payload["output_cost"] == "0.000001"
    assert payload["total_cost"] == "0.000002"


def test_quote_serializes_large_finite_costs(monkeypatch) -> None:
    def _cost(**_kwargs):
        return CostBreakdown(
            input_cost="1e44",
            output_cost="0",
            total_cost="1e44",
            currency="USD",
        )

    monkeypatch.setattr("llmcalc.cli.cost", _cost)
    result = runner.invoke(
        app,
        ["quote", "--model", "large", "--input", "1", "--output", "0", "--json"],
    )

    assert result.exit_code == 0
    expected = "1" + "0" * 44 + ".000000"
    payload = json.loads(result.stdout)
    assert payload["input_cost"] == expected
    assert payload["total_cost"] == expected


def test_model_command_reports_thresholds(monkeypatch) -> None:
    pricing = RawModelPricing.model_validate(
        {
            "input_cost_per_token": 5e-06,
            "output_cost_per_token": 3e-05,
            "input_cost_per_token_above_272k_tokens": 1e-05,
            "output_cost_per_token_above_272k_tokens": 4.5e-05,
        }
    ).to_model_pricing("gpt-5.5")

    monkeypatch.setattr("llmcalc.cli.model_costs", lambda **_kwargs: pricing)

    result = runner.invoke(app, ["model", "--model", "gpt-5.5", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["thresholds"] == ["above_272k_tokens"]
    assert payload["tier_count"] == 0


def test_model_command_emits_plain_decimal_notation(monkeypatch) -> None:
    pricing = RawModelPricing.model_validate(
        {"input_cost_per_token": 7.5e-08, "output_cost_per_token": 0}
    ).to_model_pricing("gemini/gemini-1.5-flash")

    monkeypatch.setattr("llmcalc.cli.model_costs", lambda **_kwargs: pricing)

    result = runner.invoke(app, ["model", "--model", "gemini/gemini-1.5-flash", "--json"])

    assert result.exit_code == 0
    # Not '7.5E-8'.
    assert json.loads(result.stdout)["input_cost_per_token"] == "0.000000075"


def test_model_command_handles_tiered_model_without_base_rates(monkeypatch) -> None:
    pricing = RawModelPricing.model_validate(
        {
            "tiered_pricing": [
                {
                    "range": [0, 256000],
                    "input_cost_per_token": 5e-08,
                    "output_cost_per_token": 4e-07,
                }
            ]
        }
    ).to_model_pricing("dashscope/qwen-flash")

    monkeypatch.setattr("llmcalc.cli.model_costs", lambda **_kwargs: pricing)

    result = runner.invoke(app, ["model", "--model", "dashscope/qwen-flash", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["input_cost_per_token"] is None
    assert payload["tier_count"] == 1


@pytest.mark.parametrize("value", ["1.5", "1oops", "1e3", "1_000", "١٠٠٠"])
def test_quote_rejects_non_ascii_integer_syntax(value: str) -> None:
    result = runner.invoke(
        app,
        ["quote", "--model", "gpt-5.1", "--input", value, "--output", "1"],
    )
    assert result.exit_code != 0


def test_quote_duplicate_options_use_last_value(monkeypatch) -> None:
    captured: dict[str, int] = {}

    def _cost(**kwargs):
        captured["input_tokens"] = kwargs["input_tokens"]
        return CostBreakdown(
            input_cost="0",
            output_cost="0",
            total_cost="0",
            currency="USD",
        )

    monkeypatch.setattr("llmcalc.cli.cost", _cost)
    result = runner.invoke(
        app,
        [
            "quote",
            "--model",
            "gpt-5.1",
            "--input",
            "1",
            "--input",
            "2",
            "--output",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert captured["input_tokens"] == 2
