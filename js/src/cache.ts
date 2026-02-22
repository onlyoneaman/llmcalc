import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export const CACHE_DIR_NAME = "llmcalc";
export const CACHE_FILE_NAME = "pricing_cache.json";

function defaultCacheDir(): string {
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Caches");
  }

  if (process.platform === "win32") {
    return process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local");
  }

  return process.env.XDG_CACHE_HOME ?? path.join(os.homedir(), ".cache");
}

export function cacheFilePath(): string {
  const override = process.env.LLMCALC_CACHE_PATH;
  if (override && override.trim().length > 0) {
    return override;
  }

  return path.join(defaultCacheDir(), CACHE_DIR_NAME, CACHE_FILE_NAME);
}

export async function loadCachedPricing(maxAgeSeconds: number): Promise<Record<string, unknown> | null> {
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

  const nowSeconds = Date.now() / 1000;
  if (nowSeconds - fetchedAt > maxAgeSeconds) {
    return null;
  }

  return data as Record<string, unknown>;
}

export async function saveCachedPricing(data: Record<string, unknown>): Promise<void> {
  const targetPath = cacheFilePath();
  const targetDir = path.dirname(targetPath);

  await mkdir(targetDir, { recursive: true });
  const payload = {
    fetched_at: Date.now() / 1000,
    data
  };

  await writeFile(targetPath, JSON.stringify(payload), "utf8");
}

export async function clearCache(): Promise<void> {
  const targetPath = cacheFilePath();
  await rm(targetPath, { force: true });
}
