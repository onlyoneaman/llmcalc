import { Decimal } from "./decimal.js";

export type RateKind =
  | "input"
  | "output"
  | "cache_read"
  | "cache_read_audio"
  | "cache_creation"
  | "cache_creation_audio"
  | "cache_creation_1h"
  | "reasoning"
  | "input_audio"
  | "output_audio"
  | "input_image"
  | "output_image";
export type PricingMode = "standard" | "batch" | "priority" | "flex";

/** Upstream field name for each rate kind. */
export const RATE_FIELDS: Record<RateKind, string> = {
  input: "input_cost_per_token",
  output: "output_cost_per_token",
  cache_read: "cache_read_input_token_cost",
  cache_read_audio: "cache_read_input_audio_token_cost",
  cache_creation: "cache_creation_input_token_cost",
  cache_creation_audio: "cache_creation_input_audio_token_cost",
  cache_creation_1h: "cache_creation_input_token_cost_above_1hr",
  reasoning: "output_cost_per_reasoning_token",
  input_audio: "input_cost_per_audio_token",
  output_audio: "output_cost_per_audio_token",
  input_image: "input_cost_per_image_token",
  output_image: "output_cost_per_image_token"
};

export const MODE_SUFFIXES: Record<PricingMode, string> = {
  standard: "",
  batch: "batches",
  priority: "priority",
  flex: "flex"
};

const RATE_KINDS = Object.keys(RATE_FIELDS) as RateKind[];

// DeepSeek and friends spell the cache-read rate differently.
const CACHE_READ_ALIASES = ["input_cost_per_token_cache_hit"] as const;

// When a model omits a rate, bill those tokens at this rate instead.
const RATE_FALLBACK: Partial<Record<RateKind, RateKind>> = {
  cache_read: "input",
  cache_read_audio: "cache_read",
  cache_creation: "input",
  cache_creation_1h: "cache_creation",
  reasoning: "output",
  input_audio: "input",
  output_audio: "output",
  input_image: "input",
  output_image: "output"
};

// Rate families with above_{N}_tokens variants upstream; reasoning has none.
const THRESHOLD_BASES: Record<string, RateKind> = {
  input_cost_per_token: "input",
  output_cost_per_token: "output",
  cache_read_input_token_cost: "cache_read",
  cache_creation_input_token_cost: "cache_creation",
  cache_creation_input_token_cost_above_1hr: "cache_creation_1h"
};

// Matched against the whole key so unrelated suffixes cannot become tiers.
const THRESHOLD_KEY = new RegExp(
  `^(${Object.keys(THRESHOLD_BASES)
    .sort((a, b) => b.length - a.length)
    .join("|")})_above_(\\d+)(k?)_tokens(?:_(batches|priority|flex))?$`
);

/** Per-token rates for one pricing context. `null` means not declared. */
export interface TokenRates {
  input: Decimal | null;
  output: Decimal | null;
  cache_read: Decimal | null;
  cache_read_audio: Decimal | null;
  cache_creation: Decimal | null;
  cache_creation_audio: Decimal | null;
  cache_creation_1h: Decimal | null;
  reasoning: Decimal | null;
  input_audio: Decimal | null;
  output_audio: Decimal | null;
  input_image: Decimal | null;
  output_image: Decimal | null;
}

export const EMPTY_RATES: TokenRates = {
  input: null,
  output: null,
  cache_read: null,
  cache_read_audio: null,
  cache_creation: null,
  cache_creation_audio: null,
  cache_creation_1h: null,
  reasoning: null,
  input_audio: null,
  output_audio: null,
  input_image: null,
  output_image: null
};

/** Return the rate for `kind`, falling back per `RATE_FALLBACK`. */
export function rateFor(rates: TokenRates, kind: RateKind): Decimal | null {
  const direct = rates[kind];
  if (direct !== null) {
    return direct;
  }
  const fallback = RATE_FALLBACK[kind];
  return fallback === undefined ? null : rateFor(rates, fallback);
}

