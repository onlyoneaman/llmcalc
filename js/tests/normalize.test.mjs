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

test("bedrock version suffix is not stripped", () => {
  const model = "anthropic.claude-3-5-sonnet-20240620-v1:0";
  assert.equal(normalizeModelName(model), model);
});

test("fine tune prefix is not stripped", () => {
  assert.equal(normalizeModelName("ft:gpt-3.5-turbo"), "ft:gpt-3.5-turbo");
});

test("bare version number resolves to nothing", () => {
  const keys = [
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "anthropic.claude-sonnet-4-20250514-v1:0"
  ];
  assert.equal(resolveModelKey("0", keys), null);
});

test("bedrock ids still resolve exactly", () => {
  const keys = ["anthropic.claude-sonnet-4-20250514-v1:0"];
  assert.equal(
    resolveModelKey("anthropic.claude-sonnet-4-20250514-v1:0", keys),
    "anthropic.claude-sonnet-4-20250514-v1:0"
  );
});

test("multi separator keeps remainder, matching python", () => {
  assert.equal(normalizeModelName("openai/foo/bar"), "foo/bar");
});

test("version suffixes one and two are preserved", () => {
  assert.equal(normalizeModelName("ai21.jamba-instruct-v1:1"), "ai21.jamba-instruct-v1:1");
  assert.equal(normalizeModelName("cohere.command-text-v14:2"), "cohere.command-text-v14:2");
});
