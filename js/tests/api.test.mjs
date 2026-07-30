import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

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

test("bool token counts are rejected", async () => {
  await withCachePath(async () => {
    await assert.rejects(
      () => usage("gpt-5.1", { prompt_tokens: true, completion_tokens: false }, { fetchImpl: fakeFetch() }),
      /must be an integer/
    );
  });
});

test("camel case usage keys are accepted", async () => {
  await withCachePath(async () => {
    const result = await usage("gpt-5.1", { inputTokens: 10, outputTokens: 5 }, { fetchImpl: fakeFetch() });
    assert.ok(result);
    assert.equal(result.totalCost.toFixed(6), "0.000020");
  });
});

test("string usage explains that text is unsupported", async () => {
  await assert.rejects(
    () => usage("gpt-5.1", "hello world", { fetchImpl: fakeFetch() }),
    /token counts, not text/
  );
});

test("messages array explains that text is unsupported", async () => {
  await assert.rejects(
    () => usage("gpt-5.1", [{ role: "user", content: "hi" }], { fetchImpl: fakeFetch() }),
    /token counts, not text/
  );
});

test("dict with messages explains that text is unsupported", async () => {
  await assert.rejects(
    () => usage("gpt-5.1", { messages: [{ role: "user", content: "hi" }] }, { fetchImpl: fakeFetch() }),
    /token counts, not text/
  );
});

test("float token counts are rejected", async () => {
  await assert.rejects(
    () => usage("gpt-5.1", { prompt_tokens: 1.5, completion_tokens: 2 }, { fetchImpl: fakeFetch() }),
    /must be an integer/
  );
});

const fixtureDir = dirname(fileURLToPath(import.meta.url));
const tierFixture = JSON.parse(
  readFileSync(join(fixtureDir, "..", "..", "tests", "fixtures", "tiered_cases.json"), "utf8")
);

function stubFetch(pricing) {
  return async () => ({
    ok: true,
    status: 200,
    json: async () => ({ "test-model": pricing })
  });
}

for (const testCase of [...tierFixture.thresholds, ...tierFixture.graduated]) {
  test(`cost matches fixture: ${testCase.name}`, async () => {
    await withCachePath(async () => {
      const result = await cost("test-model", testCase.input_tokens, testCase.output_tokens, {
        fetchImpl: stubFetch(testCase.pricing)
      });

      assert.ok(result !== null);
      assert.equal(result.inputCost.toFixed(6), testCase.expected.input_cost);
      assert.equal(result.outputCost.toFixed(6), testCase.expected.output_cost);
      assert.equal(result.totalCost.toFixed(6), testCase.expected.total_cost);
      assert.equal(result.tierApplied, testCase.expected.tier_applied);
    });
  });
}

test("total is computed from unrounded legs", async () => {
  await withCachePath(async () => {
    const result = await cost("test-model", 1, 1, {
      fetchImpl: stubFetch({
        input_cost_per_token: "0.0000005",
        output_cost_per_token: "0.0000005"
      })
    });

    assert.ok(result !== null);
    assert.equal(result.totalCost.toFixed(6), "0.000001");
  });
});

for (const testCase of tierFixture.cache_and_reasoning) {
  test(`cache/reasoning matches fixture: ${testCase.name}`, async () => {
    await withCachePath(async () => {
      const result = await cost("test-model", testCase.input_tokens, testCase.output_tokens, {
        fetchImpl: stubFetch(testCase.pricing),
        cachedTokens: testCase.cached_tokens ?? 0,
        cacheCreationTokens: testCase.cache_creation_tokens ?? 0,
        reasoningTokens: testCase.reasoning_tokens ?? 0
      });

      assert.ok(result !== null);
      const expected = testCase.expected;
      assert.equal(result.inputCost.toFixed(6), expected.input_cost);
      assert.equal(result.outputCost.toFixed(6), expected.output_cost);
      assert.equal(result.totalCost.toFixed(6), expected.total_cost);
      assert.equal(result.cacheReadCost.toFixed(6), expected.cache_read_cost);
      assert.equal(result.cacheCreationCost.toFixed(6), expected.cache_creation_cost);
      assert.equal(result.reasoningCost.toFixed(6), expected.reasoning_cost);
      assert.equal(result.tierApplied, expected.tier_applied);
      // The invariant that answers "is the total adding it up right?"
      assert.equal(
        result.inputCost.add(result.outputCost).toFixed(6),
        result.totalCost.toFixed(6)
      );
    });
  });
}

test("openai usage shape treats cached as a subset", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      {
        prompt_tokens: 100_000,
        completion_tokens: 1_000,
        prompt_tokens_details: { cached_tokens: 90_000 }
      },
      {
        fetchImpl: stubFetch({
          input_cost_per_token: "0.000005",
          output_cost_per_token: "0.00003",
          cache_read_input_token_cost: "0.0000005"
        })
      }
    );

    assert.ok(result !== null);
    assert.equal(result.totalCost.toFixed(6), "0.125000");
    assert.equal(result.cacheReadCost.toFixed(6), "0.045000");
  });
});

test("anthropic usage shape treats cache as additive", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      {
        input_tokens: 1_000,
        output_tokens: 500,
        cache_read_input_tokens: 90_000,
        cache_creation_input_tokens: 2_000
      },
      {
        fetchImpl: stubFetch({
          input_cost_per_token: "0.000003",
          output_cost_per_token: "0.000015",
          cache_read_input_token_cost: "0.0000003",
          cache_creation_input_token_cost: "0.00000375"
        })
      }
    );

    assert.ok(result !== null);
    assert.equal(result.totalCost.toFixed(6), "0.045000");
    assert.equal(result.cacheReadCost.toFixed(6), "0.027000");
    assert.equal(result.cacheCreationCost.toFixed(6), "0.007500");
  });
});

test("reasoning tokens read from completion details", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      {
        prompt_tokens: 1_000,
        completion_tokens: 5_000,
        completion_tokens_details: { reasoning_tokens: 4_000 }
      },
      {
        fetchImpl: stubFetch({
          input_cost_per_token: "0.000005",
          output_cost_per_token: "0.00003",
          output_cost_per_reasoning_token: "0.00006"
        })
      }
    );

    assert.ok(result !== null);
    assert.equal(result.totalCost.toFixed(6), "0.275000");
    assert.equal(result.reasoningCost.toFixed(6), "0.240000");
  });
});

test("cached tokens cannot exceed input tokens", async () => {
  await withCachePath(async () => {
    const opts = {
      fetchImpl: stubFetch({
        input_cost_per_token: "0.000005",
        output_cost_per_token: "0.00003"
      })
    };
    await assert.rejects(
      () => cost("test-model", 100, 10, { ...opts, cachedTokens: 101 }),
      /must not exceed inputTokens/
    );
    await assert.rejects(
      () => cost("test-model", 100, 10, { ...opts, cachedTokens: 60, cacheCreationTokens: 60 }),
      /must not exceed inputTokens/
    );
    await assert.rejects(
      () => cost("test-model", 100, 10, { ...opts, reasoningTokens: 11 }),
      /must not exceed outputTokens/
    );
  });
});
