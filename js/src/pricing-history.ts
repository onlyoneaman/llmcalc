import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { gunzip, gzip } from "node:zlib";
import { promisify } from "node:util";

import { cacheFilePath } from "./cache.js";
import { getUserAgent } from "./config.js";
import { PricingHistoryError, PricingSchemaError } from "./errors.js";

const gzipAsync = promisify(gzip);
const gunzipAsync = promisify(gunzip);
const EARLIEST_SNAPSHOT_DATE = "2023-09-06";
const COMMITS_URL = "https://api.github.com/repos/BerriAI/litellm/commits";
const PRICING_PATH = "model_prices_and_context_window.json";
const SHA_PATTERN = /^[0-9a-f]{40}$/;
const HISTORY_TIMEOUT_MS = 10_000;

interface ResponseLike {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}

export type HistoryFetchLike = (
  input: string,
  init?: { headers?: Record<string, string>; signal?: AbortSignal }
) => Promise<ResponseLike>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function fetchWithTimeout(
  fetchImpl: HistoryFetchLike,
  url: string
): Promise<ResponseLike> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), HISTORY_TIMEOUT_MS);
  try {
    return await fetchImpl(url, {
      headers: { "User-Agent": getUserAgent() },
      signal: controller.signal
    });
  } finally {
    clearTimeout(timeout);
  }
}

export function validateSnapshotAt(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error("snapshotAt must use YYYY-MM-DD");
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new Error("snapshotAt must use YYYY-MM-DD");
  }
  const todayUtc = new Date().toISOString().slice(0, 10);
  if (value >= todayUtc) {
    throw new Error("snapshotAt must be a completed UTC date");
  }
  if (value < EARLIEST_SNAPSHOT_DATE) {
    throw new PricingHistoryError("LiteLLM snapshot history starts at 2023-09-06");
  }
  return value;
}

export function historyCacheDir(): string {
  return `${cacheFilePath()}.history`;
}

function datePath(snapshotAt: string): string {
  return path.join(historyCacheDir(), "dates", `${snapshotAt}.json`);
}

function snapshotPath(sha: string): string {
  return path.join(historyCacheDir(), "snapshots", `${sha}.json.gz`);
}

async function atomicWrite(targetPath: string, data: Uint8Array): Promise<void> {
  await mkdir(path.dirname(targetPath), { recursive: true });
  const temporary = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, data);
    await rename(temporary, targetPath);
  } finally {
    await rm(temporary, { force: true });
  }
}

async function loadSha(snapshotAt: string): Promise<string | null> {
  try {
    const payload: unknown = JSON.parse(await readFile(datePath(snapshotAt), "utf8"));
    const sha = isRecord(payload) ? payload.sha : null;
    return typeof sha === "string" && SHA_PATTERN.test(sha) ? sha : null;
  } catch {
    return null;
  }
}

async function saveSha(snapshotAt: string, sha: string): Promise<void> {
  await atomicWrite(datePath(snapshotAt), Buffer.from(JSON.stringify({ sha })));
}

async function loadSnapshot(sha: string): Promise<Record<string, unknown> | null> {
  try {
    const raw = await gunzipAsync(await readFile(snapshotPath(sha)));
    const payload: unknown = JSON.parse(raw.toString("utf8"));
    return isRecord(payload) ? payload : null;
  } catch {
    return null;
  }
}

async function saveSnapshot(sha: string, payload: Record<string, unknown>): Promise<void> {
  await atomicWrite(snapshotPath(sha), await gzipAsync(Buffer.from(JSON.stringify(payload))));
}

async function resolveSha(snapshotAt: string, fetchImpl: HistoryFetchLike): Promise<string> {
  const cutoff = `${snapshotAt}T23:59:59Z`;
  const url = new URL(COMMITS_URL);
  url.search = new URLSearchParams({
    sha: "main",
    path: PRICING_PATH,
    until: cutoff,
    per_page: "1"
  }).toString();

  let commits: unknown;
  try {
    const response = await fetchWithTimeout(fetchImpl, url.toString());
    if (!response.ok) {
      throw new Error(`unexpected status: ${response.status}`);
    }
    commits = await response.json();
  } catch {
    throw new PricingHistoryError("failed to resolve LiteLLM pricing snapshot");
  }
  if (!Array.isArray(commits) || commits.length === 0 || !isRecord(commits[0])) {
    throw new PricingHistoryError("no LiteLLM pricing snapshot exists for that date");
  }
  const commit = commits[0];
  const sha = commit.sha;
  const commitData = isRecord(commit.commit) ? commit.commit : null;
  const committer = commitData !== null && isRecord(commitData.committer)
    ? commitData.committer
    : null;
  const committedAt = committer?.date;
  if (
    typeof sha !== "string" ||
    !SHA_PATTERN.test(sha) ||
    typeof committedAt !== "string" ||
    Number.isNaN(Date.parse(committedAt))
  ) {
    throw new PricingHistoryError("GitHub returned an invalid pricing snapshot");
  }
  if (Date.parse(committedAt) > Date.parse(cutoff)) {
    throw new PricingHistoryError("GitHub returned a pricing snapshot after the requested date");
  }
  return sha;
}

async function fetchSnapshot(
  sha: string,
  fetchImpl: HistoryFetchLike
): Promise<Record<string, unknown>> {
  const url = `https://raw.githubusercontent.com/BerriAI/litellm/${sha}/${PRICING_PATH}`;
  try {
    const response = await fetchWithTimeout(fetchImpl, url);
    if (!response.ok) {
      throw new Error(`unexpected status: ${response.status}`);
    }
    const payload: unknown = await response.json();
    if (!isRecord(payload)) {
      throw new PricingSchemaError("pricing payload must be a JSON object");
    }
    return payload;
  } catch (error) {
    if (error instanceof PricingSchemaError) {
      throw error;
    }
    throw new PricingHistoryError("failed to fetch LiteLLM pricing snapshot");
  }
}

export async function getHistoricalPricingPayload(
  snapshotAt: string,
  fetchImpl: HistoryFetchLike
): Promise<Record<string, unknown>> {
  const normalized = validateSnapshotAt(snapshotAt);
  let sha = await loadSha(normalized);
  if (sha !== null) {
    const cached = await loadSnapshot(sha);
    if (cached !== null) {
      return cached;
    }
  }

  if (sha === null) {
    sha = await resolveSha(normalized, fetchImpl);
    try {
      await saveSha(normalized, sha);
    } catch {
      // Cache persistence must not block a valid snapshot.
    }
    const cached = await loadSnapshot(sha);
    if (cached !== null) {
      return cached;
    }
  }
  const payload = await fetchSnapshot(sha, fetchImpl);
  try {
    await saveSnapshot(sha, payload);
  } catch {
    // Cache persistence must not block a valid snapshot.
  }
  return payload;
}
