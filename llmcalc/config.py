"""Configuration defaults and environment-driven settings."""

from __future__ import annotations

import os
from importlib import metadata

APP_NAME = "llmcalc"
FALLBACK_VERSION = "0.1.1"
DEFAULT_CACHE_TIMEOUT_SECONDS = 43200
DEFAULT_CURRENCY = "USD"
DEFAULT_PRICING_URL = (
    "https://raw.githubusercontent.com/llmlite/llmlite/main/model_prices_and_context_window.json"
)


def get_package_version() -> str:
    """Return installed package version with a source fallback."""
    try:
        return metadata.version(APP_NAME)
    except metadata.PackageNotFoundError:
        return FALLBACK_VERSION


def get_user_agent() -> str:
    """Return HTTP user agent for outbound pricing requests."""
    return f"{APP_NAME}/{get_package_version()}"


def get_pricing_url(explicit_url: str | None = None) -> str:
    """Resolve pricing source URL from explicit arg, env var, then default."""
    return explicit_url or os.getenv("LLMCALC_PRICING_URL") or DEFAULT_PRICING_URL


def get_default_currency() -> str:
    """Resolve fallback currency label from env var or default."""
    raw = os.getenv("LLMCALC_CURRENCY", "").strip().upper()
    return raw or DEFAULT_CURRENCY


def resolve_cache_timeout(cache_timeout: int | None = None) -> int:
    """Resolve cache timeout from explicit value, env var, or default."""
    if cache_timeout is not None:
        if cache_timeout <= 0:
            raise ValueError("cache_timeout must be positive")
        return cache_timeout

    env_value = os.getenv("LLMCALC_CACHE_TIMEOUT")
    if env_value is None:
        return DEFAULT_CACHE_TIMEOUT_SECONDS

    try:
        parsed = int(env_value)
    except ValueError:
        return DEFAULT_CACHE_TIMEOUT_SECONDS

    if parsed <= 0:
        return DEFAULT_CACHE_TIMEOUT_SECONDS

    return parsed
