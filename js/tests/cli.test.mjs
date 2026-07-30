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

async function withTieredCache(run) {
  const tmpDir = await mkdtemp(path.join(os.tmpdir(), "llmcalc-cli-tiered-"));
  const cachePath = path.join(tmpDir, "pricing_cache.json");

  const payload = {
    fetched_at: Date.now() / 1000,
    data: {
      "gpt-5.5": {
        input_cost_per_token: "0.000005",
        output_cost_per_token: "0.00003",
        input_cost_per_token_above_272k_tokens: "0.00001",
        output_cost_per_token_above_272k_tokens: "0.000045",
        currency: "USD"
      },
      "dashscope/qwen-flash": {
        tiered_pricing: [
          {
            range: [0, 256000],
            input_cost_per_token: "0.00000005",
            output_cost_per_token: "0.0000004"
          },
          {
            range: [256000, 1000000],
            input_cost_per_token: "0.00000025",
            output_cost_per_token: "0.000002"
          }
        ],
        currency: "USD"
      },
      "gemini/gemini-1.5-flash": {
        input_cost_per_token: "0.000000075",
        output_cost_per_token: "0",
        input_cost_per_token_above_128k_tokens: "0.00000015",
        currency: "USD"
      }
    }
  };

  await writeFile(cachePath, JSON.stringify(payload), "utf8");
  await run(cachePath);
}

test("quote reports tier_applied in json output", async () => {
  await withTieredCache(async (cachePath) => {
    const result = runCli(
      ["quote", "--model", "gpt-5.5", "--input", "300000", "--output", "5000", "--json"],
      cachePath
    );

    assert.equal(result.status, 0);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.tier_applied, "above_272k_tokens");
    assert.equal(payload.total_cost, "3.225000");
  });
});

test("quote reports no tier for base rates", async () => {
  await withTieredCache(async (cachePath) => {
    const result = runCli(
      ["quote", "--model", "gpt-5.5", "--input", "100000", "--output", "5000", "--json"],
      cachePath
    );

    assert.equal(result.status, 0);
    assert.equal(JSON.parse(result.stdout).tier_applied, null);
  });
});

test("quote prices a tiered model that previously exited 1", async () => {
  await withTieredCache(async (cachePath) => {
    const result = runCli(
      [
        "quote",
        "--model",
        "dashscope/qwen-flash",
        "--input",
        "300000",
        "--output",
        "1000",
        "--json"
      ],
      cachePath
    );

    assert.equal(result.status, 0);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.tier_applied, "tiered_pricing");
    assert.equal(payload.input_cost, "0.023800");
  });
});

test("model command reports thresholds in json output", async () => {
  await withTieredCache(async (cachePath) => {
    const result = runCli(["model", "--model", "gpt-5.5", "--json"], cachePath);

    assert.equal(result.status, 0);
    const payload = JSON.parse(result.stdout);
    assert.deepEqual(payload.thresholds, ["above_272k_tokens"]);
    assert.equal(payload.tier_count, 0);
  });
});

test("model command emits plain decimal notation", async () => {
  await withTieredCache(async (cachePath) => {
    const result = runCli(["model", "--model", "gemini/gemini-1.5-flash", "--json"], cachePath);

    assert.equal(result.status, 0);
    // Not '7.5e-8'.
    assert.equal(JSON.parse(result.stdout).input_cost_per_token, "0.000000075");
  });
});

test("model command handles tiered model without base rates", async () => {
  await withTieredCache(async (cachePath) => {
    const result = runCli(["model", "--model", "dashscope/qwen-flash", "--json"], cachePath);

    assert.equal(result.status, 0);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.input_cost_per_token, null);
    assert.equal(payload.tier_count, 2);
  });
});
