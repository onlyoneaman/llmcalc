import { clearCache as clearCacheFile } from "./cache.js";
import { DEFAULT_CACHE_TIMEOUT_SECONDS, resolveCacheTimeout } from "./config.js";
import { Decimal } from "./decimal.js";
import { type PricingParseResult } from "./diagnostics.js";
import { resolveModelKey } from "./normalize.js";
import { type FetchLike, getPricingReport, getPricingTable } from "./pricing-client.js";
import { type CostBreakdown, type ModelPricing, baseRates } from "./models.js";
import {
  type PricingMode,
  type TokenRates,
  rateFor,
  resolveModeRates,
  resolveRates,
  resolveTierRates,
  selectQueryTierRate,
  selectTierRates
} from "./pricing-tiers.js";
import { normalizeUsage, validateTokenCount } from "./usage-normalization.js";

export { TEXT_INPUT_MESSAGE } from "./usage-normalization.js";

export interface ApiOptions {
  cacheTimeout?: number;
  pricingUrl?: string;
  fetchImpl?: FetchLike;
  snapshotAt?: string;
  /** Subset of inputTokens already served from cache. */
  cachedTokens?: number;
  /** Subset of inputTokens written to the cache. */
  cacheCreationTokens?: number;
  /** Subset of outputTokens spent on reasoning. */
  reasoningTokens?: number;
  processingMode?: string;
  cacheCreationTokens1h?: number;
  cacheCreationAudioTokens?: number;
  cachedAudioTokens?: number;
  cachedImageTokens?: number;
  inputAudioTokens?: number;
  outputAudioTokens?: number;
  inputImageTokens?: number;
  outputImageTokens?: number;
  queryCount?: number;
  queryResults?: number;
  webSearchRequests?: number;
  webSearchContext?: string;
  mapsGroundingRequests?: number;
  region?: string;
}

export interface PricingReportOptions {
  cacheTimeout?: number;
  pricingUrl?: string;
  fetchImpl?: FetchLike;
  snapshotAt?: string;
  strict?: boolean;
}

const STANDARD_MODES = new Set(["standard", "default", "on_demand", "auto", "0"]);

function normalizeProcessingMode(value: string | undefined): PricingMode {
  const normalized = (value ?? "standard").trim().toLowerCase().replaceAll("-", "_");
  if (STANDARD_MODES.has(normalized)) {
    return "standard";
  }
  if (normalized === "batch" || normalized === "batches") {
    return "batch";
  }
  if (normalized === "priority" || normalized === "fast") {
    return "priority";
  }
  if (normalized === "flex") {
    return "flex";
  }
  throw new Error(`unsupported pricing mode: ${value ?? ""}`);
}

function resolveModelRates(
  pricing: ModelPricing,
  inputTokens: number,
  processingMode: PricingMode
): [TokenRates, string | null] {
  const standardBase = baseRates(pricing);
  let base = standardBase;
  let tierApplied: string | null = null;
  if (pricing.tieredPricing.length > 0) {
    const selected = selectTierRates(pricing.tieredPricing, inputTokens);
    if (selected !== null) {
      base = resolveTierRates(base, selected);
      tierApplied = "tiered_pricing";
    }
  }

  const profile = pricing.pricingModes[processingMode];
  if (profile !== undefined && processingMode !== "batch") {
    base = resolveModeRates(base, profile, processingMode);
  }
  let [rates, thresholdApplied] = resolveRates(
    base,
    pricing.thresholds,
    inputTokens,
    pricing.provider
  );
  tierApplied = thresholdApplied ?? tierApplied;
  if (profile !== undefined) {
    if (processingMode === "batch") {
      rates = resolveModeRates(rates, profile, processingMode, standardBase, pricing.provider);
    }
    const [modeRates, modeTier] = resolveRates(
      rates,
      profile.thresholds,
      inputTokens,
      pricing.provider
    );
    rates = modeRates;
    tierApplied = modeTier ?? tierApplied;
  }
  return [rates, tierApplied];
}

function componentCost(count: number, rate: Decimal | null): Decimal | null {
  if (count === 0) {
    return new Decimal(0);
  }
  return rate === null ? null : new Decimal(count).mul(rate);
}

export async function model(modelName: string, options: ApiOptions = {}): Promise<ModelPricing | null> {
  const table = await getPricingTable({
    cacheTimeout: resolveCacheTimeout(options.cacheTimeout),
    ...(options.pricingUrl !== undefined ? { pricingUrl: options.pricingUrl } : {}),
    ...(options.fetchImpl !== undefined ? { fetchImpl: options.fetchImpl } : {}),
    ...(options.snapshotAt !== undefined ? { snapshotAt: options.snapshotAt } : {})
  });

  const resolved = resolveModelKey(modelName, Object.keys(table));
  if (resolved === null) {
    return null;
  }

  return table[resolved] ?? null;
}

