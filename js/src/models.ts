import { Decimal } from "decimal.js";

export interface CostBreakdown {
  inputCost: Decimal;
  outputCost: Decimal;
  totalCost: Decimal;
  currency: string;
}

export interface ModelPricing {
  model: string;
  inputCostPerToken: Decimal;
  outputCostPerToken: Decimal;
  provider: string | null;
  currency: string;
  lastUpdated: string | null;
}

export interface RawModelPricingInput {
  input_cost_per_token?: unknown;
  output_cost_per_token?: unknown;
  prompt_cost_per_token?: unknown;
  completion_cost_per_token?: unknown;
  input_cost_per_million_tokens?: unknown;
  output_cost_per_million_tokens?: unknown;
  provider?: unknown;
  currency?: unknown;
  last_updated?: unknown;
}

function parseDecimal(value: unknown): Decimal | null {
  if (value === null || value === undefined) {
    return null;
  }

  if (typeof value === "string") {
    const normalized = value.trim();
    if (normalized.length === 0) {
      return null;
    }
    const parsed = new Decimal(normalized);
    if (parsed.lessThan(0)) {
      throw new Error("pricing values must be non-negative");
    }
    return parsed;
  }

  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return null;
    }
    const parsed = new Decimal(value);
    if (parsed.lessThan(0)) {
      throw new Error("pricing values must be non-negative");
    }
    return parsed;
  }

  return null;
}

export function toModelPricing(
  model: string,
  raw: RawModelPricingInput,
  defaultCurrency = "USD"
): ModelPricing {
  let inputCost = parseDecimal(raw.input_cost_per_token);
  let outputCost = parseDecimal(raw.output_cost_per_token);

  if (inputCost === null) {
    inputCost = parseDecimal(raw.prompt_cost_per_token);
  }
  if (outputCost === null) {
    outputCost = parseDecimal(raw.completion_cost_per_token);
  }

  if (inputCost === null) {
    const perMillion = parseDecimal(raw.input_cost_per_million_tokens);
    if (perMillion !== null) {
      inputCost = perMillion.div(1_000_000);
    }
  }
  if (outputCost === null) {
    const perMillion = parseDecimal(raw.output_cost_per_million_tokens);
    if (perMillion !== null) {
      outputCost = perMillion.div(1_000_000);
    }
  }

  if (inputCost === null || outputCost === null) {
    throw new Error("Missing input/output token pricing fields");
  }

  const currency = typeof raw.currency === "string" && raw.currency.length > 0
    ? raw.currency
    : defaultCurrency;

  return {
    model,
    inputCostPerToken: inputCost,
    outputCostPerToken: outputCost,
    provider: typeof raw.provider === "string" ? raw.provider : null,
    currency,
    lastUpdated: typeof raw.last_updated === "string" ? raw.last_updated : null
  };
}
