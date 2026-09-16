import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { clearCache, cost, model, usage } from "../dist/api.js";
import { normalizeUsage } from "../dist/usage-normalization.js";

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

test("input-only model accepts zero output", async () => {
  await withCachePath(async () => {
    const result = await cost("mistral/mistral-embed", 1000, 0, {
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          "mistral/mistral-embed": { input_cost_per_token: "0.000001" }
        })
      })
    });

    assert.ok(result !== null);
    assert.equal(result.totalCost.toFixed(6), "0.001000");
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

test("Gemini usage counts cached content and thoughts correctly", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      {
        promptTokenCount: 100,
        candidatesTokenCount: 20,
        cachedContentTokenCount: 80,
        thoughtsTokenCount: 10
      },
      {
        fetchImpl: stubFetch({
          input_cost_per_token: "0.01",
          output_cost_per_token: "0.02",
          cache_read_input_token_cost: "0.001",
          output_cost_per_reasoning_token: "0.03"
        })
      }
    );

    assert.ok(result !== null);
    assert.equal(result.inputCost.toFixed(6), "0.280000");
    assert.equal(result.outputCost.toFixed(6), "0.700000");
    assert.equal(result.totalCost.toFixed(6), "0.980000");
  });
});

test("Gemini Live response token count is accepted", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      { promptTokenCount: 100, responseTokenCount: 20 },
      { fetchImpl: stubFetch({ input_cost_per_token: "0.01", output_cost_per_token: "0.02" }) }
    );

    assert.ok(result !== null);
    assert.equal(result.totalCost.toFixed(6), "1.400000");
  });
});

test("Gemini usage treats tool-use prompt tokens as an included subset", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      {
        promptTokenCount: 100,
        candidatesTokenCount: 20,
        thoughtsTokenCount: 10,
        toolUsePromptTokenCount: 30,
        totalTokenCount: 130
      },
      {
        fetchImpl: stubFetch({
          input_cost_per_token: "0.01",
          output_cost_per_token: "0.02"
        })
      }
    );

    assert.ok(result !== null);
    assert.equal(result.inputCost.toFixed(6), "1.000000");
    assert.equal(result.outputCost.toFixed(6), "0.600000");
    assert.equal(result.totalCost.toFixed(6), "1.600000");
  });
});

test("Gemini usage treats tool-use prompt tokens as additive when total confirms it", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      {
        prompt_token_count: 100,
        candidates_token_count: 20,
        thoughts_token_count: 10,
        tool_use_prompt_token_count: 30,
        total_token_count: 160
      },
      {
        fetchImpl: stubFetch({
          input_cost_per_token: "0.01",
          output_cost_per_token: "0.02"
        })
      }
    );

    assert.ok(result !== null);
    assert.equal(result.inputCost.toFixed(6), "1.300000");
    assert.equal(result.outputCost.toFixed(6), "0.600000");
    assert.equal(result.totalCost.toFixed(6), "1.900000");
  });
});

test("Gemini usage rejects ambiguous or inconsistent tool-use totals", async () => {
  const usageValue = {
    promptTokenCount: 100,
    candidatesTokenCount: 20,
    toolUsePromptTokenCount: 30
  };

  await assert.rejects(
    () => usage("test-model", usageValue, { fetchImpl: stubFetch({}) }),
    /totalTokenCount is required/
  );
  await assert.rejects(
    () =>
      usage(
        "test-model",
        { ...usageValue, totalTokenCount: 140 },
        { fetchImpl: stubFetch({}) }
      ),
    /inconsistent/
  );
});

test("Bedrock usage treats cache reads and writes as additive", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      {
        inputTokens: 100,
        outputTokens: 20,
        cacheReadInputTokens: 50,
        cacheWriteInputTokens: 30
      },
      {
        fetchImpl: stubFetch({
          input_cost_per_token: "0.01",
          output_cost_per_token: "0.03",
          cache_read_input_token_cost: "0.001",
          cache_creation_input_token_cost: "0.02"
        })
      }
    );

    assert.ok(result !== null);
    assert.equal(result.totalCost.toFixed(6), "2.250000");
  });
});

