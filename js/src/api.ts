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

function validateNonNegative(value: number, fieldName: string): void {
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`${fieldName} must be a non-negative integer`);
  }
}

function valueFromMapping(
  usage: Record<string, unknown>,
  keyOptions: readonly string[]
): number | null {
  for (const key of keyOptions) {
    const value = usage[key];
    if (typeof value === "number" && Number.isInteger(value)) {
      return value;
    }
  }
  return null;
}

function getUsageTokens(usage: unknown): [number, number] {
  if (typeof usage !== "object" || usage === null) {
    throw new Error("usage must provide input/prompt tokens and output/completion tokens");
  }

  const dictUsage = usage as Record<string, unknown>;
  const inputTokens =
    valueFromMapping(dictUsage, ["input_tokens", "prompt_tokens"]) ??
    valueFromMapping(dictUsage, ["inputTokens", "promptTokens"]);
  const outputTokens =
    valueFromMapping(dictUsage, ["output_tokens", "completion_tokens"]) ??
    valueFromMapping(dictUsage, ["outputTokens", "completionTokens"]);

  if (inputTokens === null || outputTokens === null) {
    throw new Error("usage must provide input/prompt tokens and output/completion tokens");
  }

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
  validateNonNegative(inputTokens, "inputTokens");
  validateNonNegative(outputTokens, "outputTokens");

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
