#!/usr/bin/env node

import path from "node:path";
import { fileURLToPath } from "node:url";

import { cost, model, clearCache } from "./api.js";
import { getPackageVersion } from "./config.js";

interface Printer {
  out: (message: string) => void;
  err: (message: string) => void;
}

function printHelp(print: (message: string) => void): void {
  print(`llmcalc ${getPackageVersion()}`);
  print("Usage:");
  print("  llmcalc quote --model <id> --input <tokens> --output <tokens> [--cache-timeout <sec>] [--json]");
  print("  llmcalc model --model <id> [--cache-timeout <sec>] [--json]");
  print("  llmcalc cache clear");
  print("  llmcalc --version | -v");
}

function parseArgs(args: string[]): { flags: Set<string>; values: Map<string, string> } {
  const flags = new Set<string>();
  const values = new Map<string, string>();

  for (let i = 0; i < args.length; i += 1) {
    const token = args[i] ?? "";
    if (!token.startsWith("--")) {
      continue;
    }

    if (token === "--json") {
      flags.add(token);
      continue;
    }

    const next = args[i + 1];
    if (next === undefined || next.startsWith("--")) {
      throw new Error(`Missing value for ${token}`);
    }

    values.set(token, next);
    i += 1;
  }

  return { flags, values };
}

function parseIntOption(raw: string | undefined, name: string): number {
  if (raw === undefined) {
    throw new Error(`Missing required option ${name}`);
  }

  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new Error(`${name} must be a non-negative integer`);
  }

  return parsed;
}

function parseCacheTimeout(raw: string | undefined): number | undefined {
  if (raw === undefined) {
    return undefined;
  }

  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error("--cache-timeout must be a positive integer");
  }

  return parsed;
}

function emit(data: Record<string, string>, asJson: boolean, out: (message: string) => void): void {
  if (asJson) {
    out(JSON.stringify(data));
    return;
  }

  for (const [key, value] of Object.entries(data)) {
    out(`${key}: ${value}`);
  }
}

export async function main(argv: string[], printer: Printer = {
  out: (message: string) => process.stdout.write(`${message}\n`),
  err: (message: string) => process.stderr.write(`${message}\n`)
}): Promise<number> {
  if (argv.length === 0 || argv[0] === "--help" || argv[0] === "-h") {
    printHelp(printer.out);
    return 0;
  }

  if (argv.includes("--version") || argv.includes("-v")) {
    printer.out(`llmcalc ${getPackageVersion()}`);
    return 0;
  }

  const command = argv[0];

  if (command === "cache" && argv[1] === "clear") {
    await clearCache();
    printer.out("Cache cleared");
    return 0;
  }

  if (command === "quote") {
    const { flags, values } = parseArgs(argv.slice(1));
    const modelName = values.get("--model");
    if (modelName === undefined) {
      throw new Error("Missing required option --model");
    }

    const inputTokens = parseIntOption(values.get("--input"), "--input");
    const outputTokens = parseIntOption(values.get("--output"), "--output");
    const cacheTimeout = parseCacheTimeout(values.get("--cache-timeout"));

    const result = await cost(
      modelName,
      inputTokens,
      outputTokens,
      cacheTimeout !== undefined ? { cacheTimeout } : {}
    );
    if (result === null) {
      printer.err(`Model not found: ${modelName}`);
      return 1;
    }

    emit(
      {
        model: modelName,
        input_cost: result.inputCost.toFixed(6),
        output_cost: result.outputCost.toFixed(6),
        total_cost: result.totalCost.toFixed(6),
        currency: result.currency
      },
      flags.has("--json"),
      printer.out
    );
    return 0;
  }

  if (command === "model") {
    const { flags, values } = parseArgs(argv.slice(1));
    const modelName = values.get("--model");
    if (modelName === undefined) {
      throw new Error("Missing required option --model");
    }

    const cacheTimeout = parseCacheTimeout(values.get("--cache-timeout"));
    const result = await model(modelName, cacheTimeout !== undefined ? { cacheTimeout } : {});
    if (result === null) {
      printer.err(`Model not found: ${modelName}`);
      return 1;
    }

    emit(
      {
        model: result.model,
        input_cost_per_token: result.inputCostPerToken.toString(),
        output_cost_per_token: result.outputCostPerToken.toString(),
        currency: result.currency,
        provider: result.provider ?? "",
        last_updated: result.lastUpdated ?? ""
      },
      flags.has("--json"),
      printer.out
    );
    return 0;
  }

  throw new Error(`Unknown command: ${command}`);
}

const isDirectExecution =
  process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isDirectExecution) {
  main(process.argv.slice(2))
    .then((code) => {
      process.exitCode = code;
    })
    .catch((error: unknown) => {
      const message = error instanceof Error ? error.message : "Unknown error";
      process.stderr.write(`${message}\n`);
      process.exitCode = 1;
    });
}
