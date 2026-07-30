import { Decimal } from "decimal.js";

import { clearCache as clearCacheFile } from "./cache.js";
import { DEFAULT_CACHE_TIMEOUT_SECONDS, resolveCacheTimeout } from "./config.js";
import { resolveModelKey } from "./normalize.js";
import { type FetchLike, getPricingTable } from "./pricing-client.js";
import { type CostBreakdown, type ModelPricing, baseRates } from "./models.js";
import { graduatedCost, rateFor, resolveRates } from "./pricing-tiers.js";

export const DEFAULT_ROUNDING_PLACES = 6;

export interface ApiOptions {
  cacheTimeout?: number;
  pricingUrl?: string;
  fetchImpl?: FetchLike;
  /** Subset of inputTokens already served from cache. */
  cachedTokens?: number;
  /** Subset of inputTokens written to the cache. */
  cacheCreationTokens?: number;
  /** Subset of outputTokens spent on reasoning. */
  reasoningTokens?: number;
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

const PROMPT_DETAIL_KEYS = [
  "prompt_tokens_details",
  "promptTokensDetails",
  "input_tokens_details"
] as const;
const COMPLETION_DETAIL_KEYS = [
  "completion_tokens_details",
  "completionTokensDetails",
  "output_tokens_details"
] as const;
const CACHE_READ_KEYS = ["cache_read_input_tokens", "cacheReadInputTokens"] as const;
const CACHE_CREATION_KEYS = ["cache_creation_input_tokens", "cacheCreationInputTokens"] as const;
const CACHED_SUBSET_KEYS = ["cached_tokens", "cachedTokens"] as const;
const REASONING_KEYS = ["reasoning_tokens", "reasoningTokens"] as const;

/** Read a token count out of a nested details object. */
function nestedToken(
  usage: Record<string, unknown>,
  containerKeys: readonly string[],
  names: readonly string[]
): number {
  for (const containerKey of containerKeys) {
    const container = usage[containerKey];
    if (typeof container !== "object" || container === null) {
      continue;
    }
    const value = valueFromMapping(container as Record<string, unknown>, names, containerKey);
    if (value !== null) {
      return value;
    }
  }
  return 0;
}

/**
 * Normalize a provider usage object to inclusive token counts.
 *
 * Returns `[inputTokens, outputTokens, cached, cacheCreation, reasoning]` where
 * `inputTokens` is the total prompt count including both cache subsets and
 * `outputTokens` includes reasoning.
 *
 * The two provider conventions are distinguished by key name, not by guessing:
 * Anthropic reports `cache_read_input_tokens` *in addition to* `input_tokens`,
 * while OpenAI reports `prompt_tokens_details.cached_tokens` as a subset of
 * `prompt_tokens` already counted.
 */
function getUsageTokens(usage: unknown): [number, number, number, number, number] {
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

  let inputTokens = valueFromMapping(dictUsage, INPUT_KEYS, "inputTokens");
  const outputTokens = valueFromMapping(dictUsage, OUTPUT_KEYS, "outputTokens");

  if (inputTokens === null || outputTokens === null) {
    throw new Error("usage must provide input/prompt tokens and output/completion tokens");
  }

  validateTokenCount(inputTokens, "inputTokens");
  validateTokenCount(outputTokens, "outputTokens");

  const additiveRead = valueFromMapping(dictUsage, CACHE_READ_KEYS, "cacheReadInputTokens");
  const additiveCreation = valueFromMapping(
    dictUsage,
    CACHE_CREATION_KEYS,
    "cacheCreationInputTokens"
  );

  let cached: number;
  let creation: number;
  if (additiveRead !== null || additiveCreation !== null) {
    // Anthropic shape: cache counts sit outside inputTokens.
    cached = additiveRead ?? 0;
    creation = additiveCreation ?? 0;
    validateTokenCount(cached, "cacheReadInputTokens");
    validateTokenCount(creation, "cacheCreationInputTokens");
    inputTokens += cached + creation;
  } else {
    // OpenAI shape: cachedTokens is already inside promptTokens.
    cached = nestedToken(dictUsage, PROMPT_DETAIL_KEYS, CACHED_SUBSET_KEYS);
    creation = 0;
  }

  const reasoning = nestedToken(dictUsage, COMPLETION_DETAIL_KEYS, REASONING_KEYS);

  return [inputTokens, outputTokens, cached, creation, reasoning];
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

/**
 * Calculate model usage cost from token counts.
 *
 * `inputTokens` is the total prompt count, inclusive of `options.cachedTokens`
 * and `options.cacheCreationTokens`; `outputTokens` is inclusive of
 * `options.reasoningTokens`. Those subsets are re-priced at their own rates,
 * falling back to the plain input/output rate when a model does not declare
 * them.
 */
export async function cost(
  modelName: string,
  inputTokens: number,
  outputTokens: number,
  options: ApiOptions = {}
): Promise<CostBreakdown | null> {
  validateTokenCount(inputTokens, "inputTokens");
  validateTokenCount(outputTokens, "outputTokens");

  const cachedTokens = options.cachedTokens ?? 0;
  const cacheCreationTokens = options.cacheCreationTokens ?? 0;
  const reasoningTokens = options.reasoningTokens ?? 0;
  validateTokenCount(cachedTokens, "cachedTokens");
  validateTokenCount(cacheCreationTokens, "cacheCreationTokens");
  validateTokenCount(reasoningTokens, "reasoningTokens");

  if (cachedTokens + cacheCreationTokens > inputTokens) {
    throw new Error(
      "cachedTokens + cacheCreationTokens must not exceed inputTokens; " +
        "inputTokens is the total prompt count, inclusive of both"
    );
  }
  if (reasoningTokens > outputTokens) {
    throw new Error(
      "reasoningTokens must not exceed outputTokens; " +
        "outputTokens is the total completion count, inclusive of reasoning"
    );
  }

  const modelCosts = await model(modelName, options);
  if (modelCosts === null) {
    return null;
  }

  const textInput = inputTokens - cachedTokens - cacheCreationTokens;
  const textOutput = outputTokens - reasoningTokens;

  let rawTextInput: Decimal;
  let rawCacheRead: Decimal;
  let rawCacheCreation: Decimal;
  let rawTextOutput: Decimal;
  let rawReasoning: Decimal;
  let tierApplied: string | null;

  if (modelCosts.tieredPricing.length > 0) {
    const tiers = modelCosts.tieredPricing;
    rawTextInput = graduatedCost(textInput, tiers, "input");
    rawCacheRead = graduatedCost(cachedTokens, tiers, "cache_read");
    rawCacheCreation = graduatedCost(cacheCreationTokens, tiers, "cache_creation");
    rawTextOutput = graduatedCost(textOutput, tiers, "output");
    rawReasoning = graduatedCost(reasoningTokens, tiers, "reasoning");
    tierApplied = "tiered_pricing";
  } else {
    const [rates, tier] = resolveRates(
      baseRates(modelCosts),
      modelCosts.thresholds,
      inputTokens
    );
    const inputRate = rateFor(rates, "input");
    const outputRate = rateFor(rates, "output");
    if (inputRate === null || outputRate === null) {
      return null;
    }
    rawTextInput = new Decimal(textInput).mul(inputRate);
    rawCacheRead = new Decimal(cachedTokens).mul(rateFor(rates, "cache_read") ?? inputRate);
    rawCacheCreation = new Decimal(cacheCreationTokens).mul(
      rateFor(rates, "cache_creation") ?? inputRate
    );
    rawTextOutput = new Decimal(textOutput).mul(outputRate);
    rawReasoning = new Decimal(reasoningTokens).mul(rateFor(rates, "reasoning") ?? outputRate);
    tierApplied = tier;
  }

  const rawInput = rawTextInput.add(rawCacheRead).add(rawCacheCreation);
  const rawOutput = rawTextOutput.add(rawReasoning);

  // Round each emitted field once, and derive the total from the unrounded
  // legs so the parts cannot disagree with the whole.
  return {
    inputCost: roundMoney(rawInput),
    outputCost: roundMoney(rawOutput),
    totalCost: roundMoney(rawInput.add(rawOutput)),
    currency: modelCosts.currency,
    tierApplied,
    cacheReadCost: roundMoney(rawCacheRead),
    cacheCreationCost: roundMoney(rawCacheCreation),
    reasoningCost: roundMoney(rawReasoning)
  };
}

export const costAsync = cost;

export async function usage(
  modelName: string,
  usageValue: unknown,
  options: ApiOptions = {}
): Promise<CostBreakdown | null> {
  const [inputTokens, outputTokens, cachedTokens, cacheCreationTokens, reasoningTokens] =
    getUsageTokens(usageValue);
  return cost(modelName, inputTokens, outputTokens, {
    ...options,
    cachedTokens,
    cacheCreationTokens,
    reasoningTokens
  });
}

export const usageAsync = usage;

export async function clearCache(): Promise<void> {
  await clearCacheFile();
}

export const DEFAULT_CACHE_TIMEOUT = DEFAULT_CACHE_TIMEOUT_SECONDS;
