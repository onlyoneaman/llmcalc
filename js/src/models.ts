import { Decimal } from "./decimal.js";
import {
  type PricingMode,
  type PricingModeProfile,
  type QueryPricingTier,
  type PricingThreshold,
  type PricingTier,
  type TokenRates,
  parseBaseRates,
  parsePricingModes,
  parseQueryTiers,
  parseThresholds,
  parseTiers
} from "./pricing-tiers.js";

/**
 * Cost result for a token usage calculation.
 *
 * `inputCost` covers every prompt token, including any cache-read and
 * cache-creation portion; `outputCost` likewise includes reasoning tokens.
 * `totalCost` is their sum, so it always accounts for all token kinds passed.
 */
export interface CostBreakdown {
  inputCost: Decimal;
  outputCost: Decimal;
  totalCost: Decimal;
  currency: string;
  tierApplied: string | null;
  cacheReadCost: Decimal;
  cacheCreationCost: Decimal;
  cacheCreationAudioCost: Decimal;
  cacheCreation1hCost: Decimal;
  reasoningCost: Decimal;
  audioInputCost: Decimal;
  audioOutputCost: Decimal;
  imageInputCost: Decimal;
  imageOutputCost: Decimal;
  queryCost: Decimal;
  processingMode: PricingMode;
  regionalMultiplier: Decimal;
}

/**
 * Normalized token pricing for one model.
 *
 * Base rates are nullable: models priced purely through `tiered_pricing`
 * publish no flat per-token rate at all.
 */
export interface ModelPricing {
  model: string;
  inputCostPerToken: Decimal | null;
  outputCostPerToken: Decimal | null;
  cacheReadCostPerToken: Decimal | null;
  cacheReadAudioCostPerToken: Decimal | null;
  cacheCreationCostPerToken: Decimal | null;
  cacheCreationAudioCostPerToken: Decimal | null;
  cacheCreation1hCostPerToken: Decimal | null;
  reasoningCostPerToken: Decimal | null;
  inputAudioCostPerToken: Decimal | null;
  outputAudioCostPerToken: Decimal | null;
  inputImageCostPerToken: Decimal | null;
  outputImageCostPerToken: Decimal | null;
  inputCostPerQuery: Decimal | null;
  searchContextCostPerQuery: Record<string, Decimal>;
  googleMapsGroundingCostPerQuery: Decimal | null;
  webSearchBillingUnit: "per_prompt" | "per_query";
  regionalProcessingUplift: Record<string, Decimal>;
  thresholds: PricingThreshold[];
  tieredPricing: PricingTier[];
  queryPricing: QueryPricingTier[];
  pricingModes: Partial<Record<PricingMode, PricingModeProfile>>;
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
  tiered_pricing?: unknown;
  provider?: unknown;
  litellm_provider?: unknown;
  currency?: unknown;
  last_updated?: unknown;
  // Index signature keeps the above_{N}_tokens threshold keys reachable so
  // parseThresholds can see them.
  [key: string]: unknown;
}

function parseDecimal(value: unknown): Decimal | null {
  if (value === null || value === undefined) {
    return null;
  }

  if (typeof value === "string") {
    const normalized = value.trim();
    if (normalized.length === 0) {
      throw new Error("pricing values must be finite non-negative decimals");
    }
    const parsed = new Decimal(normalized);
    if (!parsed.isFinite() || parsed.lessThan(0)) {
      throw new Error("pricing values must be non-negative");
    }
    return parsed;
  }

  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error("pricing values must be finite non-negative decimals");
    }
    const parsed = new Decimal(value);
    if (parsed.lessThan(0)) {
      throw new Error("pricing values must be non-negative");
    }
    return parsed;
  }

  throw new Error("pricing values must be finite non-negative decimals");
}

