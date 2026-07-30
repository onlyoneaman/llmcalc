"""Tiered and long-context pricing resolution.

Pure helpers: no I/O, no cache, no network. Upstream ships two mechanisms that
behave differently, so both are modelled separately:

* `above_{N}_tokens` rates replace the base rates for the whole request once the
  input token count exceeds the threshold, and apply to output as well as input.
* `tiered_pricing` ranges are graduated, billing each slice at its own rate.

Every parser here absorbs its own errors and degrades to an empty result.
`pricing_client` wraps per-model parsing in a bare `except`, so raising would
drop the model from the table entirely and turn a mispricing into a `None`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

Side = Literal["input", "output"]

# Anchored on _tokens$, which also excludes service-tier variants such as
# input_cost_per_token_above_200k_tokens_priority.
_THRESHOLD_KEY = re.compile(
    r"^(?P<side>input|output)_cost_per_token_above_(?P<amount>\d+)(?P<kilo>k?)_tokens$"
)

_ZERO = Decimal("0")


@dataclass(frozen=True)
class PricingThreshold:
    threshold: int
    key: str
    input_rate: Decimal | None
    output_rate: Decimal | None


@dataclass(frozen=True)
class PricingTier:
    range_start: Decimal
    range_end: Decimal
    input_rate: Decimal | None
    output_rate: Decimal | None


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
            {"key": f"above_{match.group('amount')}{match.group('kilo')}_tokens"},
        )
        entry[match.group("side")] = rate

    return tuple(
        PricingThreshold(
            threshold=threshold,
            key=entry["key"],
            input_rate=entry.get("input"),
            output_rate=entry.get("output"),
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
        input_rate = _to_decimal(entry.get("input_cost_per_token"))
        output_rate = _to_decimal(entry.get("output_cost_per_token"))
        if input_rate is None and output_rate is None:
            continue
        tiers.append(
            PricingTier(
                range_start=start,
                range_end=end,
                input_rate=input_rate,
                output_rate=output_rate,
            )
        )

    return tuple(sorted(tiers, key=lambda tier: tier.range_start))


def resolve_rates(
    base_input: Decimal | None,
    base_output: Decimal | None,
    thresholds: Sequence[PricingThreshold],
    input_tokens: int,
) -> tuple[Decimal | None, Decimal | None, str | None]:
    """Apply the highest matching threshold.

    The trigger is the input token count alone, and it is strictly greater, so a
    request of exactly the threshold size stays on base rates. A threshold that
    declares only an input rate leaves output on its base rate.
    """
    for threshold in thresholds:
        if input_tokens > threshold.threshold:
            return (
                threshold.input_rate if threshold.input_rate is not None else base_input,
                threshold.output_rate if threshold.output_rate is not None else base_output,
                threshold.key,
            )
    return base_input, base_output, None


def _tier_rate(tier: PricingTier, side: Side) -> Decimal:
    rate = tier.input_rate if side == "input" else tier.output_rate
    return rate if rate is not None else _ZERO


def graduated_cost(tokens: int, tiers: Sequence[PricingTier], side: Side) -> Decimal:
    """Sum per-slice cost at full precision. Tokens past the top range bill at
    the last tier's rate."""
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
            total += (end - start) * _tier_rate(tier, side)
            processed = end

    if processed < remaining:
        total += (remaining - processed) * _tier_rate(tiers[-1], side)

    return total
