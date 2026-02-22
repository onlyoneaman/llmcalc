import {
  getDefaultCurrency,
  getPricingUrl,
  getUserAgent,
  resolveCacheTimeout
} from "./config.js";
import { loadCachedPricing, saveCachedPricing } from "./cache.js";
import { PricingFetchError, PricingSchemaError } from "./errors.js";
import { type ModelPricing, toModelPricing } from "./models.js";

export interface FetchResponseLike {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}

export interface FetchOptionsLike {
  headers?: Record<string, string>;
}

export type FetchLike = (
  input: string,
  init?: FetchOptionsLike
) => Promise<FetchResponseLike>;

export interface FetchPricingPayloadOptions {
  pricingUrl?: string;
  fetchImpl?: FetchLike;
}

export interface GetPricingTableOptions {
  cacheTimeout?: number;
  pricingUrl?: string;
  fetchImpl?: FetchLike;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getFetchImpl(fetchImpl?: FetchLike): FetchLike {
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

  let payload: unknown;
  try {
    const response = await activeFetch(source, {
      headers: { "User-Agent": getUserAgent() }
    });

    if (!response.ok) {
      throw new Error(`unexpected status: ${response.status}`);
    }

    payload = await response.json();
  } catch (error) {
    if (error instanceof PricingSchemaError) {
      throw error;
    }
    throw new PricingFetchError(`failed to fetch pricing data from ${source}`);
  }

  if (!isRecord(payload)) {
    throw new PricingSchemaError("pricing payload must be a JSON object");
  }

  return payload;
}

export function parsePricingPayload(payload: Record<string, unknown>): Record<string, ModelPricing> {
  const defaultCurrency = getDefaultCurrency();
  const wrappedData = payload.data;
  const rawTable = isRecord(wrappedData) ? wrappedData : payload;

  const parsed: Record<string, ModelPricing> = {};
  for (const [modelName, modelData] of Object.entries(rawTable)) {
    if (!isRecord(modelData)) {
      continue;
    }

    try {
      parsed[modelName] = toModelPricing(modelName, modelData, defaultCurrency);
    } catch {
      // Ignore non-model metadata entries.
    }
  }

  if (Object.keys(parsed).length === 0) {
    throw new PricingSchemaError("no valid model pricing entries found");
  }

  return parsed;
}

export async function getPricingTable(
  options: GetPricingTableOptions = {}
): Promise<Record<string, ModelPricing>> {
  const cacheTimeout = resolveCacheTimeout(options.cacheTimeout);

  const cachedData = await loadCachedPricing(cacheTimeout);
  if (cachedData !== null) {
    try {
      return parsePricingPayload(cachedData);
    } catch (error) {
      if (!(error instanceof PricingSchemaError)) {
        throw error;
      }
    }
  }

  try {
    const fetchedPayload = await fetchPricingPayload({
      ...(options.pricingUrl !== undefined ? { pricingUrl: options.pricingUrl } : {}),
      ...(options.fetchImpl !== undefined ? { fetchImpl: options.fetchImpl } : {})
    });

    const parsed = parsePricingPayload(fetchedPayload);
    await saveCachedPricing(fetchedPayload);
    return parsed;
  } catch (error) {
    if (!(error instanceof PricingFetchError)) {
      throw error;
    }

    if (cachedData !== null) {
      return parsePricingPayload(cachedData);
    }

    throw error;
  }
}
