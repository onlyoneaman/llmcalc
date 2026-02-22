"""Model name normalization and lookup helpers."""

from __future__ import annotations

from collections.abc import Iterable

# Keep aliases small and explicit; extend as model IDs evolve.
ALIASES: dict[str, str] = {
    "gpt-5.1-latest": "gpt-5.1",
}

PROVIDER_PREFIXES: set[str] = {
    "openai",
    "anthropic",
    "google",
    "xai",
    "meta",
    "mistral",
}


def normalize_model_name(model: str) -> str:
    """Normalize an input model identifier to a canonical lookup key."""
    normalized = model.strip().lower()
    if not normalized:
        raise ValueError("model must not be empty")

    if ":" in normalized:
        provider, suffix = normalized.split(":", 1)
        if provider and suffix:
            normalized = suffix

    if "/" in normalized:
        provider, suffix = normalized.split("/", 1)
        if provider in PROVIDER_PREFIXES and suffix:
            normalized = suffix

    return ALIASES.get(normalized, normalized)


def resolve_model_key(model: str, available_keys: Iterable[str]) -> str | None:
    """Resolve a requested model id against available pricing table keys."""
    key_map: dict[str, str] = {}
    for key in available_keys:
        key_map[key.lower()] = key
        key_map.setdefault(normalize_model_name(key), key)

    candidates: list[str] = []
    raw = model.strip().lower()
    if raw:
        candidates.append(raw)
    candidates.append(normalize_model_name(model))

    for candidate in candidates:
        direct = key_map.get(candidate)
        if direct is not None:
            return direct
        alias = ALIASES.get(candidate)
        if alias is not None and alias in key_map:
            return key_map[alias]

    return None
