# llmcalc

`llmcalc` is a native JavaScript/TypeScript implementation for estimating LLM token costs from `litellm` pricing data.

## Install

```bash
npm install llmcalc
```

## API

```ts
import { cost } from "llmcalc";

const result = await cost("gpt-5.1", 1200, 800);
if (result) {
  console.log(result.totalCost.toString(), result.currency);
}
```

## Long-Context and Tiered Pricing

Some models change price with request size, in two different ways:

- **Threshold pricing.** A model-specific prompt-size cutoff replaces whichever premium rate fields the model publishes for the whole request. The trigger is input tokens only. Most providers require the count to exceed the cutoff; xAI includes a request exactly at the cutoff.
- **Request-tier pricing.** Total input length selects one request-wide tier. Its input rate also provides the fallback for cache reads and writes. Its output rate provides the fallback for reasoning; an input-only tier row keeps the model's flat output rate.

`tierApplied` tells you which one produced a price:

```ts
(await cost("gpt-5.5", 100_000, 5_000))?.tierApplied; // null -> base rates
(await cost("gpt-5.5", 300_000, 5_000))?.tierApplied; // 'above_272k_tokens'
(await cost("dashscope/qwen3-max", 300_000, 5_000))?.tierApplied; // 'tiered_pricing'
```

Models priced purely through request-size tiers publish no flat per-token rate, so
`inputCostPerToken` and `outputCostPerToken` can be `null`.

## Processing Modes

Use `processingMode` to select standard, batch, priority, or flex pricing when
LiteLLM publishes that mode for the model. `fast` is an alias for priority:

```ts
await cost("gpt-5.5", 100_000, 5_000, { processingMode: "batch" });
await cost("gpt-5.5", 100_000, 5_000, { processingMode: "priority" });
await cost("gpt-5.5", 100_000, 5_000, { processingMode: "flex" });
```

`usage()` reads provider fields such as `service_tier` and `traffic_type`; a
mode reported by the provider takes precedence over the mode supplied by the
caller. `CostBreakdown.processingMode` records the mode used. Mode-specific
long-context rates use the same provider boundary rules as standard rates.
Batch discounts stack with long-context rates. Gemini keeps its published
cache rates in batch while discounting token modalities, and Anthropic
`provider_specific_entry.fast` pricing is exposed through the `fast` alias.

## Cached and Reasoning Tokens

Cache reads are often cheaper than fresh input, and cache *writes* can
cost more than fresh input, so ignoring them skews a total badly in either
direction. Pass the subsets and llmcalc prices each at its own rate:

```ts
await cost("gpt-5.5", 100_000, 1_000, { cachedTokens: 90_000 });
//   10_000 fresh @ 5e-06   = 0.05
//   90_000 cached @ 5e-07  = 0.045
//    1_000 output @ 3e-05  = 0.03
//   totalCost              = 0.125  (vs 0.53 if cached were billed as fresh)
```

`inputTokens` is the **total** prompt count, inclusive of `cachedTokens` and
`cacheCreationTokens`; `outputTokens` is inclusive of `reasoningTokens`. Models
that declare no cache or reasoning rate bill those tokens at the plain
input/output rate.

`usage()` picks the subsets up automatically across OpenAI, Anthropic, Gemini,
and Bedrock usage shapes. OpenAI and Gemini include cached tokens in their
input total, while Anthropic and Bedrock report cache reads and writes in
addition to their plain input count.

When Gemini tool-use prompt tokens are present, llmcalc checks the reported
`totalTokenCount` to determine whether the supplied prompt total already
includes them. Inconsistent or ambiguous metadata is rejected.

Generic cache-write counts are priced at the model's default cache-creation
rate, normally the 5-minute rate. Set `cacheCreationTokens1h` to the one-hour
subset of `cacheCreationTokens` when the model publishes a separate one-hour
rate. `usage()` reads Anthropic's 5-minute and 1-hour cache details and Bedrock's
cache-detail TTLs automatically. Supplying one-hour tokens for a model without
that rate raises an error instead of applying the wrong price.

For realtime audio, `cacheCreationAudioTokens` is the subset shared by
`cacheCreationTokens` and `inputAudioTokens`. It requires the model's published
audio cache-write rate and is reported as `cacheCreationAudioCost`.

`CostBreakdown` reports the components: `cacheReadCost`, `cacheCreationCost`,
`reasoningCost`. `inputCost` and `outputCost` already include them, and
`totalCost` is always their sum.

Library calculations use 50 significant digits. The CLI serializes monetary
fields to six decimal places for stable cross-language output.

## Audio, Image, Query, and Regional Pricing

Audio and image token details can be separated from the total token counts with
`inputAudioTokens`, `outputAudioTokens`, `inputImageTokens`, and
`outputImageTokens`. `cachedAudioTokens` and `cachedImageTokens` are the modality
subsets of `cachedTokens`; the input and output modality counts remain subsets
of `inputTokens` and `outputTokens`.

