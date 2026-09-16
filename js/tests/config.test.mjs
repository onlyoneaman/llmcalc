import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_CACHE_TIMEOUT_SECONDS,
  DEFAULT_PRICING_URL,
  getPricingUrl,
  resolveCacheTimeout
} from "../dist/config.js";

test("cache timeout environment value must be a complete positive integer", () => {
  const previous = process.env.LLMCALC_CACHE_TIMEOUT;
  try {
    for (const value of ["12junk", "1_800", "١٨٠٠"]) {
      process.env.LLMCALC_CACHE_TIMEOUT = value;
      assert.equal(resolveCacheTimeout(), DEFAULT_CACHE_TIMEOUT_SECONDS);
    }

    process.env.LLMCALC_CACHE_TIMEOUT = "1800";
    assert.equal(resolveCacheTimeout(), 1800);
  } finally {
    if (previous === undefined) {
      delete process.env.LLMCALC_CACHE_TIMEOUT;
    } else {
      process.env.LLMCALC_CACHE_TIMEOUT = previous;
    }
  }
});

test("explicit cache timeout must be a positive safe integer", () => {
  for (const value of [NaN, Infinity, 0.5, 0, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => resolveCacheTimeout(value), /positive safe integer/);
  }
  assert.equal(resolveCacheTimeout(1), 1);
});

test("empty pricing URL values fall back to the default", () => {
  const previous = process.env.LLMCALC_PRICING_URL;
  try {
    process.env.LLMCALC_PRICING_URL = "";
    assert.equal(getPricingUrl(), DEFAULT_PRICING_URL);
    assert.equal(getPricingUrl(""), DEFAULT_PRICING_URL);
  } finally {
    if (previous === undefined) {
      delete process.env.LLMCALC_PRICING_URL;
    } else {
      process.env.LLMCALC_PRICING_URL = previous;
    }
  }
});
