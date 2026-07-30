import { Decimal } from "decimal.js";

export type RateKind = "input" | "output" | "cache_read" | "cache_creation" | "reasoning";

/** Upstream field name for each rate kind. */
export const RATE_FIELDS: Record<RateKind, string> = {
  input: "input_cost_per_token",
  output: "output_cost_per_token",
  cache_read: "cache_read_input_token_cost",
  cache_creation: "cache_creation_input_token_cost",
  reasoning: "output_cost_per_reasoning_token"
};

const RATE_KINDS = Object.keys(RATE_FIELDS) as RateKind[];

// DeepSeek and friends spell the cache-read rate differently.
const CACHE_READ_ALIASES = ["input_cost_per_token_cache_hit"] as const;

// When a model omits a rate, bill those tokens at this rate instead.
const RATE_FALLBACK: Partial<Record<RateKind, RateKind>> = {
  cache_read: "input",
  cache_creation: "input",
  reasoning: "output"
};

// Only these four have above_{N}_tokens variants upstream; reasoning has none.
const THRESHOLD_BASES: Record<string, RateKind> = {
  input_cost_per_token: "input",
  output_cost_per_token: "output",
  cache_read_input_token_cost: "cache_read",
  cache_creation_input_token_cost: "cache_creation"
};

// Anchored on _tokens$ and matched against the whole key, which excludes both
// service-tier variants (..._above_200k_tokens_priority) and the 1-hour cache
// TTL variants (..._above_1hr, ..._above_1hr_above_200k_tokens).
const THRESHOLD_KEY = new RegExp(
  `^(${Object.keys(THRESHOLD_BASES)
    .sort((a, b) => b.length - a.length)
    .join("|")})_above_(\\d+)(k?)_tokens$`
);

const ZERO = new Decimal(0);

/** Per-token rates for one pricing context. `null` means not declared. */
export interface TokenRates {
  input: Decimal | null;
  output: Decimal | null;
  cache_read: Decimal | null;
  cache_creation: Decimal | null;
  reasoning: Decimal | null;
}

export const EMPTY_RATES: TokenRates = {
  input: null,
  output: null,
  cache_read: null,
  cache_creation: null,
  reasoning: null
};

/** Return the rate for `kind`, falling back per `RATE_FALLBACK`. */
export function rateFor(rates: TokenRates, kind: RateKind): Decimal | null {
  const direct = rates[kind];
  if (direct !== null) {
    return direct;
  }
  const fallback = RATE_FALLBACK[kind];
  return fallback === undefined ? null : rates[fallback];
}

function ratesAreEmpty(rates: TokenRates): boolean {
  return rates.input === null && rates.output === null;
}

export interface PricingThreshold {
  threshold: number;
  key: string;
  rates: TokenRates;
}

export interface PricingTier {
  rangeStart: Decimal;
  rangeEnd: Decimal;
  rates: TokenRates;
}

function toDecimal(value: unknown): Decimal | null {
  if (value === null || value === undefined || typeof value === "boolean") {
    return null;
  }
  if (typeof value !== "number" && typeof value !== "string") {
    return null;
  }
  if (typeof value === "number" && !Number.isFinite(value)) {
    return null;
  }

  let parsed: Decimal;
  try {
    parsed = new Decimal(String(value).trim());
  } catch {
    return null;
  }

  if (!parsed.isFinite() || parsed.lessThan(0)) {
    return null;
  }
  return parsed;
}

/** Read the flat per-token rates a model declares. */
export function parseBaseRates(raw: Record<string, unknown>): TokenRates {
  const rates: TokenRates = { ...EMPTY_RATES };
  for (const kind of RATE_KINDS) {
    rates[kind] = toDecimal(raw[RATE_FIELDS[kind]]);
  }

  if (rates.cache_read === null) {
    for (const alias of CACHE_READ_ALIASES) {
      const aliased = toDecimal(raw[alias]);
      if (aliased !== null) {
        rates.cache_read = aliased;
        break;
      }
    }
  }

  return rates;
}

