import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  fetchPricingPayload,
  getPricingTable,
  parsePricingPayload
} from "../dist/pricing-client.js";
import { PricingFetchError, PricingSchemaError } from "../dist/errors.js";

async function withCachePath(run) {
  const tmpDir = await mkdtemp(path.join(os.tmpdir(), "llmcalc-pricing-"));
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

test("parsePricingPayload supports direct table", () => {
  const table = parsePricingPayload({
    "gpt-5.1": {
      input_cost_per_token: "0.000001",
      output_cost_per_token: "0.000002"
    }
  });

  assert.equal(table["gpt-5.1"].inputCostPerToken.toString(), "0.000001");
});

test("parsePricingPayload uses its explicit or USD fallback currency", () => {
  const previous = process.env.LLMCALC_CURRENCY;
  process.env.LLMCALC_CURRENCY = "INR";

  try {
    const payload = { model: { input_cost_per_token: "0.01" } };
    assert.equal(parsePricingPayload(payload).model.currency, "USD");
    assert.equal(parsePricingPayload(payload, "EUR").model.currency, "EUR");
  } finally {
    if (previous === undefined) {
      delete process.env.LLMCALC_CURRENCY;
    } else {
      process.env.LLMCALC_CURRENCY = previous;
    }
  }
});

test("payload currency takes precedence over the fallback", () => {
  const table = parsePricingPayload(
    { model: { input_cost_per_token: "0.01", currency: "JPY" } },
    "EUR"
  );

  assert.equal(table.model.currency, "JPY");
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

test("getPricingTable applies the currency environment only to custom sources", async () => {
  await withCachePath(async () => {
    const previous = process.env.LLMCALC_CURRENCY;
    process.env.LLMCALC_CURRENCY = "INR";
    const fetchImpl = async () => ({
      ok: true,
      status: 200,
      json: async () => ({ model: { input_cost_per_token: "0.01" } })
    });

    try {
      const defaultTable = await getPricingTable({ fetchImpl });
      const customTable = await getPricingTable({
        pricingUrl: "https://example.com/prices.json",
        fetchImpl
      });

      assert.equal(defaultTable.model.currency, "USD");
      assert.equal(customTable.model.currency, "INR");
    } finally {
      if (previous === undefined) {
        delete process.env.LLMCALC_CURRENCY;
      } else {
        process.env.LLMCALC_CURRENCY = previous;
      }
    }
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

test("fetch errors do not expose pricing URL secrets", async () => {
  const secret = "https://example.com/prices.json?token=secret";
  await assert.rejects(
    () =>
      fetchPricingPayload({
        pricingUrl: secret,
        fetchImpl: async (source) => {
          throw new Error(source);
        }
      }),
    (error) => {
      assert.ok(error instanceof PricingFetchError);
      assert.equal(error.message, "failed to fetch pricing data");
      assert.doesNotMatch(error.message, /secret/);
      return true;
    }
  );
});

test("getPricingTable does not reuse cache from another source", async () => {
  await withCachePath(async () => {
    await getPricingTable({
      pricingUrl: "https://example.com/a.json",
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        json: async () => ({ a: { input_cost_per_token: 1, output_cost_per_token: 2 } })
      })
    });

    const table = await getPricingTable({
      pricingUrl: "https://example.com/b.json",
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        json: async () => ({ b: { input_cost_per_token: 3, output_cost_per_token: 4 } })
      })
    });

    assert.ok(table.b);
    assert.equal(table.a, undefined);
  });
});

test("getPricingTable rejects refresh failure instead of using expired cache", async () => {
  await withCachePath(async (cachePath) => {
    const source = "https://example.com/prices.json";
    await writeFile(
      cachePath,
      JSON.stringify({
        fetched_at: Date.now() / 1000 - 10,
        source_hash: createHash("sha256").update(source).digest("hex"),
        data: { stale: { input_cost_per_token: 1, output_cost_per_token: 2 } }
      }),
      "utf8"
    );

    await assert.rejects(
      () =>
        getPricingTable({
          cacheTimeout: 1,
          pricingUrl: source,
          fetchImpl: async () => {
            throw new Error("no network");
          }
        }),
      PricingFetchError
    );
  });
});

test("getPricingTable returns parsed pricing when cache persistence fails", async () => {
  await withCachePath(async (cachePath) => {
    await mkdir(cachePath);
    const table = await getPricingTable({
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        json: async () => ({ model: { input_cost_per_token: 1, output_cost_per_token: 2 } })
      })
    });

    assert.ok(table.model);
  });
});

test("fetchPricingPayload aborts requests at the configured timeout", async () => {
  await assert.rejects(
    () =>
      fetchPricingPayload({
        pricingUrl: "https://example.com/prices.json",
        timeoutMs: 5,
        fetchImpl: async (_input, init) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), {
              once: true
            });
          })
      }),
    PricingFetchError
  );
});
