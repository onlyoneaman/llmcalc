import assert from "node:assert/strict";
import test from "node:test";

import { normalizeModelName, resolveModelKey } from "../dist/normalize.js";

test("normalizeModelName strips prefixes", () => {
  assert.equal(normalizeModelName(" openai:gpt-5.1 "), "gpt-5.1");
  assert.equal(normalizeModelName("openai/gpt-5.1"), "gpt-5.1");
});

test("normalizeModelName resolves aliases", () => {
  assert.equal(normalizeModelName("gpt-5.1-latest"), "gpt-5.1");
});

test("resolveModelKey is case-insensitive and prefix-aware", () => {
  const keys = ["GPT-5.1", "claude-3-5-sonnet"];
  assert.equal(resolveModelKey("openai:gpt-5.1", keys), "GPT-5.1");
});

test("resolveModelKey returns null for unknown model", () => {
  assert.equal(resolveModelKey("unknown-model", ["gpt-5.1"]), null);
});
