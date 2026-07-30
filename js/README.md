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

- **Threshold pricing.** Above a prompt-size cutoff, the whole request bills at a premium rate. OpenAI's cutoff is 272k tokens, Anthropic's 200k, Gemini's 128k. Crossing it changes the input *and* output rate. The trigger is input tokens only, and it is strictly greater, so a request of exactly the cutoff stays on base rates.
- **Graduated pricing.** Tokens bill in slices, income-tax style.

`tierApplied` tells you which one produced a price:

```ts
(await cost("gpt-5.5", 100_000, 5_000))?.tierApplied; // null -> base rates
(await cost("gpt-5.5", 300_000, 5_000))?.tierApplied; // 'above_272k_tokens'
(await cost("dashscope/qwen3-max", 300_000, 5_000))?.tierApplied; // 'tiered_pricing'
```

Models priced purely through graduated tiers publish no flat per-token rate, so
`inputCostPerToken` and `outputCostPerToken` can be `null`.

## Cached and Reasoning Tokens

Cache reads are typically 10x cheaper than fresh input, and cache *writes* can
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
input/output rate, so passing the counts is always safe.

`usage()` picks the subsets up automatically, and handles the fact that the two
major providers use **opposite conventions** — OpenAI reports
`prompt_tokens_details.cached_tokens` as part of `prompt_tokens`, while
Anthropic reports `cache_read_input_tokens` *in addition to* `input_tokens`.

`CostBreakdown` reports the components: `cacheReadCost`, `cacheCreationCost`,
`reasoningCost`. `inputCost` and `outputCost` already include them, and
`totalCost` is always their sum.

## Token Counts, Not Text

llmcalc takes token counts. It does not accept strings or message arrays, and it
does not tokenize — pass counts from your provider's `usage` response, which is
what you are actually billed for. Both snake_case and camelCase usage keys work:

```ts
import { usage } from "llmcalc";

await usage("gpt-5.5", response.usage);
await usage("gpt-5.5", { prompt_tokens: 1000, completion_tokens: 500 });
await usage("gpt-5.5", { inputTokens: 1000, outputTokens: 500 });
```

## CLI

```bash
llmcalc quote --model gpt-5.1 --input 1200 --output 800
llmcalc quote --model gpt-5.5 --input 100000 --output 1000 --cached 90000
llmcalc model --model gpt-5.1 --json
llmcalc cache clear
llmcalc --version
llmcalc -v
```

## Environment

- `LLMCALC_CACHE_TIMEOUT`: cache TTL in seconds (default `43200`)
- `LLMCALC_PRICING_URL`: override pricing source URL
- `LLMCALC_CURRENCY`: fallback currency label if upstream omits currency
- `LLMCALC_CACHE_PATH`: override the cache file location (default: platform cache dir)
- `LLMCALC_CACHE_PATH`: optional absolute cache file path override
