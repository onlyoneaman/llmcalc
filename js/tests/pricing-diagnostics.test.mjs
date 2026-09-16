import assert from "node:assert/strict";
import { readFile, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { PricingSchemaError } from "../dist/errors.js";
import {
  getPricingReport,
  parsePricingPayload,
  parsePricingPayloadWithDiagnostics
} from "../dist/pricing-client.js";
import { pricingReport, pricingReportAsync } from "../dist/index.js";

const fixture = JSON.parse(
  await readFile(
    new URL("../../tests/fixtures/pricing_diagnostics_cases.json", import.meta.url),
    "utf8"
  )
);

async function withCachePath(run) {
  const tmpDir = await mkdtemp(path.join(os.tmpdir(), "llmcalc-diagnostics-"));
  const previous = process.env.LLMCALC_CACHE_PATH;
  process.env.LLMCALC_CACHE_PATH = path.join(tmpDir, "pricing_cache.json");
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

test("pricing diagnostics match the shared contract", () => {
  const result = parsePricingPayloadWithDiagnostics(fixture.payload);

  assert.deepEqual(Object.keys(result.models), fixture.parsed_models);
  assert.deepEqual(result.diagnostics, fixture.diagnostics);
});

test("parsePricingPayload preserves its table-only return value", () => {
  const table = parsePricingPayload(fixture.payload);

  assert.deepEqual(Object.keys(table), fixture.parsed_models);
  assert.equal("diagnostics" in table, false);
});

test("zero valid models carries structured diagnostics on the schema error", () => {
  assert.throws(
    () => parsePricingPayloadWithDiagnostics({ broken: "not-an-object" }),
    (error) => {
      assert.ok(error instanceof PricingSchemaError);
      assert.equal(error.message, "no valid model pricing entries found");
      assert.deepEqual(error.diagnostics, [
        {
          model: "broken",
          severity: "error",
          code: "entry_not_object",
          action: "skipped_entry",
          path: [],
          message: "pricing entry must be an object"
        }
      ]);
      return true;
    }
  );
});

test("non-scalar rates are diagnostics instead of escaping parser errors", () => {
  assert.throws(
    () =>
      parsePricingPayloadWithDiagnostics({
        valid: { input_cost_per_token: "0.01" },
        broken: { input_cost_per_token: [1] }
      }, "USD", true),
    (error) => {
      assert.ok(error instanceof PricingSchemaError);
      assert.equal(error.diagnostics[0]?.code, "invalid_rate");
      assert.deepEqual(error.diagnostics[0]?.path, ["input_cost_per_token"]);
      return true;
    }
  );
});

test("strict diagnostics reject malformed entries but permit informational skips", () => {
  const infoOnly = parsePricingPayloadWithDiagnostics(
    {
      valid: { input_cost_per_token: "0.01" },
      image: { output_cost_per_image: "0.04" }
    },
    "USD",
    true
  );
  assert.deepEqual(Object.keys(infoOnly.models), ["valid"]);

  assert.throws(
    () => parsePricingPayloadWithDiagnostics(fixture.payload, "USD", true),
    (error) => {
      assert.ok(error instanceof PricingSchemaError);
      assert.equal(error.message, "pricing payload contains invalid entries");
      assert.deepEqual(error.diagnostics, fixture.diagnostics);
      return true;
    }
  );
});

test("getPricingReport returns diagnostics without changing cache behavior", async () => {
  await withCachePath(async () => {
    let fetches = 0;
    const fetchImpl = async () => {
      fetches += 1;
      return {
        ok: true,
        status: 200,
        json: async () => fixture.payload
      };
    };

    const fetched = await getPricingReport({ fetchImpl });
    const cached = await getPricingReport({
      fetchImpl: async () => {
        throw new Error("cache should be reused");
      }
    });

    assert.equal(fetches, 1);
    assert.deepEqual(fetched.diagnostics, fixture.diagnostics);
    assert.deepEqual(cached.diagnostics, fixture.diagnostics);
  });
});

test("pricing reports are exported from the package entry point", () => {
  assert.equal(typeof pricingReport, "function");
  assert.equal(pricingReportAsync, pricingReport);
});
