import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { Decimal } from "decimal.js";

import {
  parseBaseRates,
  parseThresholds,
  parseTiers,
  rateFor,
  resolveRates,
  resolveTierRates,
  selectTierRates
} from "../dist/pricing-tiers.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(
  readFileSync(join(here, "..", "..", "tests", "fixtures", "tiered_cases.json"), "utf8")
);

function money(value) {
  return value.toFixed(6, Decimal.ROUND_HALF_UP);
}

for (const testCase of fixture.thresholds) {
  test(`threshold: ${testCase.name}`, () => {
    const pricing = testCase.pricing;
    const thresholds = parseThresholds(pricing);

    const [rates, tier] = resolveRates(
      parseBaseRates(pricing),
      thresholds,
      testCase.input_tokens,
      pricing.litellm_provider ?? null
    );

    assert.equal(tier, testCase.expected.tier_applied);
    const inputRate = rateFor(rates, "input");
    const outputRate = rateFor(rates, "output");
    assert.ok(inputRate !== null && outputRate !== null);
    assert.equal(
      money(new Decimal(testCase.input_tokens).mul(inputRate)),
      testCase.expected.input_cost
    );
    assert.equal(
      money(new Decimal(testCase.output_tokens).mul(outputRate)),
      testCase.expected.output_cost
    );
  });
}

for (const testCase of fixture.request_tiers) {
  test(`request tier: ${testCase.name}`, () => {
    const tiers = parseTiers(testCase.pricing.tiered_pricing);
    assert.ok(tiers.length > 0);
    const selected = selectTierRates(tiers, testCase.input_tokens);
    if (testCase.input_tokens === 0) {
      assert.equal(selected, null);
      return;
    }
    assert.ok(selected !== null);
    const rates = resolveTierRates(parseBaseRates(testCase.pricing), selected);
    const inputRate = rateFor(rates, "input");
    const outputRate = rateFor(rates, "output");
    assert.ok(inputRate !== null && outputRate !== null);

    assert.equal(
      money(new Decimal(testCase.input_tokens).mul(inputRate)),
      testCase.expected.input_cost
    );
    assert.equal(
      money(new Decimal(testCase.output_tokens).mul(outputRate)),
      testCase.expected.output_cost
    );
  });
}

test("thresholds are sorted descending", () => {
  const thresholds = parseThresholds({
    input_cost_per_token_above_128k_tokens: "0.000002",
    input_cost_per_token_above_272k_tokens: "0.000004"
  });
  assert.deepEqual(
    thresholds.map((t) => t.threshold),
    [272000, 128000]
  );
});

test("query priced tiers are not token tiers", () => {
  assert.deepEqual(
    parseTiers([
      { input_cost_per_query: 0.005, max_results_range: [0, 25] },
      { input_cost_per_query: 0.025, max_results_range: [26, 100] }
    ]),
    []
  );
});

test("tiers missing cost key remain missing", () => {
  const tiers = parseTiers([{ range: [0, 100], input_cost_per_token: "0.000001" }]);
  const rates = selectTierRates(tiers, 50);
  assert.ok(rates !== null);
  assert.equal(rateFor(rates, "output"), null);
});

test("output-only tier schedule is rejected", () => {
  assert.deepEqual(
    parseTiers([{ range: [0, 100], output_cost_per_token: "0.000001" }]),
    []
  );
});

test("parseTiers tolerates garbage", () => {
  assert.deepEqual(parseTiers(null), []);
  assert.deepEqual(parseTiers("nonsense"), []);
  assert.deepEqual(parseTiers([{ range: [0] }]), []);
  assert.deepEqual(parseTiers([{ range: ["a", "b"], input_cost_per_token: "1" }]), []);
});

test("parseThresholds ignores negative and unparseable rates", () => {
  assert.deepEqual(
    parseThresholds({
      input_cost_per_token_above_128k_tokens: "-0.5",
      output_cost_per_token_above_272k_tokens: "not-a-number"
    }),
    []
  );
});

test("no tier rates without tiers", () => {
  assert.equal(selectTierRates([], 1000), null);
});

test("positive input outside every range uses the last tier", () => {
  const tiers = parseTiers([
    { range: [0, 100], input_cost_per_token: "0.000001" },
    { range: [200, 300], input_cost_per_token: "0.000003" }
  ]);
  assert.equal(selectTierRates(tiers, 0), null);
  assert.equal(selectTierRates(tiers, 150)?.input?.toFixed(), "0.000003");
  assert.equal(selectTierRates(tiers, 400)?.input?.toFixed(), "0.000003");
});

test("range-bearing tier parsing rejects the whole table atomically", () => {
  const valid = { range: [0, 100], input_cost_per_token: "0.000001" };
  assert.deepEqual(parseTiers([valid, { range: [100] }]), []);
  assert.deepEqual(parseTiers([valid, null]), []);
  assert.deepEqual(parseTiers([valid, { input_cost_per_token: "0.000002" }]), []);
  assert.deepEqual(parseTiers([valid, { range: [100, 200], input_cost_per_token: "bad" }]), []);
  assert.deepEqual(
    parseTiers([
      valid,
      { range: [50, 150], input_cost_per_token: "0.000002" }
    ]),
    []
  );
});

test("threshold key preserves the k suffix form", () => {
  const kilo = parseThresholds({ input_cost_per_token_above_272k_tokens: "0.00001" });
  assert.equal(kilo[0].key, "above_272k_tokens");
  assert.equal(kilo[0].threshold, 272000);

  const literal = parseThresholds({ input_cost_per_token_above_128_tokens: "0.00001" });
  assert.equal(literal[0].key, "above_128_tokens");
  assert.equal(literal[0].threshold, 128);
});
