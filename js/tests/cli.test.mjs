import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const CLI_PATH = path.join(process.cwd(), "dist", "cli.js");

async function withCache(run) {
  const tmpDir = await mkdtemp(path.join(os.tmpdir(), "llmcalc-cli-"));
  const cachePath = path.join(tmpDir, "pricing_cache.json");

  const payload = {
    fetched_at: Date.now() / 1000,
    data: {
      "gpt-5.1": {
        input_cost_per_token: "0.000001",
        output_cost_per_token: "0.000002",
        currency: "USD"
      }
    }
  };

  await writeFile(cachePath, JSON.stringify(payload), "utf8");
  await run(cachePath);
}

function runCli(args, cachePath) {
  return spawnSync(process.execPath, [CLI_PATH, ...args], {
    encoding: "utf8",
    env: {
      ...process.env,
      LLMCALC_CACHE_PATH: cachePath
    }
  });
}

test("version flags work", async () => {
  await withCache(async (cachePath) => {
    const longFlag = runCli(["--version"], cachePath);
    const shortFlag = runCli(["-v"], cachePath);

    assert.equal(longFlag.status, 0);
    assert.equal(shortFlag.status, 0);
    assert.match(longFlag.stdout, /llmcalc\s+\d+\.\d+\.\d+/);
    assert.match(shortFlag.stdout, /llmcalc\s+\d+\.\d+\.\d+/);
  });
});

test("quote command prints totals", async () => {
  await withCache(async (cachePath) => {
    const result = runCli(["quote", "--model", "gpt-5.1", "--input", "1000", "--output", "500"], cachePath);
    assert.equal(result.status, 0);
    assert.match(result.stdout, /total_cost:\s+0\.002000/);
  });
});

test("model command supports json", async () => {
  await withCache(async (cachePath) => {
    const result = runCli(["model", "--model", "gpt-5.1", "--json"], cachePath);
    assert.equal(result.status, 0);

    const parsed = JSON.parse(result.stdout);
    assert.equal(parsed.model, "gpt-5.1");
    assert.equal(parsed.currency, "USD");
  });
});

test("missing model exits with code 1", async () => {
  await withCache(async (cachePath) => {
    const result = runCli(["quote", "--model", "unknown", "--input", "1", "--output", "1"], cachePath);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Model not found: unknown/);
  });
});
