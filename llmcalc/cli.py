"""CLI for llmcalc."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Any

import typer

from llmcalc import __version__
from llmcalc.api import clear_cache, cost
from llmcalc.api import model as model_costs
from llmcalc.config import DEFAULT_CACHE_TIMEOUT_SECONDS

DEFAULT_CACHE_TIMEOUT_HELP = (
    f"Cache TTL in seconds (default: {DEFAULT_CACHE_TIMEOUT_SECONDS} or LLMCALC_CACHE_TIMEOUT)"
)

app = typer.Typer(help="Calculate LLM token pricing.", no_args_is_help=True)
cache_app = typer.Typer(help="Cache commands.")
app.add_typer(cache_app, name="cache")


def _model_option() -> Any:
    return typer.Option(..., "--model", help="Model id")


def _cache_timeout_option() -> Any:
    return typer.Option(None, "--cache-timeout", help=DEFAULT_CACHE_TIMEOUT_HELP)


def _json_option() -> Any:
    return typer.Option(False, "--json", help="Emit JSON output")


def _rate(value: Decimal | None) -> str | None:
    """Render a per-token rate in plain decimal notation.

    `str(Decimal("0.000000075"))` is `"7.5E-8"`, which the JS CLI renders as
    `"7.5e-8"`. Both emit plain notation so their JSON output matches.
    """
    return None if value is None else format(value, "f")


def _emit(data: Mapping[str, object], as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, default=str))
        return

    for key, value in data.items():
        typer.echo(f"{key}: {value}")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"llmcalc {__version__}")
        raise typer.Exit()


@app.callback()
def app_main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-v",
            help="Show package version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    _ = version


@app.command()
def quote(
    model: str = _model_option(),
    input_tokens: int = typer.Option(
        ..., "--input", help="Total input token count, including any cached tokens", min=0
    ),
    output_tokens: int = typer.Option(
        ..., "--output", help="Total output token count, including any reasoning tokens", min=0
    ),
    cached_tokens: int = typer.Option(
        0, "--cached", help="Input tokens served from cache (subset of --input)", min=0
    ),
    cache_creation_tokens: int = typer.Option(
        0, "--cache-creation", help="Input tokens written to cache (subset of --input)", min=0
    ),
    reasoning_tokens: int = typer.Option(
        0, "--reasoning", help="Output tokens spent reasoning (subset of --output)", min=0
    ),
    cache_timeout: int | None = _cache_timeout_option(),
    as_json: bool = _json_option(),
) -> None:
    """Quote input/output/total cost for a model."""
    result = cost(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_timeout=cache_timeout,
        cached_tokens=cached_tokens,
        cache_creation_tokens=cache_creation_tokens,
        reasoning_tokens=reasoning_tokens,
    )

    if result is None:
        typer.echo(f"Model not found: {model}", err=True)
        raise typer.Exit(code=1)

    payload = {
        "model": model,
        "input_cost": result.input_cost,
        "output_cost": result.output_cost,
        "total_cost": result.total_cost,
        "currency": result.currency,
        "tier_applied": result.tier_applied,
        "cache_read_cost": result.cache_read_cost,
        "cache_creation_cost": result.cache_creation_cost,
        "reasoning_cost": result.reasoning_cost,
    }
    _emit(payload, as_json)


@app.command("model")
def model_cmd(
    model: str = _model_option(),
    cache_timeout: int | None = _cache_timeout_option(),
    as_json: bool = _json_option(),
) -> None:
    """Show per-token pricing for a model."""
    result = model_costs(model=model, cache_timeout=cache_timeout)

    if result is None:
        typer.echo(f"Model not found: {model}", err=True)
        raise typer.Exit(code=1)

    payload = {
        "model": result.model,
        "input_cost_per_token": _rate(result.input_cost_per_token),
        "output_cost_per_token": _rate(result.output_cost_per_token),
        "thresholds": [threshold.key for threshold in result.thresholds],
        "tier_count": len(result.tiered_pricing),
        "currency": result.currency,
        "provider": result.provider,
        "last_updated": result.last_updated,
    }
    _emit(payload, as_json)


@cache_app.command("clear")
def cache_clear() -> None:
    """Clear local pricing cache."""
    clear_cache()
    typer.echo("Cache cleared")
