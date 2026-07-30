import { Decimal } from "decimal.js";

import { clearCache as clearCacheFile } from "./cache.js";
import { DEFAULT_CACHE_TIMEOUT_SECONDS, resolveCacheTimeout } from "./config.js";
import { resolveModelKey } from "./normalize.js";
import { type FetchLike, getPricingTable } from "./pricing-client.js";
import { type CostBreakdown, type ModelPricing } from "./models.js";

export const DEFAULT_ROUNDING_PLACES = 6;

export interface ApiOptions {
  cacheTimeout?: number;
  pricingUrl?: string;
  fetchImpl?: FetchLike;
}

function roundMoney(amount: Decimal, places = DEFAULT_ROUNDING_PLACES): Decimal {
  return amount.toDecimalPlaces(places, Decimal.ROUND_HALF_UP);
}

export const TEXT_INPUT_MESSAGE =
  "llmcalc takes token counts, not text. Pass integer input/output token counts, " +
  "or the provider's usage object (for example response.usage). llmcalc does not " +
  "tokenize strings or message lists.";

const INPUT_KEYS = ["input_tokens", "prompt_tokens", "inputTokens", "promptTokens"] as const;
const OUTPUT_KEYS = [
  "output_tokens",
  "completion_tokens",
  "outputTokens",
  "completionTokens"
] as const;

function validateTokenCount(value: number, fieldName: string): void {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${fieldName} must be an integer, got ${typeof value}`);
  }
  if (value < 0) {
    throw new Error(`${fieldName} must be non-negative`);
  }
}

/** A key that is present but not an integer is an error, not a miss, so the
 * caller hears about the type instead of a misleading "not provided" message. */
function coerceTokenValue(value: unknown, fieldName: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${fieldName} must be an integer, got ${typeof value}`);
  }
  return value;
}

function valueFromMapping(
  usage: Record<string, unknown>,
  keyOptions: readonly string[],
  fieldName: string
): number | null {
  for (const key of keyOptions) {
    if (key in usage && usage[key] !== null && usage[key] !== undefined) {
      return coerceTokenValue(usage[key], fieldName);
    }
  }
  return null;
}

function getUsageTokens(usage: unknown): [number, number] {
  if (typeof usage === "string" || Array.isArray(usage)) {
    throw new Error(TEXT_INPUT_MESSAGE);
  }

  if (typeof usage !== "object" || usage === null) {
    throw new Error("usage must provide input/prompt tokens and output/completion tokens");
  }

  const dictUsage = usage as Record<string, unknown>;
  if ("messages" in dictUsage) {
    throw new Error(TEXT_INPUT_MESSAGE);
  }

  const inputTokens = valueFromMapping(dictUsage, INPUT_KEYS, "inputTokens");
  const outputTokens = valueFromMapping(dictUsage, OUTPUT_KEYS, "outputTokens");

  if (inputTokens === null || outputTokens === null) {
    throw new Error("usage must provide input/prompt tokens and output/completion tokens");
  }

  validateTokenCount(inputTokens, "inputTokens");
  validateTokenCount(outputTokens, "outputTokens");

  return [inputTokens, outputTokens];
}

export async function model(modelName: string, options: ApiOptions = {}): Promise<ModelPricing | null> {
  const table = await getPricingTable({
    cacheTimeout: resolveCacheTimeout(options.cacheTimeout),
    ...(options.pricingUrl !== undefined ? { pricingUrl: options.pricingUrl } : {}),
    ...(options.fetchImpl !== undefined ? { fetchImpl: options.fetchImpl } : {})
  });

  const resolved = resolveModelKey(modelName, Object.keys(table));
  if (resolved === null) {
    return null;
  }

  return table[resolved] ?? null;
}

export const modelAsync = model;

export async function cost(
  modelName: string,
  inputTokens: number,
  outputTokens: number,
  options: ApiOptions = {}
): Promise<CostBreakdown | null> {
  validateTokenCount(inputTokens, "inputTokens");
  validateTokenCount(outputTokens, "outputTokens");

  const modelCosts = await model(modelName, options);
  if (modelCosts === null) {
    return null;
  }

  const inputCost = roundMoney(new Decimal(inputTokens).mul(modelCosts.inputCostPerToken));
  const outputCost = roundMoney(new Decimal(outputTokens).mul(modelCosts.outputCostPerToken));
  const totalCost = roundMoney(inputCost.add(outputCost));

  return {
    inputCost,
    outputCost,
    totalCost,
    currency: modelCosts.currency
  };
}

export const costAsync = cost;

export async function usage(
  modelName: string,
  usageValue: unknown,
  options: ApiOptions = {}
): Promise<CostBreakdown | null> {
  const [inputTokens, outputTokens] = getUsageTokens(usageValue);
  return cost(modelName, inputTokens, outputTokens, options);
}

export const usageAsync = usage;

export async function clearCache(): Promise<void> {
  await clearCacheFile();
}

export const DEFAULT_CACHE_TIMEOUT = DEFAULT_CACHE_TIMEOUT_SECONDS;
