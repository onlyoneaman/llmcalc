import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { clearCache } from "../dist/cache.js";
import {
  getHistoricalPricingPayload,
  validateSnapshotAt
} from "../dist/pricing-history.js";

const fixture = JSON.parse(
  readFileSync(
    path.join(
      path.dirname(fileURLToPath(import.meta.url)),
      "..",
      "..",
      "tests",
      "fixtures",
      "history_snapshots.json"
    ),
    "utf8"
  )
);

async function withCachePath(run) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "llmcalc-history-"));
  const previous = process.env.LLMCALC_CACHE_PATH;
  process.env.LLMCALC_CACHE_PATH = path.join(directory, "pricing.json");
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

test("snapshot dates are validated", () => {
  assert.equal(validateSnapshotAt("2024-01-01"), "2024-01-01");
  assert.throws(() => validateSnapshotAt("01-01-2024"), /YYYY-MM-DD/);
  assert.throws(() => validateSnapshotAt("2023-09-05"), /starts at/);
  const today = new Date().toISOString().slice(0, 10);
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  assert.throws(() => validateSnapshotAt(today), /completed UTC date/);
  assert.throws(() => validateSnapshotAt(tomorrow), /completed UTC date/);
});

test("historical resolution rejects invalid commit responses", async () => {
  for (const [payload, message] of [
    [[], /no LiteLLM pricing snapshot/],
    [
      [{ sha: "invalid", commit: { committer: { date: "2024-01-01T00:00:00Z" } } }],
      /invalid pricing snapshot/
    ],
    [
      [{ sha: "a".repeat(40), commit: { committer: { date: "2024-01-02T00:00:00Z" } } }],
      /after the requested date/
    ]
  ]) {
    await withCachePath(async () => {
      await assert.rejects(
        getHistoricalPricingPayload("2024-01-01", async () => ({
          ok: true,
          status: 200,
          json: async () => payload
        })),
        message
      );
    });
  }
});

test("historical resolution reports HTTP failure", async () => {
  await withCachePath(async () => {
    await assert.rejects(
      getHistoricalPricingPayload("2024-01-01", async () => ({
        ok: false,
        status: 403,
        json: async () => ({})
      })),
      /failed to resolve/
    );
  });
});

test("historical payload is cached by date and sha", async () => {
  await withCachePath(async () => {
    const snapshot = fixture.snapshots[0];
    const calls = { commits: 0, snapshot: 0 };
    const fetchImpl = async (url) => {
      if (url.startsWith("https://api.github.com/")) {
        calls.commits += 1;
        return {
          ok: true,
          status: 200,
          json: async () => [
            {
              sha: snapshot.sha,
              commit: { committer: { date: snapshot.committed_at } }
            }
          ]
        };
      }
      calls.snapshot += 1;
      return { ok: true, status: 200, json: async () => snapshot.payload };
    };

    const first = await getHistoricalPricingPayload(snapshot.snapshot_at, fetchImpl);
    const second = await getHistoricalPricingPayload(snapshot.snapshot_at, fetchImpl);
    assert.deepEqual(first, snapshot.payload);
    assert.deepEqual(second, snapshot.payload);
    assert.deepEqual(calls, { commits: 1, snapshot: 1 });
    await clearCache();
  });
});
