#!/usr/bin/env node

import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { cost, model, clearCache, pricingReport } from "./api.js";
import { getPackageVersion } from "./config.js";
import { Decimal } from "./decimal.js";

interface Printer {
  out: (message: string) => void;
  err: (message: string) => void;
}

function printHelp(print: (message: string) => void): void {
  print(`llmcalc ${getPackageVersion()}`);
  print("Usage:");
  print(
    "  llmcalc quote --model <id> --input <tokens> --output <tokens> " +
      "[--cached <tokens>] [--cache-creation <tokens>] [--reasoning <tokens>] " +
      "[--processing-mode <mode>] [--cache-creation-1h <tokens>] " +
      "[--cache-creation-audio <tokens>] [--query-results <count>] " +
      "[--snapshot-at YYYY-MM-DD] [--cache-timeout <sec>] [--json]"
  );
  print("  llmcalc model --model <id> [--snapshot-at YYYY-MM-DD] [--cache-timeout <sec>] [--json]");
  print("  llmcalc cache clear");
  print("  llmcalc pricing check [--strict] [--snapshot-at YYYY-MM-DD] [--cache-timeout <sec>] [--json]");
  print("  llmcalc --version | -v");
}

function printQuoteHelp(print: (message: string) => void): void {
  print(
    "Usage: llmcalc quote --model <id> --input <tokens> --output <tokens> " +
      "[--cached <tokens>] [--cache-creation <tokens>] [--reasoning <tokens>] " +
      "[--processing-mode <mode>] [--cache-creation-1h <tokens>] " +
      "[--cache-creation-audio <tokens>] [--query-results <count>] " +
      "[--snapshot-at YYYY-MM-DD] [--cache-timeout <sec>] [--json]"
  );
}

function printModelHelp(print: (message: string) => void): void {
  print("Usage: llmcalc model --model <id> [--snapshot-at YYYY-MM-DD] [--cache-timeout <sec>] [--json]");
}

function printCacheHelp(print: (message: string) => void): void {
  print("Usage: llmcalc cache clear");
}

function printPricingHelp(print: (message: string) => void): void {
  print(
    "Usage: llmcalc pricing check [--strict] [--snapshot-at YYYY-MM-DD] " +
      "[--cache-timeout <sec>] [--json]"
  );
}

function parseArgs(
  args: string[],
  allowedValues: ReadonlySet<string>
): { flags: Set<string>; values: Map<string, string> } {
  const flags = new Set<string>();
  const values = new Map<string, string>();

  for (let i = 0; i < args.length; i += 1) {
    const token = args[i] ?? "";
    if (token === "--json") {
      flags.add(token);
      continue;
    }
    const equalsIndex = token.indexOf("=");
    const option = equalsIndex < 0 ? token : token.slice(0, equalsIndex);
    const inlineValue = equalsIndex < 0 ? undefined : token.slice(equalsIndex + 1);
    if (!allowedValues.has(option)) {
      throw new Error(token.startsWith("-") ? `Unknown option: ${token}` : `Unexpected argument: ${token}`);
    }

    const next = inlineValue ?? args[i + 1];
    if (next === undefined || (inlineValue === undefined && next.startsWith("-"))) {
      throw new Error(`Missing value for ${option}`);
    }
    values.set(option, next);
    if (inlineValue === undefined) {
      i += 1;
    }
  }

  return { flags, values };
}

function parseNonNegativeInt(raw: string, name: string): number {
  const normalized = raw.trim();
  const parsed = Number(normalized);
  if (!/^[+]?\d+$/.test(normalized) || !Number.isSafeInteger(parsed)) {
    throw new Error(`${name} must be a non-negative integer`);
  }
  return parsed;
}

function parseOptionalIntOption(raw: string | undefined, name: string): number {
  return raw === undefined ? 0 : parseNonNegativeInt(raw, name);
}

function parseIntOption(raw: string | undefined, name: string): number {
  if (raw === undefined) {
    throw new Error(`Missing required option ${name}`);
  }
  return parseNonNegativeInt(raw, name);
}

