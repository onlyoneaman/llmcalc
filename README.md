# llmcalc

[![PyPI version](https://img.shields.io/pypi/v/llmcalc.svg)](https://pypi.org/project/llmcalc/)
[![Python versions](https://img.shields.io/pypi/pyversions/llmcalc.svg)](https://pypi.org/project/llmcalc/)
[![CI](https://github.com/onlyoneaman/llmcalc/actions/workflows/ci.yml/badge.svg)](https://github.com/onlyoneaman/llmcalc/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/llmcalc.svg)](LICENSE)

`llmcalc` provides Python and JavaScript implementations for estimating LLM token costs.

## Install (Python)

```bash
pip install llmcalc
```

## Install (JavaScript)

```bash
npm install llmcalc
```

## What It Does

- Resolves model pricing from an upstream pricing source.
- Calculates token, cache, processing-mode, modality, query, grounding, and regional costs with 50-significant-digit decimal arithmetic.
- Provides small Python and JavaScript APIs plus CLIs.
- Caches pricing data locally (default TTL: `43200` seconds).
- Can replay completed-day snapshots from LiteLLM's repository history.
- Reports skipped pricing entries and malformed fields instead of hiding parser exclusions.

## Cost Formula

`total = (input_tokens * input_price_per_token) + (output_tokens * output_price_per_token)`

That is the simple case. Where a model prices long context, cached tokens or
reasoning tokens differently, llmcalc applies those rates too. See the two
sections below. `total_cost` is always the sum of `input_cost` and
`output_cost`, whichever rates applied.

Pricing is pulled from [`litellm`](https://github.com/BerriAI/litellm) model pricing data and cached locally.

## Long-Context and Tiered Pricing

Some models change price with request size, in two different ways:

- **Threshold pricing.** A model-specific prompt-size cutoff replaces whichever premium rate fields the model publishes for the whole request. The trigger is input tokens only. Most providers require the count to exceed the cutoff; xAI includes a request exactly at the cutoff.
- **Request-tier pricing.** Total input length selects one request-wide tier. Its input rate also provides the fallback for cache reads and writes. Its output rate provides the fallback for reasoning; an input-only tier row keeps the model's flat output rate.

`tier_applied` tells you which one produced a price:

```python
from llmcalc import cost

cost("gpt-5.5", 100_000, 5_000).tier_applied   # None -> base rates
cost("gpt-5.5", 300_000, 5_000).tier_applied   # 'above_272k_tokens'
cost("dashscope/qwen3-max", 300_000, 5_000).tier_applied  # 'tiered_pricing'
```

Models priced purely through request-size tiers publish no flat per-token rate, so
`input_cost_per_token` and `output_cost_per_token` can be `None`.

## Processing Modes

Use `processing_mode` to select standard, batch, priority, or flex pricing when
LiteLLM publishes that mode for the model. `fast` is an alias for priority:

```python
cost("gpt-5.5", 100_000, 5_000, processing_mode="batch")
cost("gpt-5.5", 100_000, 5_000, processing_mode="priority")
cost("gpt-5.5", 100_000, 5_000, processing_mode="flex")
```

JavaScript uses `processingMode`. `usage()` reads provider fields such as
`service_tier` and `traffic_type`; a mode reported by the provider takes
precedence over the mode supplied by the caller. `CostBreakdown.processing_mode`
records the mode used. Mode-specific long-context rates are selected with the
same provider boundary rules as standard rates. Batch discounts stack with
long-context rates. Gemini keeps its published cache rates in batch while
discounting token modalities, and Anthropic `provider_specific_entry.fast`
pricing is exposed through the `fast` alias.

## Cached and Reasoning Tokens

Cache reads are often cheaper than fresh input, and cache *writes* can
cost more than fresh input, so ignoring them skews a total badly in either
direction. Pass the subsets and llmcalc prices each at its own rate:

```python
from llmcalc import cost

cost("gpt-5.5", 100_000, 1_000, cached_tokens=90_000)
#   10_000 fresh @ 5e-06   = 0.05
#   90_000 cached @ 5e-07  = 0.045
#    1_000 output @ 3e-05  = 0.03
#   total_cost             = 0.125   (vs 0.53 if cached were billed as fresh)
```

`input_tokens` is the **total** prompt count, inclusive of `cached_tokens` and
`cache_creation_tokens`; `output_tokens` is inclusive of `reasoning_tokens`.
Models that declare no cache or reasoning rate simply bill those tokens at the
plain input/output rate.

`usage()` picks the subsets up automatically across OpenAI, Anthropic, Gemini,
and Bedrock usage shapes. It handles the fact that providers use opposite
conventions: OpenAI and Gemini include cached tokens in their input total,
while Anthropic and Bedrock report cache reads and writes in addition to their
plain input count:

```python
usage("gpt-5.5", openai_response.usage)        # cached is a subset
usage("claude-sonnet-4-6", anthropic_response.usage)  # cache is additive
usage("gemini-3.5-flash", gemini_response.usage_metadata)
```

When Gemini tool-use prompt tokens are present, llmcalc checks the reported
`total_token_count` to determine whether the supplied prompt total already
includes them. Inconsistent or ambiguous metadata is rejected.

Generic cache-write counts are priced at the model's default cache-creation
rate, normally the 5-minute rate. Set `cache_creation_tokens_1h` to the one-hour
subset of `cache_creation_tokens` when the model publishes a separate one-hour
rate. `usage()` reads Anthropic's 5-minute and 1-hour cache details and Bedrock's
cache-detail TTLs automatically. Supplying one-hour tokens for a model without
that rate raises an error instead of applying the wrong price.

For realtime audio, `cache_creation_audio_tokens` is the subset shared by
`cache_creation_tokens` and `input_audio_tokens`. It requires the model's
published audio cache-write rate and is reported as
`cache_creation_audio_cost`.

`CostBreakdown` reports the components: `cache_read_cost`,
`cache_creation_cost`, `reasoning_cost`. `input_cost` and `output_cost` already
include them, and `total_cost` is always their sum.

## Audio, Image, Query, and Regional Pricing

Audio and image token details can be separated from the total token counts with
`input_audio_tokens`, `output_audio_tokens`, `input_image_tokens`, and
`output_image_tokens`. `cached_audio_tokens` and `cached_image_tokens` are the
modality subsets of `cached_tokens`; the input and output modality counts remain
subsets of `input_tokens` and `output_tokens`. JavaScript uses the corresponding
camelCase names.

Direct per-query, web-search, and Google Maps grounding charges use
`query_count`, `web_search_requests`, and `maps_grounding_requests`. For
per-query schedules keyed by result limit, pass `query_results` to select the
inclusive `max_results_range` band. Web search
uses `web_search_context="low"`, `"medium"`, or `"high"` and the model's
declared per-prompt or per-query billing unit. The default context is medium.
Set `region="us"` or `region="eu"` for a published data-residency uplift, or
`region="regional"` for a published Vertex non-global endpoint uplift.
`region="global"` is equivalent to the default with no uplift.
The multiplier applies to token costs and direct per-query costs; web-search
and Maps charges retain their published unit rates.

`CostBreakdown` exposes `cache_creation_audio_cost`, `cache_creation_1h_cost`, `audio_input_cost`,
`audio_output_cost`, `image_input_cost`, `image_output_cost`, `query_cost`, and
`regional_multiplier`. A nonzero count is rejected when the selected model does
not publish the corresponding price. Video tokens and other unmodeled billing
units remain unsupported.

The CLI exposes the same inputs as `--cache-creation-1h`, `--cache-creation-audio`, `--cached-audio`,
`--cached-image`, `--input-audio`, `--output-audio`, `--input-image`,
`--output-image`, `--queries`, `--query-results`, `--web-searches`, `--web-search-context`,
`--maps-grounding`, and `--region`.

Library calculations use 50 significant digits. The CLIs serialize monetary
fields to six decimal places for stable cross-language output.

## Token Counts, Not Text

llmcalc takes token counts. It does not accept strings or message arrays, and it
does not tokenize. Pass counts from your provider's `usage` response. Supported
usage details include processing modes, cache durations, audio/image tokens,
direct query counts, web-search requests, and Maps grounding requests. Both
snake_case and camelCase usage keys work:

```python
from llmcalc import usage

usage("gpt-5.5", response.usage)                          # provider object
usage("gpt-5.5", {"prompt_tokens": 1000, "completion_tokens": 500})
usage("gpt-5.5", {"inputTokens": 1000, "outputTokens": 500})
```

Provider objects are validated before pricing. Inconsistent totals, unsupported
modalities, and nonzero dimensions without a published rate raise an error
instead of silently falling back to text pricing.

## Historical LiteLLM Snapshots

Pass `snapshot_at="YYYY-MM-DD"` to `model()`, `cost()`, `usage()`, or
`pricing_report()` to use the last commit to LiteLLM's root pricing file on or
before `23:59:59 UTC` that day:

```python
cost("gpt-4", 10_000, 1_000, snapshot_at="2024-01-01")
```

JavaScript uses `snapshotAt`; the CLI uses `--snapshot-at`. Dates must be
completed UTC days on or after `2023-09-06`. Snapshot lookup works only with the
default LiteLLM source. Resolved commit IDs and compressed payloads are cached
beside the normal cache and removed by `cache clear`.

This is LiteLLM repository snapshot history. It reproduces the pricing data
LiteLLM had recorded by that date. It is not an authoritative provider
effective-date timeline and must not be treated as invoice reconstruction.
Providers can announce prices before LiteLLM records them, and later commits can
correct earlier data.

## Pricing Diagnostics

Normal parsing keeps valid models while recording deterministic diagnostics for
skipped entries and ignored fields. Inspect them in Python with
`pricing_report()` or `pricing_report_async()` and in JavaScript with
`pricingReport()` or `pricingReportAsync()`:

```python
from llmcalc import pricing_report

report = pricing_report()
for item in report.diagnostics:
    print(item.severity, item.model, item.code, item.action, item.path)
```

Each diagnostic contains `model`, `severity`, `code`, `action`, `path`, and
`message`. Library calls with `strict=True` raise `PricingSchemaError` for any
warning or error; informational exclusions remain allowed. The equivalent CLI
command prints the full report before `--strict` exits nonzero:

```bash
llmcalc pricing check
llmcalc pricing check --strict --json
llmcalc pricing check --snapshot-at 2024-01-01 --json
```

## Python Quickstart

```python
from llmcalc import cost

result = cost(
    model="gpt-5.1",
    input_tokens=1200,
    output_tokens=800,
    processing_mode="standard",
)
if result is not None:
    print(result.total_cost, result.currency)
```

You can also calculate from usage-style objects via `usage(...)`.
Async variants are available as `cost_async(...)` and `usage_async(...)`.

## JavaScript Quickstart

```ts
import { cost } from "llmcalc";

const result = await cost("gpt-5.1", 1200, 800);
if (result !== null) {
  console.log(result.totalCost.toString(), result.currency);
}
```

## CLI Quickstart

```bash
# cost quote from token counts
llmcalc quote --model gpt-5.1 --input 1200 --output 800
llmcalc quote --model gpt-5.5 --input 100000 --output 1000 --cached 90000
llmcalc quote --model gpt-5.1 --input 1200 --output 800 --processing-mode batch
llmcalc quote --model gpt-4 --input 10000 --output 1000 --snapshot-at 2024-01-01

# inspect per-token pricing for one model
llmcalc model --model gpt-5.1 --json

# inspect skipped entries and ignored fields
llmcalc pricing check --strict --json

# clear local cache
llmcalc cache clear

# show version
llmcalc --version
llmcalc -v

# JavaScript CLI
llmcalc quote --model gpt-5.1 --input 1200 --output 800
llmcalc model --model gpt-5.1 --json
llmcalc pricing check --strict --json
llmcalc cache clear
llmcalc --version
llmcalc -v
```

## Configuration

- `LLMCALC_CACHE_TIMEOUT`: cache TTL in seconds (default `43200`)
- `LLMCALC_PRICING_URL`: override pricing source URL
- `LLMCALC_CURRENCY`: fallback label only for a custom `LLMCALC_PRICING_URL`
  that omits currency; ignored for the default LiteLLM source and does not
  convert prices
- `LLMCALC_CACHE_PATH`: override the cache file location (default: platform cache dir)

## Maintainers

Contributor workflows and release validation live in `AGENTS.md`.
