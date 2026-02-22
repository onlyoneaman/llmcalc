import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { clearCache, loadCachedPricing, saveCachedPricing } from "../dist/cache.js";

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

test("clearCache removes cache file", async () => {
  await withCachePath(async () => {
    const data = {
      "gpt-5.1": { input_cost_per_token: 0.1, output_cost_per_token: 0.2 }
    };

    await saveCachedPricing(data);
    await clearCache();
    const loaded = await loadCachedPricing(3600);
    assert.equal(loaded, null);
  });
});
