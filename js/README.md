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