export const modelAsync = model;

export async function pricingReport(
  options: PricingReportOptions = {}
): Promise<PricingParseResult> {
  return getPricingReport({
    cacheTimeout: resolveCacheTimeout(options.cacheTimeout),
    ...(options.pricingUrl !== undefined ? { pricingUrl: options.pricingUrl } : {}),
    ...(options.fetchImpl !== undefined ? { fetchImpl: options.fetchImpl } : {}),
    ...(options.snapshotAt !== undefined ? { snapshotAt: options.snapshotAt } : {}),
    ...(options.strict !== undefined ? { strict: options.strict } : {})
  });
}

export const pricingReportAsync = pricingReport;

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
  const cacheCreationTokens1h = options.cacheCreationTokens1h ?? 0;
  const cacheCreationAudioTokens = options.cacheCreationAudioTokens ?? 0;
  const cachedAudioTokens = options.cachedAudioTokens ?? 0;
  const cachedImageTokens = options.cachedImageTokens ?? 0;
  const inputAudioTokens = options.inputAudioTokens ?? 0;
  const outputAudioTokens = options.outputAudioTokens ?? 0;
  const inputImageTokens = options.inputImageTokens ?? 0;
  const outputImageTokens = options.outputImageTokens ?? 0;
  const queryCount = options.queryCount ?? 0;
  const queryResults = options.queryResults;
  const webSearchRequests = options.webSearchRequests ?? 0;
  const mapsGroundingRequests = options.mapsGroundingRequests ?? 0;
  const processingMode = normalizeProcessingMode(options.processingMode);
  for (const [name, value] of [
    ["cachedTokens", cachedTokens],
    ["cacheCreationTokens", cacheCreationTokens],
    ["reasoningTokens", reasoningTokens],
    ["cacheCreationTokens1h", cacheCreationTokens1h],
    ["cacheCreationAudioTokens", cacheCreationAudioTokens],
    ["cachedAudioTokens", cachedAudioTokens],
    ["cachedImageTokens", cachedImageTokens],
    ["inputAudioTokens", inputAudioTokens],
    ["outputAudioTokens", outputAudioTokens],
    ["inputImageTokens", inputImageTokens],
    ["outputImageTokens", outputImageTokens],
    ["queryCount", queryCount],
    ["webSearchRequests", webSearchRequests],
    ["mapsGroundingRequests", mapsGroundingRequests]
  ] as const) {
    validateTokenCount(value, name);
  }
  if (queryResults !== undefined) {
    validateTokenCount(queryResults, "queryResults");
  }

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
  if (cacheCreationTokens1h > cacheCreationTokens) {
    throw new Error("cacheCreationTokens1h must not exceed cacheCreationTokens");
  }
  if (cacheCreationAudioTokens + cacheCreationTokens1h > cacheCreationTokens) {
    throw new Error(
      "cacheCreationAudioTokens + cacheCreationTokens1h must not exceed cacheCreationTokens"
    );
  }
  if (cachedAudioTokens + cachedImageTokens > cachedTokens) {
    throw new Error("cachedAudioTokens + cachedImageTokens must not exceed cachedTokens");
  }
  if (cachedAudioTokens > inputAudioTokens) {
    throw new Error("cachedAudioTokens must not exceed inputAudioTokens");
  }
  if (cachedAudioTokens + cacheCreationAudioTokens > inputAudioTokens) {
    throw new Error(
      "cachedAudioTokens + cacheCreationAudioTokens must not exceed inputAudioTokens"
    );
  }
  if (cachedImageTokens > inputImageTokens) {
    throw new Error("cachedImageTokens must not exceed inputImageTokens");
  }
  const uncachedAudioTokens = inputAudioTokens - cachedAudioTokens - cacheCreationAudioTokens;
  const uncachedImageTokens = inputImageTokens - cachedImageTokens;
  if (
    cachedTokens +
      cacheCreationTokens +
      uncachedAudioTokens +
      uncachedImageTokens >
    inputTokens
  ) {
    throw new Error("input token details must not exceed inputTokens");
  }
  if (reasoningTokens + outputAudioTokens + outputImageTokens > outputTokens) {
    throw new Error("output token details must not exceed outputTokens");
  }
  const requestedRegion = options.region?.trim().toLowerCase();
  const region = requestedRegion === "global" ? undefined : requestedRegion;
  if (
    region !== undefined &&
    region !== "us" &&
    region !== "eu" &&
    region !== "regional"
  ) {
    throw new Error("region must be 'global', 'regional', 'us', or 'eu'");
  }
  const webSearchContext = (options.webSearchContext ?? "medium").trim().toLowerCase();
  if (!new Set(["low", "medium", "high"]).has(webSearchContext)) {
    throw new Error("webSearchContext must be 'low', 'medium', or 'high'");
  }

  const modelCosts = await model(modelName, options);
  if (modelCosts === null) {
    return null;
  }
  if (processingMode !== "standard" && modelCosts.pricingModes[processingMode] === undefined) {
    throw new Error(`model ${modelCosts.model} does not declare ${processingMode} pricing`);
  }

  const hasNonTokenUsage = queryCount + webSearchRequests + mapsGroundingRequests > 0;
  if (inputTokens === 0 && outputTokens === 0 && !hasNonTokenUsage) {
    const zero = new Decimal(0);
    return {
      inputCost: zero,
      outputCost: zero,
      totalCost: zero,
      currency: modelCosts.currency,
      tierApplied: null,
      cacheReadCost: zero,
      cacheCreationCost: zero,
      cacheCreationAudioCost: zero,
      cacheCreation1hCost: zero,
      reasoningCost: zero,
      audioInputCost: zero,
      audioOutputCost: zero,
      imageInputCost: zero,
      imageOutputCost: zero,
      queryCost: zero,
      processingMode,
      regionalMultiplier: new Decimal(1)
    };
  }

  const textInput =
    inputTokens - cachedTokens - cacheCreationTokens - uncachedAudioTokens - uncachedImageTokens;
  const textOutput = outputTokens - reasoningTokens - outputAudioTokens - outputImageTokens;
  const [rates, tierApplied] = resolveModelRates(modelCosts, inputTokens, processingMode);
  if (cacheCreationTokens1h > 0 && rates.cache_creation_1h === null) {
    throw new Error(`model ${modelCosts.model} does not declare one-hour cache pricing`);
  }
  if (cacheCreationAudioTokens > 0 && rates.cache_creation_audio === null) {
    throw new Error(`model ${modelCosts.model} does not declare audio cache-write pricing`);
  }
  let queryRate = modelCosts.inputCostPerQuery;
  if (modelCosts.queryPricing.length > 0) {
    if (queryCount > 0 && queryResults === undefined) {
      throw new Error("queryResults is required for tiered per-query pricing");
    }
    if (queryResults !== undefined) {
      queryRate = selectQueryTierRate(modelCosts.queryPricing, queryResults);
      if (queryRate === null) {
        throw new Error(
          `model ${modelCosts.model} does not declare pricing for queryResults=${queryResults}`
        );
      }
    }
  } else if (queryResults !== undefined) {
    throw new Error(`model ${modelCosts.model} does not declare query-result tiers`);
  }
  if (queryCount > 0 && queryRate === null) {
    throw new Error(`model ${modelCosts.model} does not declare per-query pricing`);
  }
  if (
    webSearchRequests > 0 &&
    modelCosts.searchContextCostPerQuery[`search_context_size_${webSearchContext}`] === undefined
  ) {
    throw new Error(`model ${modelCosts.model} does not declare web-search pricing`);
  }
  if (mapsGroundingRequests > 0 && modelCosts.googleMapsGroundingCostPerQuery === null) {
    throw new Error(`model ${modelCosts.model} does not declare maps-grounding pricing`);
  }
  if (region !== undefined && modelCosts.regionalProcessingUplift[region] === undefined) {
    throw new Error(`model ${modelCosts.model} does not declare pricing for region '${region}'`);
  }
  const regionalMultiplier =
    region === undefined
      ? new Decimal(1)
      : modelCosts.regionalProcessingUplift[region] ?? new Decimal(1);

  const rawTextInput = componentCost(textInput, rateFor(rates, "input"));
  const rawTextOutput = componentCost(textOutput, rateFor(rates, "output"));
  const rawCacheRead = componentCost(
    cachedTokens - cachedAudioTokens,
    rateFor(rates, "cache_read")
  );
  const rawCachedAudio = componentCost(cachedAudioTokens, rateFor(rates, "cache_read_audio"));
  const rawCacheCreation5m = componentCost(
    cacheCreationTokens - cacheCreationTokens1h - cacheCreationAudioTokens,
    rateFor(rates, "cache_creation")
  );
  const rawCacheCreationAudio = componentCost(
    cacheCreationAudioTokens,
    rates.cache_creation_audio
  );
  const rawCacheCreation1h = componentCost(cacheCreationTokens1h, rates.cache_creation_1h);
  const rawReasoning = componentCost(reasoningTokens, rateFor(rates, "reasoning"));
  const rawAudioInput = componentCost(uncachedAudioTokens, rateFor(rates, "input_audio"));
  const rawAudioOutput = componentCost(outputAudioTokens, rateFor(rates, "output_audio"));
  const rawImageInput = componentCost(uncachedImageTokens, rateFor(rates, "input_image"));
  const rawImageOutput = componentCost(outputImageTokens, rateFor(rates, "output_image"));
  const rawDirectQuery = componentCost(queryCount, queryRate);

  const webBillable =
    webSearchRequests > 0 && modelCosts.webSearchBillingUnit === "per_prompt"
      ? 1
      : webSearchRequests;
  const mapsBillable =
    mapsGroundingRequests > 0 && modelCosts.webSearchBillingUnit === "per_prompt"
      ? 1
      : mapsGroundingRequests;
  const webCost = componentCost(
    webBillable,
    modelCosts.searchContextCostPerQuery[`search_context_size_${webSearchContext}`] ?? null
  );
  const mapsCost = componentCost(mapsBillable, modelCosts.googleMapsGroundingCostPerQuery);
  const rawCosts = [
    rawTextInput,
    rawTextOutput,
    rawCacheRead,
    rawCachedAudio,
    rawCacheCreation5m,
    rawCacheCreationAudio,
    rawCacheCreation1h,
    rawReasoning,
    rawAudioInput,
    rawAudioOutput,
    rawImageInput,
    rawImageOutput,
    rawDirectQuery,
    webCost,
    mapsCost
  ];
  if (rawCosts.some((value) => value === null)) {
    return null;
  }

  const scaled = (value: Decimal | null): Decimal =>
    (value ?? new Decimal(0)).mul(regionalMultiplier);
  const cacheReadCost = scaled((rawCacheRead ?? new Decimal(0)).add(rawCachedAudio ?? 0));
  const cacheCreation1hCost = scaled(rawCacheCreation1h);
  const cacheCreationCost = scaled(
    (rawCacheCreation5m ?? new Decimal(0))
      .add(rawCacheCreationAudio ?? 0)
      .add(rawCacheCreation1h ?? 0)
  );
  const cacheCreationAudioCost = scaled(rawCacheCreationAudio);
  const reasoningCost = scaled(rawReasoning);
  const audioInputCost = scaled(rawAudioInput);
  const audioOutputCost = scaled(rawAudioOutput);
  const imageInputCost = scaled(rawImageInput);
  const imageOutputCost = scaled(rawImageOutput);
  const queryCost = scaled(rawDirectQuery).add(webCost ?? 0).add(mapsCost ?? 0);
  const rawInput = scaled(rawTextInput)
    .add(cacheReadCost)
    .add(cacheCreationCost)
    .add(audioInputCost)
    .add(imageInputCost)
    .add(queryCost);
  const rawOutput = scaled(rawTextOutput)
    .add(reasoningCost)
    .add(audioOutputCost)
    .add(imageOutputCost);

  return {
    inputCost: rawInput,
    outputCost: rawOutput,
    totalCost: rawInput.add(rawOutput),
    currency: modelCosts.currency,
    tierApplied,
    cacheReadCost,
    cacheCreationCost,
    cacheCreationAudioCost,
    cacheCreation1hCost,
    reasoningCost,
    audioInputCost,
    audioOutputCost,
    imageInputCost,
    imageOutputCost,
    queryCost,
    processingMode,
    regionalMultiplier
  };
}