Direct per-query, web-search, and Google Maps grounding charges use `queryCount`,
`webSearchRequests`, and `mapsGroundingRequests`. For per-query schedules keyed
by result limit, pass `queryResults` to select the inclusive
`max_results_range` band. Web search uses
`webSearchContext: "low"`, `"medium"`, or `"high"` and the model's declared
per-prompt or per-query billing unit. The default context is medium. Set
`region: "us"` or `region: "eu"` for a published data-residency uplift, or
`region: "regional"` for a published Vertex non-global endpoint uplift.
`region: "global"` is equivalent to the default with no uplift.
The multiplier applies to token costs and direct per-query costs; web-search
and Maps charges retain their published unit rates.

`CostBreakdown` exposes `cacheCreationAudioCost`, `cacheCreation1hCost`, `audioInputCost`,
`audioOutputCost`, `imageInputCost`, `imageOutputCost`, `queryCost`, and
`regionalMultiplier`. A nonzero count is rejected when the selected model does
not publish the corresponding price. Video tokens and other unmodeled billing
units remain unsupported.

The CLI exposes the same inputs as `--cache-creation-1h`, `--cache-creation-audio`, `--cached-audio`,
`--cached-image`, `--input-audio`, `--output-audio`, `--input-image`,
`--output-image`, `--queries`, `--query-results`, `--web-searches`, `--web-search-context`,
`--maps-grounding`, and `--region`.

## Token Counts, Not Text

llmcalc takes token counts. It does not accept strings or message arrays, and it
does not tokenize. Pass counts from your provider's `usage` response. Supported
usage details include processing modes, cache durations, audio/image tokens,
direct query counts, web-search requests, and Maps grounding requests. Both
snake_case and camelCase usage keys work:

```ts
import { usage } from "llmcalc";

await usage("gpt-5.5", response.usage);
await usage("gpt-5.5", { prompt_tokens: 1000, completion_tokens: 500 });
await usage("gpt-5.5", { inputTokens: 1000, outputTokens: 500 });
```

Provider objects are validated before pricing. Inconsistent totals, unsupported
modalities, and nonzero dimensions without a published rate raise an error
instead of silently falling back to text pricing.

## Historical LiteLLM Snapshots

Pass `snapshotAt: "YYYY-MM-DD"` to `model()`, `cost()`, `usage()`, or
`pricingReport()` to use the last commit to LiteLLM's root pricing file on or
before `23:59:59 UTC` that day:

```ts
await cost("gpt-4", 10_000, 1_000, { snapshotAt: "2024-01-01" });
```

The CLI uses `--snapshot-at`. Dates must be completed UTC days on or after
`2023-09-06`. Snapshot lookup works only with the default LiteLLM source.
Resolved commit IDs and compressed payloads are cached beside the normal cache
and removed by `cache clear`.

This is LiteLLM repository snapshot history. It reproduces the pricing data
LiteLLM had recorded by that date. It is not an authoritative provider
effective-date timeline and must not be treated as invoice reconstruction.
Providers can announce prices before LiteLLM records them, and later commits can
correct earlier data.

## Pricing Diagnostics

Normal parsing keeps valid models while recording deterministic diagnostics for
skipped entries and ignored fields. Inspect them with `pricingReport()` or
`pricingReportAsync()`:

```ts
import { pricingReport } from "llmcalc";

const report = await pricingReport();
for (const item of report.diagnostics) {
  console.log(item.severity, item.model, item.code, item.action, item.path);
}
```

Each diagnostic contains `model`, `severity`, `code`, `action`, `path`, and
`message`. Library calls with `{ strict: true }` throw `PricingSchemaError` for
any warning or error; informational exclusions remain allowed. The equivalent
CLI command prints the full report before `--strict` exits nonzero:

```bash
llmcalc pricing check
llmcalc pricing check --strict --json
llmcalc pricing check --snapshot-at 2024-01-01 --json
```

## CLI

```bash
llmcalc quote --model gpt-5.1 --input 1200 --output 800
llmcalc quote --model gpt-5.5 --input 100000 --output 1000 --cached 90000
llmcalc quote --model gpt-5.1 --input 1200 --output 800 --processing-mode batch
llmcalc quote --model gpt-4 --input 10000 --output 1000 --snapshot-at 2024-01-01
llmcalc model --model gpt-5.1 --json
llmcalc pricing check --strict --json
llmcalc cache clear
llmcalc --version
llmcalc -v
```

## Environment

- `LLMCALC_CACHE_TIMEOUT`: cache TTL in seconds (default `43200`)
- `LLMCALC_PRICING_URL`: override pricing source URL
- `LLMCALC_CURRENCY`: fallback label only for a custom `LLMCALC_PRICING_URL`
  that omits currency; ignored for the default LiteLLM source and does not
  convert prices
- `LLMCALC_CACHE_PATH`: override the cache file location (default: platform cache dir)
