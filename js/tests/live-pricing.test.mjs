import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_PRICING_URL } from "../dist/config.js";
import { fetchPricingPayload, parsePricingPayload } from "../dist/pricing-client.js";

test("default pricing url points at litellm", () => {
  assert.equal(
    DEFAULT_PRICING_URL,
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
  );
});

test(
  "default pricing url is fetchable and parses",
  { skip: process.env.SKIP_NETWORK === "1" },
  async () => {
    const payload = await fetchPricingPayload({});
    const table = parsePricingPayload(payload);

    assert.ok("gpt-4o" in table);
    assert.ok("gpt-5.5" in table);
    assert.ok(Object.keys(table).length > 2000);
  }
);