export const costAsync = cost;

export async function usage(
  modelName: string,
  usageValue: unknown,
  options: ApiOptions = {}
): Promise<CostBreakdown | null> {
  const normalized = normalizeUsage(usageValue);
  return cost(modelName, normalized.inputTokens, normalized.outputTokens, {
    ...options,
    cachedTokens: normalized.cachedTokens,
    cacheCreationTokens: normalized.cacheCreationTokens,
    reasoningTokens: normalized.reasoningTokens,
    ...((normalized.processingMode ?? options.processingMode) !== undefined
      ? { processingMode: normalized.processingMode ?? options.processingMode }
      : {}),
    cacheCreationTokens1h: normalized.cacheCreationTokens1h,
    cacheCreationAudioTokens: normalized.cacheCreationAudioTokens,
    cachedAudioTokens: normalized.cachedAudioTokens,
    cachedImageTokens: normalized.cachedImageTokens,
    inputAudioTokens: normalized.inputAudioTokens,
    outputAudioTokens: normalized.outputAudioTokens,
    inputImageTokens: normalized.inputImageTokens,
    outputImageTokens: normalized.outputImageTokens,
    queryCount: normalized.queryCount,
    webSearchRequests: normalized.webSearchRequests,
    mapsGroundingRequests: normalized.mapsGroundingRequests
  });
}

export const usageAsync = usage;

export async function clearCache(): Promise<void> {
  await clearCacheFile();
}

export const DEFAULT_CACHE_TIMEOUT = DEFAULT_CACHE_TIMEOUT_SECONDS;