test("one-hour cache writes are priced", async () => {
  const cases = [
    {
      input_tokens: 100,
      output_tokens: 20,
      cache_creation_input_tokens: 30,
      cache_creation: {
        ephemeral_5m_input_tokens: 20,
        ephemeral_1h_input_tokens: 10
      }
    },
    {
      inputTokens: 100,
      outputTokens: 20,
      cacheWriteInputTokens: 30,
      cacheDetails: [
        { ttl: "5m", inputTokens: 20 },
        { ttl: "1h", inputTokens: 10 }
      ]
    }
  ];

  for (const usageValue of cases) {
    await withCachePath(async () => {
      const result = await usage("test-model", usageValue, {
        fetchImpl: stubFetch({
          input_cost_per_token: "0.01",
          output_cost_per_token: "0.02",
          cache_creation_input_token_cost: "0.012",
          cache_creation_input_token_cost_above_1hr: "0.02"
        })
      });
      assert.ok(result !== null);
      assert.equal(result.cacheCreation1hCost.toFixed(), "0.2");
    });
  }
});

test("cache duration details must match their aggregate", () => {
  assert.throws(
    () => normalizeUsage({
      input_tokens: 100,
      output_tokens: 20,
      cache_creation_input_tokens: 30,
      cache_creation: {
        ephemeral_5m_input_tokens: 20,
        ephemeral_1h_input_tokens: 5
      }
    }),
    /must sum/
  );
});

test("Gemini media and cached modalities are normalized", () => {
  const normalized = normalizeUsage({
    promptTokenCount: 100,
    responseTokenCount: 50,
    cachedContentTokenCount: 20,
    promptTokensDetails: [
      { modality: "AUDIO", tokenCount: 30 },
      { modality: "DOCUMENT", tokenCount: 20 },
      { modality: "TEXT", tokenCount: 50 }
    ],
    cacheTokensDetails: [
      { modality: "AUDIO", tokenCount: 10 },
      { modality: "DOCUMENT", tokenCount: 5 }
    ],
    responseTokensDetails: [
      { modality: "AUDIO", tokenCount: 10 },
      { modality: "IMAGE", tokenCount: 5 }
    ]
  });

  assert.equal(normalized.inputAudioTokens, 30);
  assert.equal(normalized.inputImageTokens, 20);
  assert.equal(normalized.cachedAudioTokens, 10);
  assert.equal(normalized.cachedImageTokens, 5);
  assert.equal(normalized.outputAudioTokens, 10);
  assert.equal(normalized.outputImageTokens, 5);
});

test("query and xAI tool usage are normalized", () => {
  const normalized = normalizeUsage({
    inputTokens: 10,
    outputTokens: 5,
    searchUnits: 2,
    serverSideToolUsageDetails: { webSearchCalls: 3 },
    googleMapsGroundingRequests: 4
  });

  assert.equal(normalized.queryCount, 2);
  assert.equal(normalized.webSearchRequests, 3);
  assert.equal(normalized.mapsGroundingRequests, 4);
});

test("service tiers are priced", async () => {
  await withCachePath(async () => {
    for (const serviceTier of ["standard", "unspecified", "flex"]) {
      const result = await usage(
        "test-model",
        { input_tokens: 100, output_tokens: 20, service_tier: serviceTier },
        {
          fetchImpl: stubFetch({
            input_cost_per_token: "0.01",
            output_cost_per_token: "0.02",
            input_cost_per_token_flex: "0.005",
            output_cost_per_token_flex: "0.01"
          })
        }
      );
      assert.ok(result !== null);
      assert.equal(result.processingMode, serviceTier === "flex" ? "flex" : "standard");
    }
  });
});

test("reported processing mode overrides requested mode", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      { input_tokens: 100, output_tokens: 0, service_tier: "flex" },
      {
        processingMode: "priority",
        fetchImpl: stubFetch({
          input_cost_per_token: "0.01",
          input_cost_per_token_priority: "0.02",
          input_cost_per_token_flex: "0.005"
        })
      }
    );

    assert.ok(result !== null);
    assert.equal(result.processingMode, "flex");
    assert.equal(result.totalCost.toFixed(), "0.5");
  });
});