export interface PricingModeProfile {
  rates: TokenRates;
  thresholds: PricingThreshold[];
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

export interface QueryPricingTier {
  rangeStart: number;
  rangeEnd: number;
  rate: Decimal;
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
export function parseBaseRates(raw: Record<string, unknown>, suffix = ""): TokenRates {
  const rates: TokenRates = { ...EMPTY_RATES };
  const fieldSuffix = suffix.length > 0 ? `_${suffix}` : "";
  for (const kind of RATE_KINDS) {
    rates[kind] = toDecimal(raw[`${RATE_FIELDS[kind]}${fieldSuffix}`]);
  }

  if (suffix.length === 0 && rates.cache_read === null) {
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
export function parseThresholds(
  raw: Record<string, unknown>,
  suffix = ""
): PricingThreshold[] {
  const byThreshold = new Map<number, { key: string; rates: TokenRates }>();

  for (const [key, value] of Object.entries(raw)) {
    const match = THRESHOLD_KEY.exec(key);
    if (match === null || (match[4] ?? "") !== suffix) {
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

export function parsePricingModes(
  raw: Record<string, unknown>
): Partial<Record<PricingMode, PricingModeProfile>> {
  const profiles: Partial<Record<PricingMode, PricingModeProfile>> = {};
  for (const mode of ["batch", "priority", "flex"] as const) {
    const suffix = MODE_SUFFIXES[mode];
    const rates = parseBaseRates(raw, suffix);
    const thresholds = parseThresholds(raw, suffix);
    if (RATE_KINDS.some((kind) => rates[kind] !== null) || thresholds.length > 0) {
      profiles[mode] = { rates, thresholds };
    }
  }
  return profiles;
}

export function overlayRates(base: TokenRates, overrides: TokenRates): TokenRates {
  const resolved = { ...base };
  for (const kind of RATE_KINDS) {
    if (overrides[kind] !== null) {
      resolved[kind] = overrides[kind];
    }
  }
  return resolved;
}

export function resolveModeRates(
  base: TokenRates,
  profile: PricingModeProfile,
  mode: PricingMode,
  standardBase: TokenRates = base,
  provider: string | null = null
): TokenRates {
  if (mode !== "batch") {
    const resolved = overlayRates(base, profile.rates);
    if (profile.rates.output !== null && profile.rates.reasoning === null) {
      resolved.reasoning = null;
    }
    return resolved;
  }
  const referenceInput = standardBase.input ?? base.input;
  const referenceOutput = standardBase.output ?? base.output;
  const inputRatio =
    profile.rates.input !== null && referenceInput !== null && !referenceInput.isZero()
      ? profile.rates.input.div(referenceInput)
      : new Decimal("0.5");
  const outputRatio =
    profile.rates.output !== null && referenceOutput !== null && !referenceOutput.isZero()
      ? profile.rates.output.div(referenceOutput)
      : inputRatio;
  const providerName = provider?.toLowerCase() ?? "";
  const preservesCache = providerName === "gemini" || providerName.startsWith("vertex_ai");
  const cacheRatio = preservesCache ? new Decimal(1) : inputRatio;
  const discounted: TokenRates = {
    ...base,
    input: base.input?.mul(inputRatio) ?? null,
    output: base.output?.mul(outputRatio) ?? null,
    cache_read: base.cache_read?.mul(cacheRatio) ?? null,
    cache_read_audio: base.cache_read_audio?.mul(cacheRatio) ?? null,
    cache_creation: base.cache_creation?.mul(cacheRatio) ?? null,
    cache_creation_audio: base.cache_creation_audio?.mul(cacheRatio) ?? null,
    cache_creation_1h: base.cache_creation_1h?.mul(cacheRatio) ?? null,
    reasoning: null,
    input_audio: base.input_audio?.mul(inputRatio) ?? null,
    output_audio: base.output_audio?.mul(outputRatio) ?? null,
    input_image: base.input_image?.mul(inputRatio) ?? null,
    output_image: base.output_image?.mul(outputRatio) ?? null
  };
  return overlayRates(discounted, { ...profile.rates, input: null, output: null });
}

/**
 * Parse request-size tiers, sorted by range start. Returns [] when unusable.
 *
 * Search-style entries (`input_cost_per_query` with `max_results_range`) carry
 * no `range` and no per-token rate, so they yield [] and leave the model
 * unpriceable rather than being mistaken for token tiers.
 */
export function parseTiers(raw: unknown): PricingTier[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  if (!raw.some((entry) => typeof entry === "object" && entry !== null && "range" in entry)) {
    return [];
  }

  const tiers: PricingTier[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null || !("range" in entry)) {
      return [];
    }
    const record = entry as Record<string, unknown>;
    const bounds = record["range"];
    if (!Array.isArray(bounds) || bounds.length !== 2) {
      return [];
    }
    const start = toDecimal(bounds[0]);
    const end = toDecimal(bounds[1]);
    if (start === null || end === null || end.lessThanOrEqualTo(start)) {
      return [];
    }
    const rates = parseBaseRates(record);
    if (rates.input === null) {
      return [];
    }
    tiers.push({ rangeStart: start, rangeEnd: end, rates });
  }

  tiers.sort((a, b) => a.rangeStart.comparedTo(b.rangeStart));
  for (let index = 1; index < tiers.length; index += 1) {
    const previous = tiers[index - 1];
    const current = tiers[index];
    if (
      previous !== undefined &&
      current !== undefined &&
      current.rangeStart.lessThan(previous.rangeEnd)
    ) {
      return [];
    }
  }
  return tiers;
}

export function parseQueryTiers(raw: unknown): QueryPricingTier[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  if (!raw.some((entry) =>
    typeof entry === "object" && entry !== null && "max_results_range" in entry
  )) {
    return [];
  }

  const tiers: QueryPricingTier[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null) {
      return [];
    }
    const record = entry as Record<string, unknown>;
    const bounds = record["max_results_range"];
    const rate = toDecimal(record["input_cost_per_query"]);
    if (
      !Array.isArray(bounds) ||
      bounds.length !== 2 ||
      !Number.isSafeInteger(bounds[0]) ||
      !Number.isSafeInteger(bounds[1]) ||
      (bounds[0] as number) < 0 ||
      (bounds[1] as number) < (bounds[0] as number) ||
      rate === null
    ) {
      return [];
    }
    tiers.push({ rangeStart: bounds[0] as number, rangeEnd: bounds[1] as number, rate });
  }

  tiers.sort((a, b) => a.rangeStart - b.rangeStart);
  for (let index = 1; index < tiers.length; index += 1) {
    const previous = tiers[index - 1];
    const current = tiers[index];
    if (previous !== undefined && current !== undefined && current.rangeStart <= previous.rangeEnd) {
      return [];
    }
  }
  return tiers;
}

export function selectQueryTierRate(
  tiers: readonly QueryPricingTier[],
  maxResults: number
): Decimal | null {
  return tiers.find(
    (tier) => tier.rangeStart <= maxResults && maxResults <= tier.rangeEnd
  )?.rate ?? null;
}

/**
 * Apply the highest matching threshold on top of the base rates.
 *
 * The trigger is the input token count alone. xAI includes the exact boundary;
 * other providers require the count to exceed it. A threshold that declares
 * only some rates leaves the rest on their base values.
 */
export function resolveRates(
  base: TokenRates,
  thresholds: readonly PricingThreshold[],
  inputTokens: number,
  provider: string | null = null
): [TokenRates, string | null] {
  const inclusive = provider?.toLowerCase() === "xai";
  for (const threshold of thresholds) {
    if (inputTokens > threshold.threshold || (inclusive && inputTokens === threshold.threshold)) {
      const resolved: TokenRates = { ...base };
      for (const kind of RATE_KINDS) {
        const override = threshold.rates[kind];
        if (override !== null) {
          resolved[kind] = override;
        }
      }
      if (threshold.rates.output !== null && threshold.rates.reasoning === null) {
        resolved.reasoning = null;
      }
      return [resolved, threshold.key];
    }
  }
  return [base, null];
}

/** Select the request-wide rates for a total input token count. */
export function selectTierRates(
  tiers: readonly PricingTier[],
  inputTokens: number
): TokenRates | null {
  if (tiers.length === 0) {
    return null;
  }

  const tokenCount = new Decimal(inputTokens);
  if (tokenCount.lessThanOrEqualTo(0)) {
    return null;
  }
  for (const tier of tiers) {
    if (
      tokenCount.greaterThan(tier.rangeStart) &&
      tokenCount.lessThanOrEqualTo(tier.rangeEnd)
    ) {
      return tier.rates;
    }
  }

  const last = tiers[tiers.length - 1];
  return last?.rates ?? null;
}

export function resolveTierRates(base: TokenRates, tier: TokenRates): TokenRates {
  const tierDeclaresOutput = tier.output !== null;
  return {
    input: tier.input,
    output: tier.output ?? base.output,
    cache_read: tier.cache_read,
    cache_read_audio: tier.cache_read_audio,
    cache_creation: tier.cache_creation,
    cache_creation_audio: tier.cache_creation_audio,
    cache_creation_1h: tier.cache_creation_1h,
    reasoning: tier.reasoning ?? (tierDeclaresOutput ? null : base.reasoning),
    input_audio: tier.input_audio,
    output_audio: tier.output_audio,
    input_image: tier.input_image,
    output_image: tier.output_image
  };
}