function parseSearchCosts(value: unknown): Record<string, Decimal> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  const raw = value as Record<string, unknown>;
  const parsed: Record<string, Decimal> = {};
  for (const key of [
    "search_context_size_low",
    "search_context_size_medium",
    "search_context_size_high"
  ]) {
    const rate = parseDecimal(raw[key]);
    if (rate !== null) {
      parsed[key] = rate;
    }
  }
  return parsed;
}

function parseProviderMultiplier(value: unknown): Decimal | null {
  try {
    const parsed = parseDecimal(value);
    return parsed !== null && parsed.greaterThan(0) ? parsed : null;
  } catch {
    return null;
  }
}

export function toModelPricing(
  model: string,
  raw: RawModelPricingInput,
  defaultCurrency = "USD"
): ModelPricing {
  let inputCost = parseDecimal(raw.input_cost_per_token);
  let outputCost = parseDecimal(raw.output_cost_per_token);
  const promptCost = parseDecimal(raw.prompt_cost_per_token);
  const completionCost = parseDecimal(raw.completion_cost_per_token);
  const inputPerMillion = parseDecimal(raw.input_cost_per_million_tokens);
  const outputPerMillion = parseDecimal(raw.output_cost_per_million_tokens);

  if (inputCost === null) {
    inputCost = promptCost;
  }
  if (outputCost === null) {
    outputCost = completionCost;
  }

  if (inputCost === null) {
    if (inputPerMillion !== null) {
      inputCost = inputPerMillion.div(1_000_000);
    }
  }
  if (outputCost === null) {
    if (outputPerMillion !== null) {
      outputCost = outputPerMillion.div(1_000_000);
    }
  }

  const tieredPricing = parseTiers(raw.tiered_pricing);
  const queryPricing = parseQueryTiers(raw.tiered_pricing);
  const thresholds = parseThresholds(raw as Record<string, unknown>);
  const aux = parseBaseRates(raw as Record<string, unknown>);
  const pricingModes = parsePricingModes(raw as Record<string, unknown>);
  const providerSpecificEntry = raw.provider_specific_entry;
  const providerSpecific =
    typeof providerSpecificEntry === "object" &&
    providerSpecificEntry !== null &&
    !Array.isArray(providerSpecificEntry)
      ? providerSpecificEntry as Record<string, unknown>
      : {};
  const fastMultiplier = parseProviderMultiplier(providerSpecific.fast);
  if (fastMultiplier !== null && pricingModes.priority === undefined) {
    const scale = (rate: Decimal | null): Decimal | null =>
      rate === null ? null : rate.mul(fastMultiplier);
    pricingModes.priority = {
      rates: {
        input: scale(inputCost),
        output: scale(outputCost),
        cache_read: scale(aux.cache_read),
        cache_read_audio: scale(aux.cache_read_audio),
        cache_creation: scale(aux.cache_creation),
        cache_creation_audio: scale(aux.cache_creation_audio),
        cache_creation_1h: scale(aux.cache_creation_1h),
        reasoning: scale(aux.reasoning),
        input_audio: scale(aux.input_audio),
        output_audio: scale(aux.output_audio),
        input_image: scale(aux.input_image),
        output_image: scale(aux.output_image)
      },
      thresholds: []
    };
  }
  const inputCostPerQuery = parseDecimal(raw.input_cost_per_query);
  const searchContextCostPerQuery = parseSearchCosts(raw.search_context_cost_per_query);
  const googleMapsGroundingCostPerQuery = parseDecimal(
    raw.google_maps_grounding_cost_per_query
  );

  const hasBaseRate = inputCost !== null || outputCost !== null;
  const hasUnitRate =
    aux.cache_read !== null ||
    aux.cache_read_audio !== null ||
    aux.cache_creation !== null ||
    aux.cache_creation_audio !== null ||
    aux.cache_creation_1h !== null ||
    aux.reasoning !== null ||
    aux.input_audio !== null ||
    aux.output_audio !== null ||
    aux.input_image !== null ||
    aux.output_image !== null ||
    inputCostPerQuery !== null ||
    googleMapsGroundingCostPerQuery !== null ||
    Object.keys(searchContextCostPerQuery).length > 0 ||
    Object.keys(pricingModes).length > 0;
  if (!hasBaseRate && tieredPricing.length === 0 && queryPricing.length === 0 && !hasUnitRate) {
    throw new Error("Missing supported pricing fields");
  }

  const currency = typeof raw.currency === "string" && raw.currency.length > 0
    ? raw.currency
    : defaultCurrency;
  const webSearchBillingUnit = raw.web_search_billing_unit ?? "per_prompt";
  if (webSearchBillingUnit !== "per_prompt" && webSearchBillingUnit !== "per_query") {
    throw new Error("web_search_billing_unit must be per_prompt or per_query");
  }
  const regionalProcessingUplift: Record<string, Decimal> = {};
  for (const region of ["us", "eu"]) {
    const multiplier = parseDecimal(raw[`regional_processing_uplift_multiplier_${region}`]);
    if (multiplier !== null) {
      if (multiplier.lessThanOrEqualTo(0)) {
        throw new Error("regional uplift multipliers must be positive");
      }
      regionalProcessingUplift[region] = multiplier;
    }
  }
  if (
    regionalProcessingUplift.us === undefined &&
    Object.keys(providerSpecific).length > 0
  ) {
    const us = parseProviderMultiplier(providerSpecific.us);
    if (us !== null) {
      regionalProcessingUplift.us = us;
    }
  }
  const regional = parseDecimal(raw.regional_endpoint_uplift_multiplier);
  if (regional !== null) {
    if (regional.lessThanOrEqualTo(0)) {
      throw new Error("regional uplift multipliers must be positive");
    }
    regionalProcessingUplift.regional = regional;
  }

  return {
    model,
    inputCostPerToken: inputCost,
    outputCostPerToken: outputCost,
    cacheReadCostPerToken: aux.cache_read,
    cacheReadAudioCostPerToken: aux.cache_read_audio,
    cacheCreationCostPerToken: aux.cache_creation,
    cacheCreationAudioCostPerToken: aux.cache_creation_audio,
    cacheCreation1hCostPerToken: aux.cache_creation_1h,
    reasoningCostPerToken: aux.reasoning,
    inputAudioCostPerToken: aux.input_audio,
    outputAudioCostPerToken: aux.output_audio,
    inputImageCostPerToken: aux.input_image,
    outputImageCostPerToken: aux.output_image,
    inputCostPerQuery,
    searchContextCostPerQuery,
    googleMapsGroundingCostPerQuery,
    webSearchBillingUnit,
    regionalProcessingUplift,
    thresholds,
    tieredPricing,
    queryPricing,
    pricingModes,
    provider: typeof raw.litellm_provider === "string" && raw.litellm_provider.length > 0
      ? raw.litellm_provider
      : typeof raw.provider === "string"
        ? raw.provider
        : null,
    currency,
    lastUpdated: typeof raw.last_updated === "string" ? raw.last_updated : null
  };
}

/** Bundle the declared rates for `pricing-tiers` to resolve against. */
export function baseRates(pricing: ModelPricing): TokenRates {
  return {
    input: pricing.inputCostPerToken,
    output: pricing.outputCostPerToken,
    cache_read: pricing.cacheReadCostPerToken,
    cache_read_audio: pricing.cacheReadAudioCostPerToken,
    cache_creation: pricing.cacheCreationCostPerToken,
    cache_creation_audio: pricing.cacheCreationAudioCostPerToken,
    cache_creation_1h: pricing.cacheCreation1hCostPerToken,
    reasoning: pricing.reasoningCostPerToken,
    input_audio: pricing.inputAudioCostPerToken,
    output_audio: pricing.outputAudioCostPerToken,
    input_image: pricing.inputImageCostPerToken,
    output_image: pricing.outputImageCostPerToken
  };
}
