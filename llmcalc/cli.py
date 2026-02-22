"""CLI for llmcalc."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

import typer

from llmcalc import __version__
from llmcalc.api import (
    calculate_token_cost,
    clear_cache,
    get_model_costs,
)
from llmcalc.config import DEFAULT_CACHE_TIMEOUT_SECONDS

DEFAULT_CACHE_TIMEOUT_HELP = (
    f"Cache TTL in seconds (default: {DEFAULT_CACHE_TIMEOUT_SECONDS} or LLMCALC_CACHE_TIMEOUT)"
)

app = typer.Typer(help="Calculate LLM token pricing from llmlite data.", no_args_is_help=True)
cache_app = typer.Typer(help="Cache commands.")
app.add_typer(cache_app, name="cache")


def _model_option() -> Any:
    return typer.Option(..., "--model", help="Model id")


def _cache_timeout_option() -> Any:
    return typer.Option(None, "--cache-timeout", help=DEFAULT_CACHE_TIMEOUT_HELP)


def _json_option() -> Any:
    return typer.Option(False, "--json", help="Emit JSON output")


def _emit(data: dict[str, object], as_json: bool) -> None:
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
    input_tokens: int = typer.Option(..., "--input", help="Input token count", min=0),
    output_tokens: int = typer.Option(..., "--output", help="Output token count", min=0),
    cache_timeout: int | None = _cache_timeout_option(),
    as_json: bool = _json_option(),
) -> None:
    """Quote input/output/total cost for a model."""
    result = asyncio.run(
        calculate_token_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_timeout=cache_timeout,
        )
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
    }
    _emit(payload, as_json)


@app.command("model")
def model_cmd(
    model: str = _model_option(),
    cache_timeout: int | None = _cache_timeout_option(),
    as_json: bool = _json_option(),
) -> None:
    """Show per-token pricing for a model."""
    result = asyncio.run(get_model_costs(model=model, cache_timeout=cache_timeout))

    if result is None:
        typer.echo(f"Model not found: {model}", err=True)
        raise typer.Exit(code=1)

    payload = {
        "model": result.model,
        "input_cost_per_token": result.input_cost_per_token,
        "output_cost_per_token": result.output_cost_per_token,
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
