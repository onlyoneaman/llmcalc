import { Decimal } from "./decimal.js";
import {
  type DiagnosticAction,
  type DiagnosticSeverity,
  type PricingDiagnostic
} from "./diagnostics.js";
import { type ModelPricing, toModelPricing } from "./models.js";
import { RATE_FIELDS, parseQueryTiers, parseTiers } from "./pricing-tiers.js";

const CORE_RATE_FIELDS = new Set([
  "input_cost_per_token",
  "output_cost_per_token",
  "prompt_cost_per_token",
  "completion_cost_per_token",
  "input_cost_per_million_tokens",
  "output_cost_per_million_tokens",
  "input_cost_per_token_cache_hit",
  "input_cost_per_query",
  "google_maps_grounding_cost_per_query",
  "regional_processing_uplift_multiplier_us",
  "regional_processing_uplift_multiplier_eu",
  "regional_endpoint_uplift_multiplier",
  ...Object.values(RATE_FIELDS)
]);
const MODE_RATE = new RegExp(
  `^(?:${Object.values(RATE_FIELDS).join("|")})_(?:batches|priority|flex)$`
);
const THRESHOLD_RATE = new RegExp(
  "^(?:input_cost_per_token|output_cost_per_token|cache_read_input_token_cost|" +
    "cache_creation_input_token_cost|cache_creation_input_token_cost_above_1hr)" +
    "_above_\\d+k?_tokens(?:_(?:batches|priority|flex))?$"
);
const METADATA_FIELDS = ["provider", "litellm_provider", "currency"] as const;
const SEARCH_CONTEXT_KEYS = new Set([
  "search_context_size_low",
  "search_context_size_medium",
  "search_context_size_high"
]);

export interface ModelPricingInspection {
  pricing: ModelPricing | null;
  diagnostics: PricingDiagnostic[];
}

function diagnostic(
  model: string,
  severity: DiagnosticSeverity,
  code: string,
  action: DiagnosticAction,
  path: Array<string | number>,
  message: string
): PricingDiagnostic {
  return { model, severity, code, action, path, message };
}

function validDecimal(value: unknown): boolean {
  if (value === null || value === undefined || typeof value === "boolean") {
    return false;
  }
  if (typeof value !== "number" && typeof value !== "string") {
    return false;
  }
  try {
    const parsed = new Decimal(String(value).trim());
    return parsed.isFinite() && parsed.greaterThanOrEqualTo(0);
  } catch {
    return false;
  }
}

function validMultiplier(value: unknown): boolean {
  return validDecimal(value) && new Decimal(String(value).trim()).greaterThan(0);
}