function parseCacheTimeout(raw: string | undefined): number | undefined {
  if (raw === undefined) {
    return undefined;
  }

  const normalized = raw.trim();
  const parsed = Number(normalized);
  if (!/^[+]?\d+$/.test(normalized) || !Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error("--cache-timeout must be a positive integer");
  }

  return parsed;
}

function emit(
  data: Record<string, unknown>,
  asJson: boolean,
  out: (message: string) => void
): void {
  if (asJson) {
    out(JSON.stringify(data));
    return;
  }

  for (const [key, value] of Object.entries(data)) {
    const rendered = Array.isArray(value)
      ? value.every((item) => typeof item === "string")
        ? `[${value.map((item) => `'${item}'`).join(", ")}]`
        : JSON.stringify(value)
      : value === null
        ? "None"
        : typeof value === "object"
          ? JSON.stringify(value)
          : value;
    out(`${key}: ${rendered}`);
  }
}

/**
 * Render a per-token rate in plain decimal notation.
 *
 * `toString()` yields `"7.5e-8"` for small values, where Python's
 * `str(Decimal)` yields `"7.5E-8"`. Both CLIs emit plain notation so their
 * JSON output matches.
 */
function rate(value: Decimal | null): string | null {
  return value === null ? null : value.toFixed();
}

