import json

from typer.testing import CliRunner

from llmcalc import __version__
from llmcalc.cli import app
from llmcalc.models import CostBreakdown, RawModelPricing

runner = CliRunner()


def test_cli_version_long_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"llmcalc {__version__}" in result.stdout


def test_cli_version_short_flag() -> None:
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert f"llmcalc {__version__}" in result.stdout


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
