import assert from "node:assert/strict";
import test from "node:test";

import { toModelPricing } from "../dist/models.js";

test("toModelPricing supports alias fields", () => {
  const model = toModelPricing("gpt-5.1", {
    prompt_cost_per_token: "0.000001",
    completion_cost_per_token: "0.000002",
    provider: "openai"
  });

  assert.equal(model.inputCostPerToken.toString(), "0.000001");
  assert.equal(model.outputCostPerToken.toString(), "0.000002");
  assert.equal(model.provider, "openai");
});

test("empty LiteLLM provider falls back to provider", () => {
  const model = toModelPricing("model", {
    input_cost_per_token: "0.000001",
    litellm_provider: "",
    provider: "openai"
  });

  assert.equal(model.provider, "openai");
});

test("toModelPricing supports per million fields", () => {
  const model = toModelPricing("gpt-5.1", {
    input_cost_per_million_tokens: "2",
    output_cost_per_million_tokens: "4"
  });

  assert.equal(model.inputCostPerToken.toString(), "0.000002");
  assert.equal(model.outputCostPerToken.toString(), "0.000004");
});

test("tiered model without base rates is priceable", () => {
  const pricing = toModelPricing("dashscope/qwen3-max", {
    tiered_pricing: [
      { range: [0, 256000], input_cost_per_token: 5e-8, output_cost_per_token: 4e-7 }
    ],
    litellm_provider: "dashscope"
  });

  assert.equal(pricing.inputCostPerToken, null);
  assert.equal(pricing.outputCostPerToken, null);
  assert.equal(pricing.provider, "dashscope");
  assert.equal(pricing.tieredPricing.length, 1);
});

test("threshold fields are parsed and sorted", () => {
  const pricing = toModelPricing("gpt-5.5", {
    input_cost_per_token: 5e-6,
    output_cost_per_token: 3e-5,
    input_cost_per_token_above_272k_tokens: 1e-5,
    output_cost_per_token_above_272k_tokens: 4.5e-5
  });

  assert.deepEqual(
    pricing.thresholds.map((t) => t.key),
    ["above_272k_tokens"]
  );
});

test("model with no pricing at all is rejected", () => {
  assert.throws(() => toModelPricing("x", {}), /Missing supported pricing fields/);
});

test("model with only mode pricing is priceable", () => {
  const pricing = toModelPricing("batch-only", {
    input_cost_per_token_batches: "0.01"
  });

  assert.equal(pricing.inputCostPerToken, null);
  assert.equal(pricing.pricingModes.batch.rates.input.toFixed(), "0.01");
});

test("model with only cache pricing is priceable", () => {
  const pricing = toModelPricing("cache-only", {
    cache_read_input_token_cost: "0.001"
  });

  assert.equal(pricing.inputCostPerToken, null);
  assert.equal(pricing.cacheReadCostPerToken.toFixed(), "0.001");
});

test("non-finite string rates are rejected", () => {
  for (const value of ["NaN", "Infinity", "-Infinity"]) {
    assert.throws(() =>
      toModelPricing("x", {
        input_cost_per_token: value,
        output_cost_per_token: "0.000001"
      })
    );
  }
});

test("malformed declared rates reject the model atomically", () => {
  for (const value of [true, [], {}, ""]) {
    assert.throws(() =>
      toModelPricing("x", {
        input_cost_per_token: value,
        output_cost_per_token: "0.000001"
      })
    );
  }

  assert.throws(() =>
    toModelPricing("x", {
      input_cost_per_token: "0.000001",
      output_cost_per_token: "0.000002",
      prompt_cost_per_token: true
    })
  );
});

test("input-only token model is priceable", () => {
  const pricing = toModelPricing("mistral/mistral-embed", {
    input_cost_per_token: "0.0000001",
    litellm_provider: "mistral"
  });

  assert.equal(pricing.inputCostPerToken.toFixed(), "0.0000001");
  assert.equal(pricing.outputCostPerToken, null);
});

test("query priced tiers make a model priceable", () => {
  const pricing = toModelPricing("exa_ai/search", {
    tiered_pricing: [{ input_cost_per_query: 0.005, max_results_range: [0, 25] }]
  });

  assert.equal(pricing.queryPricing[0].rangeEnd, 25);
  assert.equal(pricing.queryPricing[0].rate.toFixed(), "0.005");
});

test("corrupt thresholds fall back to base rates without throwing", () => {
  const pricing = toModelPricing("gpt-5.5", {
    input_cost_per_token: 5e-6,
    output_cost_per_token: 3e-5,
    input_cost_per_token_above_abc_tokens: "not-a-number"
  });

  assert.deepEqual(pricing.thresholds, []);
  assert.equal(pricing.inputCostPerToken.toString(), "0.000005");
});

test("base rate only model is unchanged", () => {
  const pricing = toModelPricing("gpt-4o", {
    input_cost_per_token: 2.5e-6,
    output_cost_per_token: 1e-5
  });

  assert.equal(pricing.inputCostPerToken.toString(), "0.0000025");
  assert.deepEqual(pricing.thresholds, []);
  assert.deepEqual(pricing.tieredPricing, []);
});
