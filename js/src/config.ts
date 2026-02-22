import { readFileSync } from "node:fs";

export const APP_NAME = "llmcalc";
export const FALLBACK_VERSION = "0.1.2";
export const DEFAULT_CACHE_TIMEOUT_SECONDS = 43200;
export const DEFAULT_CURRENCY = "USD";
export const DEFAULT_PRICING_URL =
  "https://raw.githubusercontent.com/llmlite/llmlite/main/model_prices_and_context_window.json";

let cachedVersion: string | null = null;

export function getPackageVersion(): string {
  if (cachedVersion !== null) {
    return cachedVersion;
  }

  try {
    const packageJsonPath = new URL("../package.json", import.meta.url);
    const parsed = JSON.parse(readFileSync(packageJsonPath, "utf8")) as {
      version?: unknown;
    };
    if (typeof parsed.version === "string" && parsed.version.trim().length > 0) {
      cachedVersion = parsed.version;
      return cachedVersion;
    }
  } catch {
    // Fall back to a static version if package metadata is unavailable.
  }

  cachedVersion = FALLBACK_VERSION;
  return cachedVersion;
}

export function getUserAgent(): string {
  return `${APP_NAME}/${getPackageVersion()}`;
}

export function getPricingUrl(explicitUrl?: string): string {
  return explicitUrl ?? process.env.LLMCALC_PRICING_URL ?? DEFAULT_PRICING_URL;
}

export function getDefaultCurrency(): string {
  const raw = process.env.LLMCALC_CURRENCY?.trim().toUpperCase() ?? "";
  return raw || DEFAULT_CURRENCY;
}

export function resolveCacheTimeout(cacheTimeout?: number): number {
  if (cacheTimeout !== undefined) {
    if (cacheTimeout <= 0) {
      throw new Error("cacheTimeout must be positive");
    }
    return cacheTimeout;
  }

  const envValue = process.env.LLMCALC_CACHE_TIMEOUT;
  if (envValue === undefined) {
    return DEFAULT_CACHE_TIMEOUT_SECONDS;
  }

  const parsed = Number.parseInt(envValue, 10);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return DEFAULT_CACHE_TIMEOUT_SECONDS;
  }

  return parsed;
}
