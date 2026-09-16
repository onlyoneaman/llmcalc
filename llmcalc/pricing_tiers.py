"""Tiered, long-context, cache and reasoning pricing resolution.

Pure helpers: no I/O, no cache, no network. Upstream ships two tiering
mechanisms that behave differently, so both are modelled separately:

* `above_{N}_tokens` rates replace the base rates for the whole request once the
  input token count exceeds the threshold, and apply to output as well as input.
* `tiered_pricing` selects one rate table from the request's total input size.

Token, cache, reasoning, audio and image rates are tracked independently.
Missing specialized rates fall back through the corresponding input or output
rate, except one-hour cache writes, which callers require explicitly.

Parsers return empty results for unsupported tier shapes. The pricing parser
reports malformed supported fields through structured diagnostics.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

RateKind = Literal[
    "input",
    "output",
    "cache_read",
    "cache_read_audio",
    "cache_creation",
    "cache_creation_audio",
    "cache_creation_1h",
    "reasoning",
    "input_audio",
    "output_audio",
    "input_image",
    "output_image",
]
PricingMode = Literal["standard", "batch", "priority", "flex"]

# Upstream field name for each rate kind.
RATE_FIELDS: dict[RateKind, str] = {
    "input": "input_cost_per_token",
    "output": "output_cost_per_token",
    "cache_read": "cache_read_input_token_cost",
    "cache_read_audio": "cache_read_input_audio_token_cost",
    "cache_creation": "cache_creation_input_token_cost",
    "cache_creation_audio": "cache_creation_input_audio_token_cost",
    "cache_creation_1h": "cache_creation_input_token_cost_above_1hr",
    "reasoning": "output_cost_per_reasoning_token",
    "input_audio": "input_cost_per_audio_token",
    "output_audio": "output_cost_per_audio_token",
    "input_image": "input_cost_per_image_token",
    "output_image": "output_cost_per_image_token",
}

MODE_SUFFIXES: dict[PricingMode, str] = {
    "standard": "",
    "batch": "batches",
    "priority": "priority",
    "flex": "flex",
}

# DeepSeek and friends spell the cache-read rate differently.
_CACHE_READ_ALIASES = ("input_cost_per_token_cache_hit",)

# When a model omits a rate, bill those tokens at this rate instead.
_RATE_FALLBACK: dict[RateKind, RateKind] = {
    "cache_read": "input",
    "cache_read_audio": "cache_read",
    "cache_creation": "input",
    "cache_creation_1h": "cache_creation",
    "reasoning": "output",
    "input_audio": "input",
    "output_audio": "output",
    "input_image": "input",
    "output_image": "output",
}

# Rate families with above_{N}_tokens variants upstream; reasoning has none.
_THRESHOLD_BASES: dict[str, RateKind] = {
    "input_cost_per_token": "input",
    "output_cost_per_token": "output",
    "cache_read_input_token_cost": "cache_read",
    "cache_creation_input_token_cost": "cache_creation",
    "cache_creation_input_token_cost_above_1hr": "cache_creation_1h",
}

_THRESHOLD_KEY = re.compile(
    r"^(?P<base>"
    + "|".join(sorted(_THRESHOLD_BASES, key=len, reverse=True))
    + r")_above_(?P<amount>\d+)(?P<kilo>k?)_tokens"
    + r"(?:_(?P<suffix>batches|priority|flex))?$"
)

_ZERO = Decimal("0")


@dataclass(frozen=True)
class TokenRates:
    """Per-token rates for one pricing context. `None` means not declared."""

    input: Decimal | None = None
    output: Decimal | None = None
    cache_read: Decimal | None = None
    cache_read_audio: Decimal | None = None
    cache_creation: Decimal | None = None
    cache_creation_audio: Decimal | None = None
    cache_creation_1h: Decimal | None = None
    reasoning: Decimal | None = None
    input_audio: Decimal | None = None
    output_audio: Decimal | None = None
    input_image: Decimal | None = None
    output_image: Decimal | None = None

    def get(self, kind: RateKind) -> Decimal | None:
        """Return the rate for `kind`, falling back per `_RATE_FALLBACK`."""
        direct: Decimal | None = getattr(self, kind)
        if direct is not None:
            return direct
        fallback = _RATE_FALLBACK.get(kind)
        return None if fallback is None else self.get(fallback)


@dataclass(frozen=True)
class PricingModeProfile:
    rates: TokenRates
    thresholds: tuple[PricingThreshold, ...]

@dataclass(frozen=True)
class PricingThreshold:
    threshold: int
    key: str
    rates: TokenRates


@dataclass(frozen=True)
class PricingTier:
    range_start: Decimal
    range_end: Decimal
    rates: TokenRates


@dataclass(frozen=True)
class QueryPricingTier:
    range_start: int
    range_end: int
    rate: Decimal


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value >= _ZERO else None
    if isinstance(value, (int, float, str)):
        try:
            parsed = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return None
        if not parsed.is_finite() or parsed < _ZERO:
            return None
        return parsed
    return None


def parse_base_rates(raw: Mapping[str, Any], suffix: str = "") -> TokenRates:
    """Read the flat per-token rates a model declares."""
    field_suffix = f"_{suffix}" if suffix else ""
    values: dict[str, Decimal | None] = {
        kind: _to_decimal(raw.get(f"{field}{field_suffix}"))
        for kind, field in RATE_FIELDS.items()
    }

    if not suffix and values["cache_read"] is None:
        for alias in _CACHE_READ_ALIASES:
            aliased = _to_decimal(raw.get(alias))
            if aliased is not None:
                values["cache_read"] = aliased
                break

    return TokenRates(**values)


def parse_thresholds(
    raw: Mapping[str, Any], suffix: str = ""
) -> tuple[PricingThreshold, ...]:
    """Collect above-N-tokens rates, highest threshold first."""
    by_threshold: dict[int, dict[str, Any]] = {}

    for key, value in raw.items():
        match = _THRESHOLD_KEY.match(key)
        if match is None or (match.group("suffix") or "") != suffix:
            continue
        rate = _to_decimal(value)
        if rate is None:
            continue
        amount = int(match.group("amount"))
        threshold = amount * 1000 if match.group("kilo") else amount
        entry = by_threshold.setdefault(
            threshold,
            {"key": f"above_{match.group('amount')}{match.group('kilo')}_tokens", "rates": {}},
        )
        entry["rates"][_THRESHOLD_BASES[match.group("base")]] = rate

    return tuple(
        PricingThreshold(
            threshold=threshold,
            key=entry["key"],
            rates=TokenRates(**entry["rates"]),
        )
        for threshold, entry in sorted(by_threshold.items(), reverse=True)
    )


def parse_pricing_modes(raw: Mapping[str, Any]) -> dict[PricingMode, PricingModeProfile]:
    profiles: dict[PricingMode, PricingModeProfile] = {}
    for mode, suffix in MODE_SUFFIXES.items():
        if mode == "standard":
            continue
        rates = parse_base_rates(raw, suffix)
        thresholds = parse_thresholds(raw, suffix)
        if any(getattr(rates, kind) is not None for kind in RATE_FIELDS) or thresholds:
            profiles[mode] = PricingModeProfile(rates=rates, thresholds=thresholds)
    return profiles


def overlay_rates(base: TokenRates, overrides: TokenRates) -> TokenRates:
    values: dict[str, Decimal | None] = {
        kind: getattr(overrides, kind)
        if getattr(overrides, kind) is not None
        else getattr(base, kind)
        for kind in RATE_FIELDS
    }
    return TokenRates(**values)


def resolve_mode_rates(
    base: TokenRates,
    profile: PricingModeProfile,
    mode: PricingMode,
    *,
    standard_base: TokenRates | None = None,
    provider: str | None = None,
) -> TokenRates:
    if mode != "batch":
        resolved = overlay_rates(base, profile.rates)
        if profile.rates.output is not None and profile.rates.reasoning is None:
            resolved = replace(resolved, reasoning=None)
        return resolved

    reference = standard_base or base
    reference_input = reference.input if reference.input is not None else base.input
    reference_output = reference.output if reference.output is not None else base.output
    input_ratio = (
        profile.rates.input / reference_input
        if profile.rates.input is not None
        and reference_input is not None
        and reference_input != _ZERO
        else Decimal("0.5")
    )
    output_ratio = (
        profile.rates.output / reference_output
        if profile.rates.output is not None
        and reference_output is not None
        and reference_output != _ZERO
        else input_ratio
    )
    provider_name = (provider or "").casefold()
    preserves_cache = provider_name == "gemini" or provider_name.startswith("vertex_ai")
    cache_ratio = Decimal("1") if preserves_cache else input_ratio
    discounted = replace(
        base,
        input=None if base.input is None else base.input * input_ratio,
        output=None if base.output is None else base.output * output_ratio,
        cache_read=(
            None if base.cache_read is None else base.cache_read * cache_ratio
        ),
        cache_read_audio=(
            None
            if base.cache_read_audio is None
            else base.cache_read_audio * cache_ratio
        ),
        cache_creation=(
            None
            if base.cache_creation is None
            else base.cache_creation * cache_ratio
        ),
        cache_creation_audio=(
            None
            if base.cache_creation_audio is None
            else base.cache_creation_audio * cache_ratio
        ),
        cache_creation_1h=(
            None
            if base.cache_creation_1h is None
            else base.cache_creation_1h * cache_ratio
        ),
        reasoning=None,
        input_audio=None if base.input_audio is None else base.input_audio * input_ratio,
        output_audio=None if base.output_audio is None else base.output_audio * output_ratio,
        input_image=None if base.input_image is None else base.input_image * input_ratio,
        output_image=None if base.output_image is None else base.output_image * output_ratio,
    )
    batch_overrides = replace(profile.rates, input=None, output=None)
    return overlay_rates(discounted, batch_overrides)


def parse_tiers(raw: Any) -> tuple[PricingTier, ...]:
    """Parse request-size tiers, sorted by range start. Returns () when unusable.

    Search-style entries (`input_cost_per_query` with `max_results_range`) carry
    no `range` and no per-token rate, so they yield () and leave the model
    unpriceable rather than being mistaken for token tiers.
    """
    if not isinstance(raw, (list, tuple)):
        return ()

    if not any(isinstance(entry, Mapping) and "range" in entry for entry in raw):
        return ()

    tiers: list[PricingTier] = []
    for entry in raw:
        if not isinstance(entry, Mapping) or "range" not in entry:
            return ()
        bounds = entry.get("range")
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            return ()
        start = _to_decimal(bounds[0])
        end = _to_decimal(bounds[1])
        if start is None or end is None or end <= start:
            return ()
        rates = parse_base_rates(entry)
        if rates.input is None:
            return ()
        tiers.append(PricingTier(range_start=start, range_end=end, rates=rates))

    tiers.sort(key=lambda tier: tier.range_start)
    if any(
        current.range_start < previous.range_end
        for previous, current in zip(tiers, tiers[1:], strict=False)
    ):
        return ()
    return tuple(tiers)


def parse_query_tiers(raw: Any) -> tuple[QueryPricingTier, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    if not any(
        isinstance(entry, Mapping) and "max_results_range" in entry for entry in raw
    ):
        return ()

    tiers: list[QueryPricingTier] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            return ()
        bounds = entry.get("max_results_range")
        rate = _to_decimal(entry.get("input_cost_per_query"))
        if (
            not isinstance(bounds, (list, tuple))
            or len(bounds) != 2
            or type(bounds[0]) is not int
            or type(bounds[1]) is not int
            or bounds[0] < 0
            or bounds[1] < bounds[0]
            or rate is None
        ):
            return ()
        tiers.append(QueryPricingTier(bounds[0], bounds[1], rate))

    tiers.sort(key=lambda tier: tier.range_start)
    if any(
        current.range_start <= previous.range_end
        for previous, current in zip(tiers, tiers[1:], strict=False)
    ):
        return ()
    return tuple(tiers)


def select_query_tier_rate(
    tiers: Sequence[QueryPricingTier], max_results: int
) -> Decimal | None:
    for tier in tiers:
        if tier.range_start <= max_results <= tier.range_end:
            return tier.rate
    return None


def resolve_rates(
    base: TokenRates,
    thresholds: Sequence[PricingThreshold],
    input_tokens: int,
    provider: str | None = None,
) -> tuple[TokenRates, str | None]:
    """Apply the highest matching threshold on top of the base rates.

    The trigger is the input token count alone. xAI includes the exact boundary;
    other providers require the count to exceed it. A threshold that declares
    only some rates leaves the rest on their base values.
    """
    inclusive = provider is not None and provider.casefold() == "xai"
    for threshold in thresholds:
        if input_tokens > threshold.threshold or (
            inclusive and input_tokens == threshold.threshold
        ):
            overrides: dict[str, Decimal | None] = {}
            for kind in RATE_FIELDS:
                value = getattr(threshold.rates, kind)
                if value is not None:
                    overrides[str(kind)] = value
            if threshold.rates.output is not None and threshold.rates.reasoning is None:
                overrides["reasoning"] = None
            return replace(base, **overrides), threshold.key
    return base, None


def select_tier_rates(
    tiers: Sequence[PricingTier], input_tokens: int
) -> TokenRates | None:
    """Select the request-wide rates for a total input token count."""
    if not tiers:
        return None

    token_count = Decimal(input_tokens)
    for tier in tiers:
        if tier.range_start < token_count <= tier.range_end:
            return tier.rates

    if token_count > 0:
        return tiers[-1].rates
    return None


def resolve_tier_rates(base: TokenRates, tier: TokenRates) -> TokenRates:
    """Resolve a selected tier with LiteLLM's per-kind fallback semantics."""
    tier_declares_output = tier.output is not None
    return TokenRates(
        input=tier.input,
        output=tier.output if tier.output is not None else base.output,
        cache_read=tier.cache_read,
        cache_read_audio=tier.cache_read_audio,
        cache_creation=tier.cache_creation,
        cache_creation_audio=tier.cache_creation_audio,
        cache_creation_1h=tier.cache_creation_1h,
        reasoning=(
            tier.reasoning
            if tier.reasoning is not None
            else None
            if tier_declares_output
            else base.reasoning
        ),
        input_audio=tier.input_audio,
        output_audio=tier.output_audio,
        input_image=tier.input_image,
        output_image=tier.output_image,
    )