/** Collect above-N-tokens rates, highest threshold first. */
export function parseThresholds(raw: Record<string, unknown>): PricingThreshold[] {
  const byThreshold = new Map<number, { key: string; rates: TokenRates }>();

  for (const [key, value] of Object.entries(raw)) {
    const match = THRESHOLD_KEY.exec(key);
    if (match === null) {
      continue;
    }
    const rate = toDecimal(value);
    if (rate === null) {
      continue;
    }

    const amount = Number(match[2]);
    const threshold = match[3] === "k" ? amount * 1000 : amount;
    const entry =
      byThreshold.get(threshold) ??
      { key: `above_${match[2]}${match[3]}_tokens`, rates: { ...EMPTY_RATES } };
    const base = match[1];
    if (base !== undefined) {
      const kind = THRESHOLD_BASES[base];
      if (kind !== undefined) {
        entry.rates[kind] = rate;
      }
    }
    byThreshold.set(threshold, entry);
  }

  return [...byThreshold.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([threshold, entry]) => ({ threshold, key: entry.key, rates: entry.rates }));
}

/**
 * Parse graduated tiers, sorted by range start. Returns [] when unusable.
 *
 * Search-style entries (`input_cost_per_query` with `max_results_range`) carry
 * no `range` and no per-token rate, so they yield [] and leave the model
 * unpriceable rather than being mistaken for token tiers.
 */
export function parseTiers(raw: unknown): PricingTier[] {
  if (!Array.isArray(raw)) {
    return [];
  }

  const tiers: PricingTier[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null) {
      continue;
    }
    const record = entry as Record<string, unknown>;
    const bounds = record["range"];
    if (!Array.isArray(bounds) || bounds.length !== 2) {
      continue;
    }
    const start = toDecimal(bounds[0]);
    const end = toDecimal(bounds[1]);
    if (start === null || end === null || end.lessThanOrEqualTo(start)) {
      continue;
    }
    const rates = parseBaseRates(record);
    if (ratesAreEmpty(rates)) {
      continue;
    }
    tiers.push({ rangeStart: start, rangeEnd: end, rates });
  }

  return tiers.sort((a, b) => a.rangeStart.comparedTo(b.rangeStart));
}

/**
 * Apply the highest matching threshold on top of the base rates.
 *
 * The trigger is the input token count alone, and it is strictly greater, so a
 * request of exactly the threshold size stays on base rates. A threshold that
 * declares only some rates leaves the rest on their base values.
 */
export function resolveRates(
  base: TokenRates,
  thresholds: readonly PricingThreshold[],
  inputTokens: number
): [TokenRates, string | null] {
  for (const threshold of thresholds) {
    if (inputTokens > threshold.threshold) {
      const resolved: TokenRates = { ...base };
      for (const kind of RATE_KINDS) {
        const override = threshold.rates[kind];
        if (override !== null) {
          resolved[kind] = override;
        }
      }
      return [resolved, threshold.key];
    }
  }
  return [base, null];
}

/**
 * Sum per-slice cost at full precision. Tokens past the top range bill at the
 * last tier's rate.
 *
 * Each token kind is measured from zero independently, matching how litellm's
 * provider calculators call this.
 */
export function graduatedCost(
  tokens: number,
  tiers: readonly PricingTier[],
  kind: RateKind
): Decimal {
  if (tokens <= 0 || tiers.length === 0) {
    return ZERO;
  }

  let total = ZERO;
  let processed = ZERO;
  const remaining = new Decimal(tokens);

  for (const tier of tiers) {
    if (processed.greaterThanOrEqualTo(remaining)) {
      break;
    }
    if (remaining.lessThanOrEqualTo(tier.rangeStart)) {
      continue;
    }
    const start = Decimal.max(tier.rangeStart, processed);
    const end = Decimal.min(tier.rangeEnd, remaining);
    if (end.greaterThan(start)) {
      total = total.add(end.sub(start).mul(rateFor(tier.rates, kind) ?? ZERO));
      processed = end;
    }
  }

  if (processed.lessThan(remaining)) {
    const last = tiers[tiers.length - 1];
    if (last !== undefined) {
      total = total.add(remaining.sub(processed).mul(rateFor(last.rates, kind) ?? ZERO));
    }
  }

  return total;
}
