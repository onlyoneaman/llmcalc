import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  cacheFilePath,
  clearCache,
  loadCachedPricing,
  saveCachedPricing
} from "../dist/cache.js";

async function withCachePath(run) {
  const tmpDir = await mkdtemp(path.join(os.tmpdir(), "llmcalc-cache-"));
  const cachePath = path.join(tmpDir, "pricing_cache.json");
  const previous = process.env.LLMCALC_CACHE_PATH;
  process.env.LLMCALC_CACHE_PATH = cachePath;

  try {
    await run(cachePath);
  } finally {
    if (previous === undefined) {
      delete process.env.LLMCALC_CACHE_PATH;
    } else {
      process.env.LLMCALC_CACHE_PATH = previous;
    }
  }
}

test("saveCachedPricing + loadCachedPricing", async () => {
  await withCachePath(async () => {
    const data = {
      "gpt-5.1": { input_cost_per_token: 0.1, output_cost_per_token: 0.2 }
    };

    await saveCachedPricing(data);
    const loaded = await loadCachedPricing(3600);
    assert.deepEqual(loaded, data);
  });
});

test("loadCachedPricing returns null for expired entries", async () => {
  await withCachePath(async (cachePath) => {
    const payload = {
      fetched_at: Date.now() / 1000 - 10,
      data: {
        "gpt-5.1": { input_cost_per_token: 1, output_cost_per_token: 2 }
      }
    };

    await writeFile(cachePath, JSON.stringify(payload), "utf8");
    const loaded = await loadCachedPricing(1);
    assert.equal(loaded, null);
  });
});

test("loadCachedPricing rejects far-future timestamps", async () => {
  await withCachePath(async (cachePath) => {
    const payload = {
      fetched_at: Date.now() / 1000 + 3600,
      data: { model: { input_cost_per_token: 1 } }
    };

    await writeFile(cachePath, JSON.stringify(payload), "utf8");
    assert.equal(await loadCachedPricing(3600), null);
  });
});

test("loadCachedPricing rejects non-object payloads", async () => {
  await withCachePath(async (cachePath) => {
    for (const payload of [[], null, "cache", 1]) {
      await writeFile(cachePath, JSON.stringify(payload), "utf8");
      assert.equal(await loadCachedPricing(3600), null);
    }
  });
});

test("cache source is hashed and must match", async () => {
  await withCachePath(async (cachePath) => {
    const data = {
      "gpt-5.1": { input_cost_per_token: 0.1, output_cost_per_token: 0.2 }
    };
    const source = "https://example.com/private.json?token=secret";

    await saveCachedPricing(data, source);
    assert.deepEqual(await loadCachedPricing(3600, source), data);
    assert.equal(await loadCachedPricing(3600, "https://example.com/b.json"), null);
    const serialized = await readFile(cachePath, "utf8");
    assert.doesNotMatch(serialized, /private\.json|token=secret/);
    assert.match(serialized, /"source_hash":"[0-9a-f]{64}"/);
  });
});

test("clearCache removes current and historical caches", async () => {
  await withCachePath(async (cachePath) => {
    const data = {
      "gpt-5.1": { input_cost_per_token: 0.1, output_cost_per_token: 0.2 }
    };

    await saveCachedPricing(data);
    const historyPath = `${cachePath}.history`;
    await mkdir(path.join(historyPath, "snapshots"), { recursive: true });
    await writeFile(path.join(historyPath, "snapshots", "snapshot.json.gz"), "snapshot");
    await clearCache();
    const loaded = await loadCachedPricing(3600);
    assert.equal(loaded, null);
    await assert.rejects(stat(historyPath), { code: "ENOENT" });
  });
});

test("whitespace cache path uses the platform default", () => {
  const previous = process.env.LLMCALC_CACHE_PATH;
  process.env.LLMCALC_CACHE_PATH = "   ";
  try {
    assert.equal(path.basename(cacheFilePath()), "pricing_cache.json");
    assert.notEqual(cacheFilePath(), "   ");
  } finally {
    if (previous === undefined) {
      delete process.env.LLMCALC_CACHE_PATH;
    } else {
      process.env.LLMCALC_CACHE_PATH = previous;
    }
  }
});
