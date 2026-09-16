import assert from "node:assert/strict";
import test from "node:test";

import { cost } from "../dist/api.js";
import { DEFAULT_PRICING_URL } from "../dist/config.js";
import { getHistoricalPricingPayload } from "../dist/pricing-history.js";
import {
  fetchPricingPayload,
  parsePricingPayload,
  parsePricingPayloadWithDiagnostics
} from "../dist/pricing-client.js";

test("default pricing url points at litellm", () => {
  assert.equal(
    DEFAULT_PRICING_URL,
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
  );
});

test(
  "fixed historical snapshot is fetchable",
  { skip: process.env.SKIP_NETWORK === "1" },
  async () => {
    const payload = await getHistoricalPricingPayload("2024-01-01", fetch);

    assert.ok("gpt-3.5-turbo" in payload);
    assert.ok(Object.keys(payload).length > 100);
  }
);

test(
  "default pricing url is fetchable and parses",
  { skip: process.env.SKIP_NETWORK === "1" },
  async () => {
    const payload = await fetchPricingPayload({});
    const table = parsePricingPayload(payload);
    const report = parsePricingPayloadWithDiagnostics(payload, "USD", true);

    assert.deepEqual(Object.keys(report.models), Object.keys(table));
    assert.ok(report.diagnostics.every((item) => item.severity === "info"));
    assert.ok("gpt-4o" in table);
    assert.ok("gpt-5.5" in table);
    assert.ok(Object.keys(table).length > 2000);
    assert.ok(Object.values(table).every((pricing) => pricing.provider));

    const rangeModels = Object.entries(payload)
      .filter(([, raw]) =>
        typeof raw === "object" &&
        raw !== null &&
        !Array.isArray(raw) &&
        Array.isArray(raw.tiered_pricing) &&
        raw.tiered_pricing.some(
          (tier) => typeof tier === "object" && tier !== null && "range" in tier
        )
      )
      .map(([name]) => name);
    const missingTiers = rangeModels.filter(
      (name) => !(name in table) || table[name].tieredPricing.length === 0
    );
    assert.deepEqual(missingTiers, []);

    assert.ok(Object.values(table).some((pricing) => pricing.thresholds.length > 0));
    assert.ok(Object.values(table).some((pricing) => pricing.cacheReadCostPerToken !== null));
    assert.ok(
      Object.values(table).some(
        (pricing) =>
          pricing.inputCostPerToken !== null && pricing.outputCostPerToken === null
      )
    );

    const rawModels = Object.fromEntries(
      Object.entries(payload).filter(
        ([name, raw]) =>
          name !== "sample_spec" &&
          typeof raw === "object" &&
          raw !== null &&
          !Array.isArray(raw)
      )
    );
    const modeRateFields = [
      "input_cost_per_token",
      "output_cost_per_token",
      "cache_read_input_token_cost",
      "cache_read_input_audio_token_cost",
      "cache_creation_input_token_cost",
      "cache_creation_input_token_cost_above_1hr",
      "output_cost_per_reasoning_token",
      "input_cost_per_audio_token",
      "output_cost_per_audio_token",
      "input_cost_per_image_token",
      "output_cost_per_image_token"
    ];
    for (const [mode, suffix] of Object.entries({
      batch: "_batches",
      priority: "_priority",
      flex: "_flex"
    })) {
      const declared = Object.entries(rawModels)
        .filter(([, raw]) =>
          modeRateFields.some((field) => `${field}${suffix}` in raw)
        )
        .map(([name]) => name);
      assert.ok(declared.length > 0);
      assert.deepEqual(
        declared.filter((name) => !(name in table) || table[name].pricingModes[mode] === undefined),
        []
      );
    }

    for (const [rawField, normalizedField] of Object.entries({
      cache_creation_input_token_cost_above_1hr: "cacheCreation1hCostPerToken",
      cache_creation_input_audio_token_cost: "cacheCreationAudioCostPerToken",
      input_cost_per_audio_token: "inputAudioCostPerToken",
      output_cost_per_audio_token: "outputAudioCostPerToken",
      input_cost_per_image_token: "inputImageCostPerToken",
      output_cost_per_image_token: "outputImageCostPerToken",
      input_cost_per_query: "inputCostPerQuery",
      google_maps_grounding_cost_per_query: "googleMapsGroundingCostPerQuery"
    })) {
      const declared = Object.entries(rawModels)
        .filter(([, raw]) => raw[rawField] !== null && raw[rawField] !== undefined)
        .map(([name]) => name);
      assert.ok(declared.length > 0);
      assert.deepEqual(
        declared.filter((name) => !(name in table) || table[name][normalizedField] === null),
        []
      );
    }

    const oneHourThresholdModels = Object.entries(rawModels)
      .filter(([, raw]) =>
        Object.keys(raw).some((key) =>
          key.startsWith("cache_creation_input_token_cost_above_1hr_above_")
        )
      )
      .map(([name]) => name);
    assert.ok(oneHourThresholdModels.length > 0);
    assert.deepEqual(
      oneHourThresholdModels.filter(
        (name) =>
          !(name in table) ||
          !table[name].thresholds.some(
            (threshold) => threshold.rates.cache_creation_1h !== null
          )
      ),
      []
    );

    const searchModels = Object.entries(rawModels)
      .filter(([, raw]) =>
        typeof raw.search_context_cost_per_query === "object" &&
        raw.search_context_cost_per_query !== null &&
        !Array.isArray(raw.search_context_cost_per_query)
      )
      .map(([name]) => name);
    assert.ok(searchModels.length > 0);
    assert.deepEqual(
      searchModels.filter(
        (name) =>
          !(name in table) || Object.keys(table[name].searchContextCostPerQuery).length === 0
      ),
      []
    );

    for (const region of ["us", "eu"]) {
      const field = `regional_processing_uplift_multiplier_${region}`;
      const declared = Object.entries(rawModels)
        .filter(([, raw]) => raw[field] !== null && raw[field] !== undefined)
        .map(([name]) => name);
      assert.ok(declared.length > 0);
      assert.deepEqual(
        declared.filter(
          (name) => !(name in table) || table[name].regionalProcessingUplift[region] === undefined
        ),
        []
      );
    }

    const queryTierModels = Object.entries(rawModels)
      .filter(([, raw]) =>
        Array.isArray(raw.tiered_pricing) &&
        raw.tiered_pricing.some(
          (tier) => typeof tier === "object" && tier !== null && "max_results_range" in tier
        )
      )
      .map(([name]) => name);
    assert.ok(queryTierModels.length > 0);
    assert.deepEqual(
      queryTierModels.filter(
        (name) => !(name in table) || table[name].queryPricing.length === 0
      ),
      []
    );

    const regionalModels = Object.entries(rawModels)
      .filter(([, raw]) => raw.regional_endpoint_uplift_multiplier != null)
      .map(([name]) => name);
    assert.ok(regionalModels.length > 0);
    assert.deepEqual(
      regionalModels.filter(
        (name) => !(name in table) || table[name].regionalProcessingUplift.regional === undefined
      ),
      []
    );

    const providerUsModels = Object.entries(rawModels)
      .filter(([, raw]) =>
        typeof raw.provider_specific_entry === "object" &&
        raw.provider_specific_entry !== null &&
        raw.provider_specific_entry.us != null
      )
      .map(([name]) => name);
    assert.ok(providerUsModels.length > 0);
    assert.deepEqual(
      providerUsModels.filter(
        (name) => !(name in table) || table[name].regionalProcessingUplift.us === undefined
      ),
      []
    );

    const providerFastModels = Object.entries(rawModels)
      .filter(([, raw]) =>
        typeof raw.provider_specific_entry === "object" &&
        raw.provider_specific_entry !== null &&
        raw.provider_specific_entry.fast != null
      )
      .map(([name]) => name);
    assert.ok(providerFastModels.length > 0);
    assert.deepEqual(
      providerFastModels.filter(
        (name) => !(name in table) || table[name].pricingModes.priority === undefined
      ),
      []
    );

    const batchLong = await cost(
      "claude-sonnet-4-5-20250929-v1:0",
      200_001,
      1_000,
      { processingMode: "batch" }
    );
    assert.equal(batchLong?.totalCost.toFixed(), "0.611253");

    const queryTier = await cost("exa_ai/search", 0, 0, {
      queryCount: 2,
      queryResults: 26
    });
    assert.equal(queryTier?.queryCost.toFixed(), "0.05");

    const audioCache = await cost("gpt-realtime", 10, 0, {
      cacheCreationTokens: 10,
      cacheCreationAudioTokens: 10,
      inputAudioTokens: 10
    });
    assert.equal(audioCache?.cacheCreationAudioCost.toFixed(), "0.000004");
  }
);