test("non-text token details are priced", async () => {
  const cases = [
    {
      input_tokens: 100,
      output_tokens: 20,
      input_tokens_details: { audio_tokens: 10 }
    },
    {
      promptTokenCount: 100,
      responseTokenCount: 20,
      responseTokensDetails: [{ modality: "AUDIO", tokenCount: 10 }]
    }
  ];

  for (const usageValue of cases) {
    await withCachePath(async () => {
      const result = await usage("test-model", usageValue, {
        fetchImpl: stubFetch({
          input_cost_per_token: "0.01",
          output_cost_per_token: "0.02",
          input_cost_per_audio_token: "0.04",
          output_cost_per_audio_token: "0.05"
        })
      });
      assert.ok(result !== null);
      assert.ok(result.audioInputCost.greaterThan(0) || result.audioOutputCost.greaterThan(0));
    });
  }
});

test("additive token totals must remain safe integers", async () => {
  await assert.rejects(
    () =>
      usage(
        "test-model",
        {
          inputTokens: Number.MAX_SAFE_INTEGER,
          outputTokens: 0,
          cacheReadInputTokens: 1
        },
        { fetchImpl: stubFetch({}) }
      ),
    /must be an integer/
  );
});

test("OpenAI Responses usage treats cache writes as a subset", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      {
        input_tokens: 100,
        output_tokens: 20,
        input_tokens_details: { cached_tokens: 30, cache_write_tokens: 20 }
      },
      {
        fetchImpl: stubFetch({
          input_cost_per_token: "0.01",
          output_cost_per_token: "0.03",
          cache_read_input_token_cost: "0.001",
          cache_creation_input_token_cost: "0.02"
        })
      }
    );

    assert.ok(result !== null);
    assert.equal(result.totalCost.toFixed(6), "1.530000");
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
const dimensionsFixture = JSON.parse(
  readFileSync(
    join(fixtureDir, "..", "..", "tests", "fixtures", "pricing_dimensions.json"),
    "utf8"
  )
);

function stubFetch(pricing) {
  return async () => ({
    ok: true,
    status: 200,
    json: async () => ({ "test-model": pricing })
  });
}

for (const testCase of dimensionsFixture.cases) {
  test(`pricing dimensions: ${testCase.name}`, async () => {
    await withCachePath(async () => {
      const raw = testCase.options;
      const result = await cost("test-model", testCase.input_tokens, testCase.output_tokens, {
        fetchImpl: stubFetch(testCase.pricing ?? dimensionsFixture.pricing),
        ...(raw.processing_mode !== undefined ? { processingMode: raw.processing_mode } : {}),
        ...(raw.cached_tokens !== undefined ? { cachedTokens: raw.cached_tokens } : {}),
        ...(raw.cache_creation_tokens !== undefined
          ? { cacheCreationTokens: raw.cache_creation_tokens }
          : {}),
        ...(raw.cache_creation_tokens_1h !== undefined
          ? { cacheCreationTokens1h: raw.cache_creation_tokens_1h }
          : {}),
        ...(raw.cache_creation_audio_tokens !== undefined
          ? { cacheCreationAudioTokens: raw.cache_creation_audio_tokens }
          : {}),
        ...(raw.reasoning_tokens !== undefined ? { reasoningTokens: raw.reasoning_tokens } : {}),
        ...(raw.input_audio_tokens !== undefined
          ? { inputAudioTokens: raw.input_audio_tokens }
          : {}),
        ...(raw.output_audio_tokens !== undefined
          ? { outputAudioTokens: raw.output_audio_tokens }
          : {}),
        ...(raw.input_image_tokens !== undefined
          ? { inputImageTokens: raw.input_image_tokens }
          : {}),
        ...(raw.output_image_tokens !== undefined
          ? { outputImageTokens: raw.output_image_tokens }
          : {}),
        ...(raw.query_count !== undefined ? { queryCount: raw.query_count } : {}),
        ...(raw.query_results !== undefined ? { queryResults: raw.query_results } : {}),
        ...(raw.web_search_requests !== undefined
          ? { webSearchRequests: raw.web_search_requests }
          : {}),
        ...(raw.web_search_context !== undefined
          ? { webSearchContext: raw.web_search_context }
          : {}),
        ...(raw.maps_grounding_requests !== undefined
          ? { mapsGroundingRequests: raw.maps_grounding_requests }
          : {}),
        ...(raw.region !== undefined ? { region: raw.region } : {})
      });
      assert.ok(result !== null);
      assert.equal(result.inputCost.toFixed(), testCase.expected.input_cost);
      assert.equal(result.outputCost.toFixed(), testCase.expected.output_cost);
      assert.equal(result.totalCost.toFixed(), testCase.expected.total_cost);
      if (testCase.expected.query_cost !== undefined) {
        assert.equal(result.queryCost.toFixed(), testCase.expected.query_cost);
      }
      if (testCase.expected.cache_creation_audio_cost !== undefined) {
        assert.equal(
          result.cacheCreationAudioCost.toFixed(),
          testCase.expected.cache_creation_audio_cost
        );
      }
    });
  });
}

