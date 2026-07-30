import { Decimal } from "decimal.js";

export type Side = "input" | "output";

export interface PricingThreshold {
  threshold: number;
  key: string;
  inputRate: Decimal | null;
  outputRate: Decimal | null;
}

export interface PricingTier {
  rangeStart: Decimal;
  rangeEnd: Decimal;
  inputRate: Decimal | null;
  outputRate: Decimal | null;
}

// Anchored on _tokens$, which also excludes service-tier variants such as
// input_cost_per_token_above_200k_tokens_priority.
const THRESHOLD_KEY = /^(input|output)_cost_per_token_above_(\d+)(k?)_tokens$/;

const ZERO = new Decimal(0);

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

export function parseThresholds(raw: Record<string, unknown>): PricingThreshold[] {
  const byThreshold = new Map<
    number,
    { key: string; input: Decimal | null; output: Decimal | null }
  >();

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
    const entry = byThreshold.get(threshold) ?? {
      key: `above_${match[2]}${match[3]}_tokens`,
      input: null,
      output: null
    };
    if (match[1] === "input") {
      entry.input = rate;
    } else {
      entry.output = rate;
    }
    byThreshold.set(threshold, entry);
  }

  return [...byThreshold.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([threshold, entry]) => ({
      threshold,
      key: entry.key,
      inputRate: entry.input,
      outputRate: entry.output
    }));
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
    const inputRate = toDecimal(record["input_cost_per_token"]);
    const outputRate = toDecimal(record["output_cost_per_token"]);
    if (inputRate === null && outputRate === null) {
      continue;
    }
    tiers.push({ rangeStart: start, rangeEnd: end, inputRate, outputRate });
  }

  return tiers.sort((a, b) => a.rangeStart.comparedTo(b.rangeStart));
}

/**
 * Apply the highest matching threshold.
 *
 * The trigger is the input token count alone, and it is strictly greater, so a
 * request of exactly the threshold size stays on base rates. A threshold that
 * declares only an input rate leaves output on its base rate.
 */
export function resolveRates(
  baseInput: Decimal | null,
  baseOutput: Decimal | null,
  thresholds: readonly PricingThreshold[],
  inputTokens: number
): [Decimal | null, Decimal | null, string | null] {
  for (const threshold of thresholds) {
    if (inputTokens > threshold.threshold) {
      return [threshold.inputRate ?? baseInput, threshold.outputRate ?? baseOutput, threshold.key];
    }
  }
  return [baseInput, baseOutput, null];
}

function tierRate(tier: PricingTier, side: Side): Decimal {
  const rate = side === "input" ? tier.inputRate : tier.outputRate;
  return rate ?? ZERO;
}

/**
 * Sum per-slice cost at full precision. Tokens past the top range bill at the
 * last tier's rate.
 */
export function graduatedCost(
  tokens: number,
  tiers: readonly PricingTier[],
  side: Side
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
      total = total.add(end.sub(start).mul(tierRate(tier, side)));
      processed = end;
    }
  }

  if (processed.lessThan(remaining)) {
    const last = tiers[tiers.length - 1];
    if (last !== undefined) {
      total = total.add(remaining.sub(processed).mul(tierRate(last, side)));
    }
  }

  return total;
}
