import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { clearCache, cost, model, usage } from "../dist/api.js";

async function withCachePath(run) {
  const tmpDir = await mkdtemp(path.join(os.tmpdir(), "llmcalc-api-"));
  const cachePath = path.join(tmpDir, "pricing_cache.json");
  const previous = process.env.LLMCALC_CACHE_PATH;
  process.env.LLMCALC_CACHE_PATH = cachePath;

  try {
    await run();
  } finally {
    if (previous === undefined) {
      delete process.env.LLMCALC_CACHE_PATH;
    } else {
      process.env.LLMCALC_CACHE_PATH = previous;
    }
  }
}

function fakeFetch() {
  return async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      "gpt-5.1": {
        input_cost_per_token: "0.000001",
        output_cost_per_token: "0.000002",
        currency: "USD"
      }
    })
  });
}

test("model resolves prefixes", async () => {
  await withCachePath(async () => {
    const result = await model("openai:gpt-5.1", { fetchImpl: fakeFetch() });
    assert.ok(result);
    assert.equal(result.model, "gpt-5.1");
  });
});

test("cost computes deterministic totals", async () => {
  await withCachePath(async () => {
    const result = await cost("gpt-5.1", 1000, 500, { fetchImpl: fakeFetch() });
    assert.ok(result);
    assert.equal(result.inputCost.toString(), "0.001");
    assert.equal(result.outputCost.toString(), "0.001");
    assert.equal(result.totalCost.toString(), "0.002");
  });
});

test("cost returns null for unknown model", async () => {
  await withCachePath(async () => {
    const result = await cost("unknown", 1, 1, { fetchImpl: fakeFetch() });
    assert.equal(result, null);
  });
});

test("usage supports prompt/completion usage objects", async () => {
  await withCachePath(async () => {
    const result = await usage("gpt-5.1", { prompt_tokens: 1000, completion_tokens: 1000 }, { fetchImpl: fakeFetch() });
    assert.ok(result);
    assert.equal(result.totalCost.toString(), "0.003");
  });
});

test("cost rejects negative tokens", async () => {
  await withCachePath(async () => {
    await assert.rejects(() => cost("gpt-5.1", -1, 1, { fetchImpl: fakeFetch() }));
  });
});

test("clearCache clears persisted data", async () => {
  await withCachePath(async () => {
    await model("gpt-5.1", { fetchImpl: fakeFetch() });
    await clearCache();
    const result = await model("gpt-5.1", { fetchImpl: fakeFetch() });
    assert.ok(result);
  });
});