export async function main(argv: string[], printer: Printer = {
  out: (message: string) => process.stdout.write(`${message}\n`),
  err: (message: string) => process.stderr.write(`${message}\n`)
}): Promise<number> {
  if (argv.length === 0 || argv[0] === "--help" || argv[0] === "-h") {
    printHelp(printer.out);
    return 0;
  }

  if (argv[0] === "--version" || argv[0] === "-v") {
    printer.out(`llmcalc ${getPackageVersion()}`);
    return 0;
  }

  const command = argv[0];

  if (command === "cache") {
    if (argv.slice(1).includes("--help") || argv.slice(1).includes("-h")) {
      printCacheHelp(printer.out);
      return 0;
    }
    if (argv[1] !== "clear") {
      throw new Error(`Unknown cache command: ${argv[1] ?? ""}`);
    }
    if (argv.length !== 2) {
      throw new Error(`Unexpected argument: ${argv[2] ?? ""}`);
    }
    await clearCache();
    printer.out("Cache cleared");
    return 0;
  }

  if (command === "pricing") {
    if (argv.slice(1).includes("--help") || argv.slice(1).includes("-h")) {
      printPricingHelp(printer.out);
      return 0;
    }
    if (argv[1] !== "check") {
      throw new Error(`Unknown pricing command: ${argv[1] ?? ""}`);
    }
    const strict = argv.includes("--strict");
    const checkArgs = argv.slice(2).filter((value) => value !== "--strict");
    const { flags, values } = parseArgs(
      checkArgs,
      new Set(["--snapshot-at", "--cache-timeout"])
    );
    const cacheTimeout = parseCacheTimeout(values.get("--cache-timeout"));
    const snapshotAt = values.get("--snapshot-at");
    const report = await pricingReport({
      ...(cacheTimeout !== undefined ? { cacheTimeout } : {}),
      ...(snapshotAt !== undefined ? { snapshotAt } : {})
    });
    const payload = {
      model_count: Object.keys(report.models).length,
      diagnostic_count: report.diagnostics.length,
      diagnostics: report.diagnostics
    };
    if (flags.has("--json")) {
      printer.out(JSON.stringify(payload));
    } else {
      printer.out(`Models: ${payload.model_count}`);
      printer.out(`Diagnostics: ${payload.diagnostic_count}`);
      for (const diagnostic of report.diagnostics) {
        const pathName = diagnostic.path.join(".");
        const location = pathName.length === 0
          ? diagnostic.model
          : `${diagnostic.model}.${pathName}`;
        printer.out(
          `${diagnostic.severity}: ${location}: ${diagnostic.code}: ${diagnostic.message}`
        );
      }
    }
    if (strict && report.diagnostics.some((item) => item.severity !== "info")) {
      return 1;
    }
    return 0;
  }

  if (command === "quote") {
    if (argv.includes("--help") || argv.includes("-h")) {
      printQuoteHelp(printer.out);
      return 0;
    }
    const { flags, values } = parseArgs(
      argv.slice(1),
      new Set([
        "--model",
        "--input",
        "--output",
        "--cached",
        "--cache-creation",
        "--reasoning",
        "--processing-mode",
        "--cache-creation-1h",
        "--cache-creation-audio",
        "--cached-audio",
        "--cached-image",
        "--input-audio",
        "--output-audio",
        "--input-image",
        "--output-image",
        "--queries",
        "--query-results",
        "--web-searches",
        "--web-search-context",
        "--maps-grounding",
        "--region",
        "--snapshot-at",
        "--cache-timeout"
      ])
    );
    const modelName = values.get("--model");
    if (modelName === undefined) {
      throw new Error("Missing required option --model");
    }

    const inputTokens = parseIntOption(values.get("--input"), "--input");
    const outputTokens = parseIntOption(values.get("--output"), "--output");
    const cachedTokens = parseOptionalIntOption(values.get("--cached"), "--cached");
    const cacheCreationTokens = parseOptionalIntOption(
      values.get("--cache-creation"),
      "--cache-creation"
    );
    const reasoningTokens = parseOptionalIntOption(values.get("--reasoning"), "--reasoning");
    const cacheCreationTokens1h = parseOptionalIntOption(
      values.get("--cache-creation-1h"),
      "--cache-creation-1h"
    );
    const cacheCreationAudioTokens = parseOptionalIntOption(
      values.get("--cache-creation-audio"),
      "--cache-creation-audio"
    );
    const cachedAudioTokens = parseOptionalIntOption(values.get("--cached-audio"), "--cached-audio");
    const cachedImageTokens = parseOptionalIntOption(values.get("--cached-image"), "--cached-image");
    const inputAudioTokens = parseOptionalIntOption(values.get("--input-audio"), "--input-audio");
    const outputAudioTokens = parseOptionalIntOption(values.get("--output-audio"), "--output-audio");
    const inputImageTokens = parseOptionalIntOption(values.get("--input-image"), "--input-image");
    const outputImageTokens = parseOptionalIntOption(values.get("--output-image"), "--output-image");
    const queryCount = parseOptionalIntOption(values.get("--queries"), "--queries");
    const queryResultsValue = values.get("--query-results");
    const queryResults = queryResultsValue === undefined
      ? undefined
      : parseOptionalIntOption(queryResultsValue, "--query-results");
    const webSearchRequests = parseOptionalIntOption(values.get("--web-searches"), "--web-searches");
    const mapsGroundingRequests = parseOptionalIntOption(
      values.get("--maps-grounding"),
      "--maps-grounding"
    );
    const region = values.get("--region");
    const snapshotAt = values.get("--snapshot-at");
    const cacheTimeout = parseCacheTimeout(values.get("--cache-timeout"));

    const result = await cost(modelName, inputTokens, outputTokens, {
      ...(cacheTimeout !== undefined ? { cacheTimeout } : {}),
      cachedTokens,
      cacheCreationTokens,
      reasoningTokens,
      processingMode: values.get("--processing-mode") ?? "standard",
      ...(snapshotAt !== undefined ? { snapshotAt } : {}),
      cacheCreationTokens1h,
      cacheCreationAudioTokens,
      cachedAudioTokens,
      cachedImageTokens,
      inputAudioTokens,
      outputAudioTokens,
      inputImageTokens,
      outputImageTokens,
      queryCount,
      ...(queryResults !== undefined ? { queryResults } : {}),
      webSearchRequests,
      webSearchContext: values.get("--web-search-context") ?? "medium",
      mapsGroundingRequests,
      ...(region !== undefined ? { region } : {})
    });
    if (result === null) {
      printer.err(`Model not found: ${modelName}`);
      return 1;
    }

    const displayedInput = result.inputCost.toDecimalPlaces(6, Decimal.ROUND_HALF_UP);
    const displayedOutput = result.outputCost.toDecimalPlaces(6, Decimal.ROUND_HALF_UP);
    emit(
      {
        model: modelName,
        input_cost: displayedInput.toFixed(6),
        output_cost: displayedOutput.toFixed(6),
        total_cost: displayedInput.add(displayedOutput).toFixed(6),
        currency: result.currency,
        tier_applied: result.tierApplied,
        cache_read_cost: result.cacheReadCost.toFixed(6),
        cache_creation_cost: result.cacheCreationCost.toFixed(6),
        cache_creation_audio_cost: result.cacheCreationAudioCost.toFixed(6),
        cache_creation_1h_cost: result.cacheCreation1hCost.toFixed(6),
        reasoning_cost: result.reasoningCost.toFixed(6),
        audio_input_cost: result.audioInputCost.toFixed(6),
        audio_output_cost: result.audioOutputCost.toFixed(6),
        image_input_cost: result.imageInputCost.toFixed(6),
        image_output_cost: result.imageOutputCost.toFixed(6),
        query_cost: result.queryCost.toFixed(6),
        processing_mode: result.processingMode,
        regional_multiplier: result.regionalMultiplier.toFixed()
      },
      flags.has("--json"),
      printer.out
    );
    return 0;
  }

  if (command === "model") {
    if (argv.includes("--help") || argv.includes("-h")) {
      printModelHelp(printer.out);
      return 0;
    }
    const { flags, values } = parseArgs(
      argv.slice(1),
      new Set(["--model", "--snapshot-at", "--cache-timeout"])
    );
    const modelName = values.get("--model");
    if (modelName === undefined) {
      throw new Error("Missing required option --model");
    }

    const cacheTimeout = parseCacheTimeout(values.get("--cache-timeout"));
    const snapshotAt = values.get("--snapshot-at");
    const result = await model(modelName, {
      ...(cacheTimeout !== undefined ? { cacheTimeout } : {}),
      ...(snapshotAt !== undefined ? { snapshotAt } : {})
    });
    if (result === null) {
      printer.err(`Model not found: ${modelName}`);
      return 1;
    }

    emit(
      {
        model: result.model,
        input_cost_per_token: rate(result.inputCostPerToken),
        output_cost_per_token: rate(result.outputCostPerToken),
        thresholds: result.thresholds.map((threshold) => threshold.key),
        tier_count: result.tieredPricing.length,
        processing_modes: Object.keys(result.pricingModes).sort(),
        cache_read_cost_per_token: rate(result.cacheReadCostPerToken),
        cache_read_audio_cost_per_token: rate(result.cacheReadAudioCostPerToken),
        cache_creation_cost_per_token: rate(result.cacheCreationCostPerToken),
        cache_creation_audio_cost_per_token: rate(result.cacheCreationAudioCostPerToken),
        cache_creation_1h_cost_per_token: rate(result.cacheCreation1hCostPerToken),
        reasoning_cost_per_token: rate(result.reasoningCostPerToken),
        input_audio_cost_per_token: rate(result.inputAudioCostPerToken),
        output_audio_cost_per_token: rate(result.outputAudioCostPerToken),
        input_image_cost_per_token: rate(result.inputImageCostPerToken),
        output_image_cost_per_token: rate(result.outputImageCostPerToken),
        input_cost_per_query: rate(result.inputCostPerQuery),
        query_pricing: result.queryPricing.map((tier) => ({
          range: [tier.rangeStart, tier.rangeEnd],
          input_cost_per_query: tier.rate.toFixed()
        })),
        search_context_cost_per_query: Object.fromEntries(
          Object.entries(result.searchContextCostPerQuery).map(([key, value]) => [
            key,
            value.toFixed()
          ])
        ),
        google_maps_grounding_cost_per_query: rate(
          result.googleMapsGroundingCostPerQuery
        ),
        web_search_billing_unit: result.webSearchBillingUnit,
        regional_processing_uplift: Object.fromEntries(
          Object.entries(result.regionalProcessingUplift).map(([key, value]) => [
            key,
            value.toFixed()
          ])
        ),
        currency: result.currency,
        provider: result.provider,
        last_updated: result.lastUpdated
      },
      flags.has("--json"),
      printer.out
    );
    return 0;
  }

  throw new Error(`Unknown command: ${command}`);
}

function isDirectExecution(): boolean {
  if (process.argv[1] === undefined) {
    return false;
  }
  try {
    return realpathSync(process.argv[1]) === fileURLToPath(import.meta.url);
  } catch {
    return false;
  }
}

if (isDirectExecution()) {
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
