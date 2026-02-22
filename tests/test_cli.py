from typer.testing import CliRunner

from llmcalc import __version__
from llmcalc.cli import app

runner = CliRunner()


def test_cli_version_long_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"llmcalc {__version__}" in result.stdout


def test_cli_version_short_flag() -> None:
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert f"llmcalc {__version__}" in result.stdout
