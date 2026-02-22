import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { getPricingTable, parsePricingPayload } from "../dist/pricing-client.js";
import { PricingFetchError, PricingSchemaError } from "../dist/errors.js";

async function withCachePath(run) {
  const tmpDir = await mkdtemp(path.join(os.tmpdir(), "llmcalc-pricing-"));
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

test("parsePricingPayload supports direct table", () => {
  const table = parsePricingPayload({
    "gpt-5.1": {
      input_cost_per_token: "0.000001",
      output_cost_per_token: "0.000002"
    }
  });

  assert.equal(table["gpt-5.1"].inputCostPerToken.toString(), "0.000001");
});

test("parsePricingPayload supports wrapped table", () => {
  const table = parsePricingPayload({
    data: {
      "gpt-5.1": {
        input_cost_per_million_tokens: "2",
        output_cost_per_million_tokens: "4"
      }
    }
  });

  assert.equal(table["gpt-5.1"].outputCostPerToken.toString(), "0.000004");
});

test("parsePricingPayload throws for invalid payload", () => {
  assert.throws(
    () => parsePricingPayload({ meta: { foo: "bar" } }),
    PricingSchemaError
  );
});

test("getPricingTable uses cache when valid", async () => {
  await withCachePath(async () => {
    const payload = {
      "gpt-5.1": {
        input_cost_per_token: "0.000001",
        output_cost_per_token: "0.000002"
      }
    };

    await getPricingTable({
      cacheTimeout: 3600,
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        json: async () => payload
      })
    });

    const table = await getPricingTable({
      cacheTimeout: 3600,
      fetchImpl: async () => {
        throw new Error("fetch should not run when cache is valid");
      }
    });

    assert.ok(table["gpt-5.1"]);
  });
});

test("getPricingTable fetches and saves when cache is missing", async () => {
  await withCachePath(async () => {
    const table = await getPricingTable({
      cacheTimeout: 3600,
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          "gpt-5.1": {
            input_cost_per_token: "0.000001",
            output_cost_per_token: "0.000002"
          }
        })
      })
    });

    assert.ok(table["gpt-5.1"]);
  });
});

test("getPricingTable throws when fetch fails and cache is empty", async () => {
  await withCachePath(async () => {
    await assert.rejects(
      () =>
        getPricingTable({
          cacheTimeout: 3600,
          fetchImpl: async () => {
            throw new Error("no network");
          }
        }),
      PricingFetchError
    );
  });
});
