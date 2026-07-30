"""Tiered, long-context, cache and reasoning pricing resolution.

Pure helpers: no I/O, no cache, no network. Upstream ships two tiering
mechanisms that behave differently, so both are modelled separately:

* `above_{N}_tokens` rates replace the base rates for the whole request once the
  input token count exceeds the threshold, and apply to output as well as input.
* `tiered_pricing` ranges are graduated, billing each slice at its own rate.

Five rate kinds are tracked. `cache_read`, `cache_creation` and `reasoning` fall
back to the plain input/output rate when a model does not declare them, which
makes passing those token counts harmless for models without cache pricing.

Every parser here absorbs its own errors and degrades to an empty result.
`pricing_client` wraps per-model parsing in a bare `except`, so raising would
drop the model from the table entirely and turn a mispricing into a `None`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

RateKind = Literal["input", "output", "cache_read", "cache_creation", "reasoning"]

# Upstream field name for each rate kind.
RATE_FIELDS: dict[RateKind, str] = {
    "input": "input_cost_per_token",
    "output": "output_cost_per_token",
    "cache_read": "cache_read_input_token_cost",
    "cache_creation": "cache_creation_input_token_cost",
    "reasoning": "output_cost_per_reasoning_token",
}

# DeepSeek and friends spell the cache-read rate differently.
_CACHE_READ_ALIASES = ("input_cost_per_token_cache_hit",)

# When a model omits a rate, bill those tokens at this rate instead.
_RATE_FALLBACK: dict[RateKind, RateKind] = {
    "cache_read": "input",
    "cache_creation": "input",
    "reasoning": "output",
}

# Only these four have above_{N}_tokens variants upstream; reasoning has none.
_THRESHOLD_BASES: dict[str, RateKind] = {
    "input_cost_per_token": "input",
    "output_cost_per_token": "output",
    "cache_read_input_token_cost": "cache_read",
    "cache_creation_input_token_cost": "cache_creation",
}

# Anchored on _tokens$ and matched against the whole key, which excludes both
# service-tier variants (..._above_200k_tokens_priority) and the 1-hour cache
# TTL variants (..._above_1hr, ..._above_1hr_above_200k_tokens).
_THRESHOLD_KEY = re.compile(
    r"^(?P<base>"
    + "|".join(sorted(_THRESHOLD_BASES, key=len, reverse=True))
    + r")_above_(?P<amount>\d+)(?P<kilo>k?)_tokens$"
)

_ZERO = Decimal("0")


@dataclass(frozen=True)
class TokenRates:
    """Per-token rates for one pricing context. `None` means not declared."""

    input: Decimal | None = None
    output: Decimal | None = None
    cache_read: Decimal | None = None
    cache_creation: Decimal | None = None
    reasoning: Decimal | None = None

    def get(self, kind: RateKind) -> Decimal | None:
        """Return the rate for `kind`, falling back per `_RATE_FALLBACK`."""
        direct: Decimal | None = getattr(self, kind)
        if direct is not None:
            return direct
        fallback = _RATE_FALLBACK.get(kind)
        return None if fallback is None else getattr(self, fallback)

    def is_empty(self) -> bool:
        return self.input is None and self.output is None


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


def parse_base_rates(raw: Mapping[str, Any]) -> TokenRates:
    """Read the flat per-token rates a model declares."""
    values: dict[str, Decimal | None] = {
        kind: _to_decimal(raw.get(field)) for kind, field in RATE_FIELDS.items()
    }

    if values["cache_read"] is None:
        for alias in _CACHE_READ_ALIASES:
            aliased = _to_decimal(raw.get(alias))
            if aliased is not None:
                values["cache_read"] = aliased
                break

    return TokenRates(**values)


def parse_thresholds(raw: Mapping[str, Any]) -> tuple[PricingThreshold, ...]:
    """Collect above-N-tokens rates, highest threshold first."""
    by_threshold: dict[int, dict[str, Any]] = {}

    for key, value in raw.items():
        match = _THRESHOLD_KEY.match(key)
        if match is None:
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


def parse_tiers(raw: Any) -> tuple[PricingTier, ...]:
    """Parse graduated tiers, sorted by range start. Returns () when unusable.

    Search-style entries (`input_cost_per_query` with `max_results_range`) carry
    no `range` and no per-token rate, so they yield () and leave the model
    unpriceable rather than being mistaken for token tiers.
    """
    if not isinstance(raw, (list, tuple)):
        return ()

    tiers: list[PricingTier] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        bounds = entry.get("range")
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            continue
        start = _to_decimal(bounds[0])
        end = _to_decimal(bounds[1])
        if start is None or end is None or end <= start:
            continue
        rates = parse_base_rates(entry)
        if rates.is_empty():
            continue
        tiers.append(PricingTier(range_start=start, range_end=end, rates=rates))

    return tuple(sorted(tiers, key=lambda tier: tier.range_start))


def resolve_rates(
    base: TokenRates,
    thresholds: Sequence[PricingThreshold],
    input_tokens: int,
) -> tuple[TokenRates, str | None]:
    """Apply the highest matching threshold on top of the base rates.

    The trigger is the input token count alone, and it is strictly greater, so a
    request of exactly the threshold size stays on base rates. A threshold that
    declares only some rates leaves the rest on their base values.
    """
    for threshold in thresholds:
        if input_tokens > threshold.threshold:
            overrides: dict[str, Decimal] = {}
            for kind in RATE_FIELDS:
                value = getattr(threshold.rates, kind)
                if value is not None:
                    overrides[str(kind)] = value
            return replace(base, **overrides), threshold.key
    return base, None


def graduated_cost(tokens: int, tiers: Sequence[PricingTier], kind: RateKind) -> Decimal:
    """Sum per-slice cost at full precision. Tokens past the top range bill at
    the last tier's rate.

    Each token kind is measured from zero independently, matching how litellm's
    provider calculators call this.
    """
    if tokens <= 0 or not tiers:
        return _ZERO

    total = _ZERO
    processed = _ZERO
    remaining = Decimal(tokens)

    for tier in tiers:
        if processed >= remaining:
            break
        if remaining <= tier.range_start:
            continue
        start = max(tier.range_start, processed)
        end = min(tier.range_end, remaining)
        if end > start:
            total += (end - start) * (tier.rates.get(kind) or _ZERO)
            processed = end

    if processed < remaining:
        total += (remaining - processed) * (tiers[-1].rates.get(kind) or _ZERO)

    return total
