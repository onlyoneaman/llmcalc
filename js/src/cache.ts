import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export const CACHE_DIR_NAME = "llmcalc";
export const CACHE_FILE_NAME = "pricing_cache.json";
const MAX_FUTURE_SKEW_SECONDS = 300;

function sourceHash(sourceUrl: string | undefined): string | null {
  return sourceUrl === undefined
    ? null
    : createHash("sha256").update(sourceUrl).digest("hex");
}

function defaultCacheDir(): string {
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Caches", CACHE_DIR_NAME);
  }

  if (process.platform === "win32") {
    const root = process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local");
    return path.join(root, CACHE_DIR_NAME, CACHE_DIR_NAME, "Cache");
  }

  const root = process.env.XDG_CACHE_HOME ?? path.join(os.homedir(), ".cache");
  return path.join(root, CACHE_DIR_NAME);
}

export function cacheFilePath(): string {
  const override = process.env.LLMCALC_CACHE_PATH;
  if (override && override.trim().length > 0) {
    return override;
  }

  return path.join(defaultCacheDir(), CACHE_FILE_NAME);
}

export async function loadCachedPricing(
  maxAgeSeconds: number,
  sourceUrl?: string
): Promise<Record<string, unknown> | null> {
  const targetPath = cacheFilePath();

  let raw: string;
  try {
    raw = await readFile(targetPath, "utf8");
  } catch {
    return null;
  }

  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return null;
  }

  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    return null;
  }

  const fetchedAt = (payload as { fetched_at?: unknown }).fetched_at;
  const data = (payload as { data?: unknown }).data;
  if (typeof fetchedAt !== "number" || !Number.isFinite(fetchedAt)) {
    return null;
  }

  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return null;
  }
  const storedHash = (payload as { source_hash?: unknown }).source_hash;
  const legacySource = (payload as { source_url?: unknown }).source_url;
  const comparableHash = typeof storedHash === "string"
    ? storedHash
    : typeof legacySource === "string"
      ? sourceHash(legacySource)
      : null;
  if (sourceUrl !== undefined && comparableHash !== sourceHash(sourceUrl)) {
    return null;
  }

  const nowSeconds = Date.now() / 1000;
  if (fetchedAt > nowSeconds + MAX_FUTURE_SKEW_SECONDS) {
    return null;
  }
  if (nowSeconds - fetchedAt > maxAgeSeconds) {
    return null;
  }

  return data as Record<string, unknown>;
}

export async function saveCachedPricing(
  data: Record<string, unknown>,
  sourceUrl?: string
): Promise<void> {
  const targetPath = cacheFilePath();
  const targetDir = path.dirname(targetPath);

  await mkdir(targetDir, { recursive: true });
  const payload = {
    fetched_at: Date.now() / 1000,
    source_hash: sourceHash(sourceUrl),
    data
  };

  const tempPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(tempPath, JSON.stringify(payload), "utf8");
    await rename(tempPath, targetPath);
  } finally {
    await rm(tempPath, { force: true });
  }
}

export async function clearCache(): Promise<void> {
  const targetPath = cacheFilePath();
  await rm(targetPath, { force: true });
  await rm(`${targetPath}.history`, { force: true, recursive: true });
}
