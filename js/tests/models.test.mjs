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

test("toModelPricing supports per million fields", () => {
  const model = toModelPricing("gpt-5.1", {
    input_cost_per_million_tokens: "2",
    output_cost_per_million_tokens: "4"
  });

  assert.equal(model.inputCostPerToken.toString(), "0.000002");
  assert.equal(model.outputCostPerToken.toString(), "0.000004");
});