function isSupportedRate(key: string): boolean {
  return CORE_RATE_FIELDS.has(key) || MODE_RATE.test(key);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOtherSupportedPricing(raw: Record<string, unknown>): boolean {
  if (parseQueryTiers(raw.tiered_pricing).length > 0) {
    return true;
  }
  for (const [key, value] of Object.entries(raw)) {
    if (key === "tiered_pricing") {
      continue;
    }
    if ((isSupportedRate(key) || THRESHOLD_RATE.test(key)) && validDecimal(value)) {
      return true;
    }
    if (
      key === "search_context_cost_per_query" &&
      isRecord(value) &&
      Object.entries(value).some(
        ([context, rate]) => SEARCH_CONTEXT_KEYS.has(context) && validDecimal(rate)
      )
    ) {
      return true;
    }
  }
  return false;
}

function unsupportedCostField(key: string): boolean {
  return key.includes("cost") &&
    key !== "search_context_cost_per_query" &&
    !isSupportedRate(key) &&
    !THRESHOLD_RATE.test(key);
}

function matchesRawSchema(raw: Record<string, unknown>): boolean {
  const tiers = raw.tiered_pricing;
  if (tiers !== null && tiers !== undefined && !Array.isArray(tiers)) {
    return false;
  }

  const searchCosts = raw.search_context_cost_per_query;
  if (searchCosts !== null && searchCosts !== undefined) {
    if (!isRecord(searchCosts) || !Object.values(searchCosts).every(validDecimal)) {
      return false;
    }
  }

  const providerSpecific = raw.provider_specific_entry;
  if (providerSpecific !== null && providerSpecific !== undefined && !isRecord(providerSpecific)) {
    return false;
  }

  const billingUnit = raw.web_search_billing_unit;
  if (
    billingUnit !== null &&
    billingUnit !== undefined &&
    billingUnit !== "per_prompt" &&
    billingUnit !== "per_query"
  ) {
    return false;
  }

  for (const region of ["us", "eu"] as const) {
    const value = raw[`regional_processing_uplift_multiplier_${region}`];
    if (value !== null && value !== undefined && validDecimal(value)) {
      if (new Decimal(String(value).trim()).lessThanOrEqualTo(0)) {
        return false;
      }
    }
  }
  return true;
}

function schemaDiagnostic(model: string): PricingDiagnostic {
  return diagnostic(
    model,
    "error",
    "invalid_metadata",
    "skipped_entry",
    [],
    "pricing entry does not match the supported schema"
  );
}

export function inspectModelPricing(
  model: string,
  modelData: Record<string, unknown>,
  defaultCurrency: string
): ModelPricingInspection {
  const diagnostics: PricingDiagnostic[] = [];
  const sanitized = { ...modelData };

  for (const field of METADATA_FIELDS) {
    const value = sanitized[field];
    if (value !== null && value !== undefined && typeof value !== "string") {
      return {
        pricing: null,
        diagnostics: [
          diagnostic(
            model,
            "error",
            "invalid_metadata",
            "skipped_entry",
            [field],
            "pricing metadata must use the expected type"
          )
        ]
      };
    }
  }

  const lastUpdated = sanitized.last_updated;
  if (lastUpdated !== null && lastUpdated !== undefined && typeof lastUpdated !== "string") {
    diagnostics.push(
      diagnostic(
        model,
        "warning",
        "invalid_metadata",
        "ignored_field",
        ["last_updated"],
        "last_updated must be a string"
      )
    );
    delete sanitized.last_updated;
  }

  const providerSpecific = sanitized.provider_specific_entry;
  if (isRecord(providerSpecific)) {
    const cleaned = { ...providerSpecific };
    for (const field of ["us", "fast"] as const) {
      const value = cleaned[field];
      if (value !== null && value !== undefined && !validMultiplier(value)) {
        diagnostics.push(
          diagnostic(
            model,
            "warning",
            "invalid_rate",
            "ignored_field",
            ["provider_specific_entry", field],
            "provider pricing multiplier must be a finite positive decimal"
          )
        );
        delete cleaned[field];
      }
    }
    sanitized.provider_specific_entry = cleaned;
  }

  for (const [key, value] of Object.entries(sanitized)) {
    if (THRESHOLD_RATE.test(key) && !validDecimal(value)) {
      diagnostics.push(
        diagnostic(
          model,
          "warning",
          "invalid_threshold_rate",
          "ignored_field",
          [key],
          "long-context pricing rate is malformed"
        )
      );
      delete sanitized[key];
    } else if (isSupportedRate(key) && !validDecimal(value)) {
      return {
        pricing: null,
        diagnostics: [
          ...diagnostics,
          diagnostic(
            model,
            "error",
            "invalid_rate",
            "skipped_entry",
            [key],
            "supported pricing rate must be a finite non-negative decimal"
          )
        ]
      };
    }
  }

  const rawTiers = sanitized.tiered_pricing;
  const hasRangeTiers =
    Array.isArray(rawTiers) && rawTiers.some((entry) => isRecord(entry) && "range" in entry);
  const hasQueryTiers =
    Array.isArray(rawTiers) &&
    rawTiers.some((entry) => isRecord(entry) && "max_results_range" in entry);
  const invalidTiers =
    (hasRangeTiers && parseTiers(rawTiers).length === 0) ||
    (hasQueryTiers && parseQueryTiers(rawTiers).length === 0);
  if (invalidTiers) {
    const otherPricing = hasOtherSupportedPricing(sanitized);
    const invalidTier = diagnostic(
      model,
      otherPricing ? "warning" : "error",
      "invalid_tier_schedule",
      otherPricing ? "ignored_field" : "skipped_entry",
      ["tiered_pricing"],
      "request-tier pricing schedule is malformed"
    );
    if (!otherPricing) {
      return { pricing: null, diagnostics: [...diagnostics, invalidTier] };
    }
    diagnostics.push(invalidTier);
    delete sanitized.tiered_pricing;
  }

  if (!matchesRawSchema(sanitized)) {
    return { pricing: null, diagnostics: [...diagnostics, schemaDiagnostic(model)] };
  }

  let pricing: ModelPricing;
  try {
    pricing = toModelPricing(model, sanitized, defaultCurrency);
  } catch (error) {
    if (!(error instanceof Error) || error.message !== "Missing supported pricing fields") {
      throw error;
    }
    const hasCostField = Object.keys(sanitized).some((key) => key.includes("cost"));
    return {
      pricing: null,
      diagnostics: [
        ...diagnostics,
        diagnostic(
          model,
          "info",
          hasCostField ? "unsupported_pricing_unit" : "missing_supported_pricing",
          "skipped_entry",
          [],
          hasCostField
            ? "entry uses pricing units that llmcalc does not support"
            : "entry has no supported pricing fields"
        )
      ]
    };
  }
  for (const key of Object.keys(sanitized)) {
    if (unsupportedCostField(key)) {
      diagnostics.push(
        diagnostic(
          model,
          "info",
          "unsupported_pricing_unit",
          "ignored_field",
          [key],
          "pricing field uses a billing unit that llmcalc does not support"
        )
      );
    }
  }
  return { pricing, diagnostics };
}
