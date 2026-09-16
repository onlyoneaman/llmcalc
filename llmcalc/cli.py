"""CLI for llmcalc."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Annotated, Any

import typer

from llmcalc import __version__
from llmcalc.api import clear_cache, cost, pricing_report
from llmcalc.api import model as model_costs
from llmcalc.config import DEFAULT_CACHE_TIMEOUT_SECONDS
from llmcalc.models import COST_DECIMAL_PRECISION

MAX_SAFE_INTEGER = 2**53 - 1
_ASCII_INTEGER = re.compile(r"[+]?[0-9]+")


DEFAULT_CACHE_TIMEOUT_HELP = (
    f"Cache TTL in seconds (default: {DEFAULT_CACHE_TIMEOUT_SECONDS} or LLMCALC_CACHE_TIMEOUT)"
)

app = typer.Typer(help="Calculate LLM token pricing.", no_args_is_help=True)
cache_app = typer.Typer(help="Cache commands.")
pricing_app = typer.Typer(help="Pricing data commands.")
app.add_typer(cache_app, name="cache")
app.add_typer(pricing_app, name="pricing")


def _model_option() -> Any:
    return typer.Option(..., "--model", help="Model id")


def _cache_timeout_option() -> Any:
    return typer.Option(None, "--cache-timeout", help=DEFAULT_CACHE_TIMEOUT_HELP)


def _json_option() -> Any:
    return typer.Option(False, "--json", help="Emit JSON output")


def _integer(value: str, option: str, minimum: int) -> int:
    normalized = value.strip()
    if _ASCII_INTEGER.fullmatch(normalized) is None:
        raise typer.BadParameter("must be an integer", param_hint=option)
    parsed = int(normalized)
    if not minimum <= parsed <= MAX_SAFE_INTEGER:
        raise typer.BadParameter(
            f"must be between {minimum} and {MAX_SAFE_INTEGER}",
            param_hint=option,
        )
    return parsed


def _rate(value: Decimal | None) -> str | None:
    """Render a per-token rate in plain decimal notation.

    `str(Decimal("0.000000075"))` is `"7.5E-8"`, which the JS CLI renders as
    `"7.5e-8"`. Both emit plain notation so their JSON output matches.
    """
    return None if value is None else format(value, "f")


def _money(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = max(COST_DECIMAL_PRECISION, value.adjusted() + 9)
        rounded = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return format(rounded, "f")


def _sum_money(left: str, right: str) -> str:
    left_value = Decimal(left)
    right_value = Decimal(right)
    with localcontext() as context:
        context.prec = max(
            COST_DECIMAL_PRECISION,
            left_value.adjusted() + 10,
            right_value.adjusted() + 10,
        )
        return _money(left_value + right_value)


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
    input_tokens: str = typer.Option(
        ..., "--input", help="Total input token count, including any cached tokens"
    ),
    output_tokens: str = typer.Option(
        ..., "--output", help="Total output token count, including any reasoning tokens"
    ),
    cached_tokens: str = typer.Option(
        "0", "--cached", help="Input tokens served from cache (subset of --input)"
    ),
    cache_creation_tokens: str = typer.Option(
        "0",
        "--cache-creation",
        help="Input tokens written to cache (subset of --input)",
    ),
    reasoning_tokens: str = typer.Option(
        "0", "--reasoning", help="Output tokens spent reasoning (subset of --output)"
    ),
    processing_mode: str = typer.Option(
        "standard", "--processing-mode", help="standard, batch, priority, flex, or fast"
    ),
    cache_creation_tokens_1h: str = typer.Option(
        "0", "--cache-creation-1h", help="One-hour cache writes (subset of --cache-creation)"
    ),
    cache_creation_audio_tokens: str = typer.Option(
        "0",
        "--cache-creation-audio",
        help="Audio cache writes (subset of --cache-creation and --input-audio)",
    ),
    cached_audio_tokens: str = typer.Option(
        "0", "--cached-audio", help="Cached audio tokens (subset of --cached and --input-audio)"
    ),
    cached_image_tokens: str = typer.Option(
        "0", "--cached-image", help="Cached image tokens (subset of --cached and --input-image)"
    ),
    input_audio_tokens: str = typer.Option("0", "--input-audio"),
    output_audio_tokens: str = typer.Option("0", "--output-audio"),
    input_image_tokens: str = typer.Option("0", "--input-image"),
    output_image_tokens: str = typer.Option("0", "--output-image"),
    query_count: str = typer.Option("0", "--queries"),
    query_results: str | None = typer.Option(None, "--query-results"),
    web_search_requests: str = typer.Option("0", "--web-searches"),
    web_search_context: str = typer.Option(
        "medium", "--web-search-context", help="low, medium, or high"
    ),
    maps_grounding_requests: str = typer.Option("0", "--maps-grounding"),
    region: str | None = typer.Option(
        None, "--region", help="Regional processing: global, regional, us, or eu"
    ),
    snapshot_at: str | None = typer.Option(
        None, "--snapshot-at", help="LiteLLM repository snapshot date (YYYY-MM-DD)"
    ),
    cache_timeout: str | None = _cache_timeout_option(),
    as_json: bool = _json_option(),
) -> None:
    """Quote input/output/total cost for a model."""
    parsed_input = _integer(input_tokens, "--input", 0)
    parsed_output = _integer(output_tokens, "--output", 0)
    parsed_cached = _integer(cached_tokens, "--cached", 0)
    parsed_creation = _integer(cache_creation_tokens, "--cache-creation", 0)
    parsed_reasoning = _integer(reasoning_tokens, "--reasoning", 0)
    parsed_creation_1h = _integer(
        cache_creation_tokens_1h, "--cache-creation-1h", 0
    )
    parsed_creation_audio = _integer(
        cache_creation_audio_tokens, "--cache-creation-audio", 0
    )
    parsed_cached_audio = _integer(cached_audio_tokens, "--cached-audio", 0)
    parsed_cached_image = _integer(cached_image_tokens, "--cached-image", 0)
    parsed_input_audio = _integer(input_audio_tokens, "--input-audio", 0)
    parsed_output_audio = _integer(output_audio_tokens, "--output-audio", 0)
    parsed_input_image = _integer(input_image_tokens, "--input-image", 0)
    parsed_output_image = _integer(output_image_tokens, "--output-image", 0)
    parsed_queries = _integer(query_count, "--queries", 0)
    parsed_query_results = (
        None if query_results is None else _integer(query_results, "--query-results", 0)
    )
    parsed_web_searches = _integer(web_search_requests, "--web-searches", 0)
    parsed_maps = _integer(maps_grounding_requests, "--maps-grounding", 0)
    parsed_timeout = (
        None if cache_timeout is None else _integer(cache_timeout, "--cache-timeout", 1)
    )
    result = cost(
        model=model,
        input_tokens=parsed_input,
        output_tokens=parsed_output,
        cache_timeout=parsed_timeout,
        snapshot_at=snapshot_at,
        cached_tokens=parsed_cached,
        cache_creation_tokens=parsed_creation,
        reasoning_tokens=parsed_reasoning,
        processing_mode=processing_mode,
        cache_creation_tokens_1h=parsed_creation_1h,
        cache_creation_audio_tokens=parsed_creation_audio,
        cached_audio_tokens=parsed_cached_audio,
        cached_image_tokens=parsed_cached_image,
        input_audio_tokens=parsed_input_audio,
        output_audio_tokens=parsed_output_audio,
        input_image_tokens=parsed_input_image,
        output_image_tokens=parsed_output_image,
        query_count=parsed_queries,
        query_results=parsed_query_results,
        web_search_requests=parsed_web_searches,
        web_search_context=web_search_context,
        maps_grounding_requests=parsed_maps,
        region=region,
    )

    if result is None:
        typer.echo(f"Model not found: {model}", err=True)
        raise typer.Exit(code=1)

    input_cost = _money(result.input_cost)
    output_cost = _money(result.output_cost)
    payload = {
        "model": model,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": _sum_money(input_cost, output_cost),
        "currency": result.currency,
        "tier_applied": result.tier_applied,
        "cache_read_cost": _money(result.cache_read_cost),
        "cache_creation_cost": _money(result.cache_creation_cost),
        "cache_creation_audio_cost": _money(result.cache_creation_audio_cost),
        "cache_creation_1h_cost": _money(result.cache_creation_1h_cost),
        "reasoning_cost": _money(result.reasoning_cost),
        "audio_input_cost": _money(result.audio_input_cost),
        "audio_output_cost": _money(result.audio_output_cost),
        "image_input_cost": _money(result.image_input_cost),
        "image_output_cost": _money(result.image_output_cost),
        "query_cost": _money(result.query_cost),
        "processing_mode": result.processing_mode,
        "regional_multiplier": _rate(result.regional_multiplier),
    }
    _emit(payload, as_json)


@app.command("model")
def model_cmd(
    model: str = _model_option(),
    snapshot_at: str | None = typer.Option(
        None, "--snapshot-at", help="LiteLLM repository snapshot date (YYYY-MM-DD)"
    ),
    cache_timeout: str | None = _cache_timeout_option(),
    as_json: bool = _json_option(),
) -> None:
    """Show per-token pricing for a model."""
    parsed_timeout = (
        None if cache_timeout is None else _integer(cache_timeout, "--cache-timeout", 1)
    )
    result = model_costs(
        model=model,
        cache_timeout=parsed_timeout,
        snapshot_at=snapshot_at,
    )

    if result is None:
        typer.echo(f"Model not found: {model}", err=True)
        raise typer.Exit(code=1)

    payload = {
        "model": result.model,
        "input_cost_per_token": _rate(result.input_cost_per_token),
        "output_cost_per_token": _rate(result.output_cost_per_token),
        "thresholds": [threshold.key for threshold in result.thresholds],
        "tier_count": len(result.tiered_pricing),
        "processing_modes": sorted(result.pricing_modes),
        "cache_read_cost_per_token": _rate(result.cache_read_cost_per_token),
        "cache_read_audio_cost_per_token": _rate(
            result.cache_read_audio_cost_per_token
        ),
        "cache_creation_cost_per_token": _rate(result.cache_creation_cost_per_token),
        "cache_creation_audio_cost_per_token": _rate(
            result.cache_creation_audio_cost_per_token
        ),
        "cache_creation_1h_cost_per_token": _rate(
            result.cache_creation_1h_cost_per_token
        ),
        "reasoning_cost_per_token": _rate(result.reasoning_cost_per_token),
        "input_audio_cost_per_token": _rate(result.input_audio_cost_per_token),
        "output_audio_cost_per_token": _rate(result.output_audio_cost_per_token),
        "input_image_cost_per_token": _rate(result.input_image_cost_per_token),
        "output_image_cost_per_token": _rate(result.output_image_cost_per_token),
        "input_cost_per_query": _rate(result.input_cost_per_query),
        "query_pricing": [
            {
                "range": [tier.range_start, tier.range_end],
                "input_cost_per_query": _rate(tier.rate),
            }
            for tier in result.query_pricing
        ],
        "search_context_cost_per_query": {
            key: _rate(value)
            for key, value in result.search_context_cost_per_query.items()
        },
        "google_maps_grounding_cost_per_query": _rate(
            result.google_maps_grounding_cost_per_query
        ),
        "web_search_billing_unit": result.web_search_billing_unit,
        "regional_processing_uplift": {
            key: _rate(value)
            for key, value in result.regional_processing_uplift.items()
        },
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


@pricing_app.command("check")
def pricing_check(
    snapshot_at: str | None = typer.Option(
        None, "--snapshot-at", help="LiteLLM repository snapshot date (YYYY-MM-DD)"
    ),
    cache_timeout: str | None = _cache_timeout_option(),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit nonzero when warnings or errors are present.",
    ),
    as_json: bool = _json_option(),
) -> None:
    """Inspect pricing data exclusions and malformed fields."""
    parsed_timeout = (
        None if cache_timeout is None else _integer(cache_timeout, "--cache-timeout", 1)
    )
    report = pricing_report(
        cache_timeout=parsed_timeout,
        snapshot_at=snapshot_at,
    )
    diagnostics = [item.to_dict() for item in report.diagnostics]
    payload = {
        "model_count": len(report.models),
        "diagnostic_count": len(diagnostics),
        "diagnostics": diagnostics,
    }
    if as_json:
        typer.echo(json.dumps(payload))
    else:
        typer.echo(f"Models: {len(report.models)}")
        typer.echo(f"Diagnostics: {len(diagnostics)}")
        for item in report.diagnostics:
            path = ".".join(str(part) for part in item.path)
            location = item.model if not path else f"{item.model}.{path}"
            typer.echo(f"{item.severity}: {location}: {item.code}: {item.message}")

    if strict and any(item.severity in {"warning", "error"} for item in report.diagnostics):
        raise typer.Exit(code=1)
