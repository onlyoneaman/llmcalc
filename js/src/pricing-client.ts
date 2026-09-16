import {
  DEFAULT_CURRENCY,
  DEFAULT_PRICING_URL,
  getDefaultCurrency,
  getPricingUrl,
  getUserAgent,
  resolveCacheTimeout
} from "./config.js";
import { loadCachedPricing, saveCachedPricing } from "./cache.js";
import { type PricingDiagnostic, type PricingParseResult } from "./diagnostics.js";
import { PricingFetchError, PricingSchemaError } from "./errors.js";
import { type ModelPricing } from "./models.js";
import { getHistoricalPricingPayload } from "./pricing-history.js";
import { inspectModelPricing } from "./pricing-parser.js";

export interface FetchResponseLike {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}

export interface FetchOptionsLike {
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export type FetchLike = (
  input: string,
  init?: FetchOptionsLike
) => Promise<FetchResponseLike>;

export interface FetchPricingPayloadOptions {
  pricingUrl?: string;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
}

export interface GetPricingTableOptions {
  cacheTimeout?: number;
  pricingUrl?: string;
  fetchImpl?: FetchLike;
  snapshotAt?: string;
}

export interface GetPricingReportOptions extends GetPricingTableOptions {
  strict?: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function getFetchImpl(fetchImpl?: FetchLike): FetchLike {
  if (fetchImpl !== undefined) {
    return fetchImpl;
  }

  const globalFetch = globalThis.fetch as unknown;
  if (typeof globalFetch !== "function") {
    throw new PricingFetchError("global fetch is unavailable in this environment");
  }

  return globalFetch as FetchLike;
}

export async function fetchPricingPayload(
  options: FetchPricingPayloadOptions = {}
): Promise<Record<string, unknown>> {
  const source = getPricingUrl(options.pricingUrl);
  const activeFetch = getFetchImpl(options.fetchImpl);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 10_000);

  let payload: unknown;
  try {
    const response = await activeFetch(source, {
      headers: { "User-Agent": getUserAgent() },
      signal: controller.signal
    });

    if (!response.ok) {
      throw new Error(`unexpected status: ${response.status}`);
    }

    payload = await response.json();
  } catch (error) {
    if (error instanceof PricingSchemaError) {
      throw error;
    }
    throw new PricingFetchError("failed to fetch pricing data");
  } finally {
    clearTimeout(timeout);
  }

  if (!isRecord(payload)) {
    throw new PricingSchemaError("pricing payload must be a JSON object");
  }

  return payload;
}

export function parsePricingPayload(
  payload: Record<string, unknown>,
  defaultCurrency = DEFAULT_CURRENCY
): Record<string, ModelPricing> {
  return parsePricingPayloadWithDiagnostics(payload, defaultCurrency).models;
}

export function parsePricingPayloadWithDiagnostics(
  payload: Record<string, unknown>,
  defaultCurrency = DEFAULT_CURRENCY,
  strict = false
): PricingParseResult {
  const wrappedData = payload.data;
  const rawTable = isRecord(wrappedData) ? wrappedData : payload;

  const parsed: Record<string, ModelPricing> = {};
  const diagnostics: PricingDiagnostic[] = [];
  for (const [modelName, modelData] of Object.entries(rawTable)) {
    if (modelName === "sample_spec") {
      diagnostics.push({
        model: modelName,
        severity: "info",
        code: "excluded_metadata_entry",
        action: "skipped_entry",
        path: [],
        message: "known pricing schema example was excluded"
      });
      continue;
    }
    if (!isRecord(modelData)) {
      diagnostics.push({
        model: modelName,
        severity: "error",
        code: "entry_not_object",
        action: "skipped_entry",
        path: [],
        message: "pricing entry must be an object"
      });
      continue;
    }

    const inspected = inspectModelPricing(modelName, modelData, defaultCurrency);
    diagnostics.push(...inspected.diagnostics);
    if (inspected.pricing !== null) {
      parsed[modelName] = inspected.pricing;
    }
  }

  if (Object.keys(parsed).length === 0) {
    throw new PricingSchemaError("no valid model pricing entries found", diagnostics);
  }
  if (strict && diagnostics.some((item) => item.severity !== "info")) {
    throw new PricingSchemaError(
      "pricing payload contains invalid entries",
      diagnostics
    );
  }

  return { models: parsed, diagnostics };
}

export async function getPricingReport(
  options: GetPricingReportOptions = {}
): Promise<PricingParseResult> {
  const cacheTimeout = resolveCacheTimeout(options.cacheTimeout);
  const source = getPricingUrl(options.pricingUrl);
  const defaultCurrency =
    source === DEFAULT_PRICING_URL ? DEFAULT_CURRENCY : getDefaultCurrency();
  if (options.snapshotAt !== undefined) {
    if (source !== DEFAULT_PRICING_URL) {
      throw new Error("snapshotAt is only supported with the default LiteLLM pricing source");
    }
    const historical = await getHistoricalPricingPayload(
      options.snapshotAt,
      getFetchImpl(options.fetchImpl)
    );
    return parsePricingPayloadWithDiagnostics(
      historical,
      DEFAULT_CURRENCY,
      options.strict ?? false
    );
  }

  const cachedData = await loadCachedPricing(cacheTimeout, source);
  if (cachedData !== null) {
    try {
      return parsePricingPayloadWithDiagnostics(
        cachedData,
        defaultCurrency,
        options.strict ?? false
      );
    } catch (error) {
      if (!(error instanceof PricingSchemaError)) {
        throw error;
      }
      if (options.strict === true) {
        throw error;
      }
    }
  }

  const fetchedPayload = await fetchPricingPayload({
    pricingUrl: source,
    ...(options.fetchImpl !== undefined ? { fetchImpl: options.fetchImpl } : {})
  });

  const report = parsePricingPayloadWithDiagnostics(
    fetchedPayload,
    defaultCurrency,
    options.strict ?? false
  );
  try {
    await saveCachedPricing(fetchedPayload, source);
  } catch {
    // Cache persistence must not discard pricing that was fetched and parsed successfully.
  }
  return report;
}

export async function getPricingTable(
  options: GetPricingTableOptions = {}
): Promise<Record<string, ModelPricing>> {
  return (await getPricingReport(options)).models;
}