for (const [options, message] of [
  [{ cacheCreationTokens: 1, cacheCreationTokens1h: 1 }, /one-hour cache pricing/],
  [{ cacheCreationTokens: 1, cacheCreationAudioTokens: 1, inputAudioTokens: 1 }, /audio cache-write pricing/],
  [{ queryCount: 1 }, /per-query pricing/],
  [{ webSearchRequests: 1 }, /web-search pricing/],
  [{ mapsGroundingRequests: 1 }, /maps-grounding pricing/],
  [{ region: "regional" }, /pricing for region 'regional'/]
]) {
  test(`requested dimension requires a declared rate: ${message.source}`, async () => {
    await withCachePath(async () => {
      await assert.rejects(
        cost("test-model", 1, 0, {
          fetchImpl: stubFetch({ input_cost_per_token: "0.01" }),
          ...options
        }),
        message
      );
    });
  });
}

for (const mode of ["batch", "priority", "flex"]) {
  test(`processing mode requires declared pricing: ${mode}`, async () => {
    await withCachePath(async () => {
      await assert.rejects(
        cost("test-model", 1, 0, {
          fetchImpl: stubFetch({ input_cost_per_token: "0.01" }),
          processingMode: mode
        }),
        new RegExp(`does not declare ${mode} pricing`)
      );
    });
  });
}

test("query result tiers require a supported result count", async () => {
  await withCachePath(async () => {
    const fetchImpl = stubFetch({
      tiered_pricing: [
        { input_cost_per_query: "0.005", max_results_range: [0, 25] }
      ]
    });
    await assert.rejects(
      cost("test-model", 0, 0, { fetchImpl, queryCount: 1 }),
      /queryResults is required/
    );
    await assert.rejects(
      cost("test-model", 0, 0, { fetchImpl, queryCount: 1, queryResults: 26 }),
      /queryResults=26/
    );
  });
});

for (const testCase of [...tierFixture.thresholds, ...tierFixture.request_tiers]) {
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
    assert.equal(result.inputCost.toFixed(), "0.0000005");
    assert.equal(result.outputCost.toFixed(), "0.0000005");
    assert.equal(result.totalCost.toFixed(6), "0.000001");
    assert.ok(result.inputCost.add(result.outputCost).equals(result.totalCost));
  });
});

test("cost arithmetic retains 50 significant digits", async () => {
  await withCachePath(async () => {
    const result = await cost("test-model", Number.MAX_SAFE_INTEGER, 0, {
      fetchImpl: stubFetch({ input_cost_per_token: "0.1234567890123456789" })
    });

    assert.ok(result !== null);
    assert.equal(result.inputCost.toFixed(), "1111999897984715.7653252505775537899");
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

test("Anthropic thinking tokens are reasoning", async () => {
  await withCachePath(async () => {
    const result = await usage(
      "test-model",
      {
        input_tokens: 1_000,
        output_tokens: 5_000,
        output_tokens_details: { thinking_tokens: 4_000 }
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
    assert.equal(result.reasoningCost.toFixed(6), "0.240000");
    assert.equal(result.totalCost.toFixed(6), "0.275000");
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
