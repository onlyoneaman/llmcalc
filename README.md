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
- Calculates input, output, and total costs with deterministic decimal rounding.
- Provides small Python and JavaScript APIs plus CLIs.
- Caches pricing data locally (default TTL: `43200` seconds).

## Cost Formula

`total = (input_tokens * input_price_per_token) + (output_tokens * output_price_per_token)`

Pricing is pulled from [`litellm`](https://github.com/BerriAI/litellm) model pricing data and cached locally.

## Long-Context and Tiered Pricing

Some models change price with request size, in two different ways:

- **Threshold pricing.** Above a prompt-size cutoff, the whole request bills at a premium rate. OpenAI's cutoff is 272k tokens, Anthropic's 200k, Gemini's 128k. Crossing it changes the input *and* output rate. The trigger is input tokens only, and it is strictly greater, so a request of exactly the cutoff stays on base rates.
- **Graduated pricing.** Tokens bill in slices, income-tax style: the first N at one rate, the next M at another.

`tier_applied` tells you which one produced a price:

```python
from llmcalc import cost

cost("gpt-5.5", 100_000, 5_000).tier_applied   # None -> base rates
cost("gpt-5.5", 300_000, 5_000).tier_applied   # 'above_272k_tokens'
cost("dashscope/qwen3-max", 300_000, 5_000).tier_applied  # 'tiered_pricing'
```

Models priced purely through graduated tiers publish no flat per-token rate, so
`input_cost_per_token` and `output_cost_per_token` can be `None`.

## Token Counts, Not Text

llmcalc takes token counts. It does not accept strings or message arrays, and it
does not tokenize — pass counts from your provider's `usage` response, which is
what you are actually billed for. Both snake_case and camelCase usage keys work:

```python
from llmcalc import usage

usage("gpt-5.5", response.usage)                          # provider object
usage("gpt-5.5", {"prompt_tokens": 1000, "completion_tokens": 500})
usage("gpt-5.5", {"inputTokens": 1000, "outputTokens": 500})
```

## Python Quickstart

```python
from llmcalc import cost

result = cost(
    model="gpt-5.1",
    input_tokens=1200,
    output_tokens=800,
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

# inspect per-token pricing for one model
llmcalc model --model gpt-5.1 --json

# clear local cache
llmcalc cache clear

# show version
llmcalc --version
llmcalc -v

# JavaScript CLI
llmcalc quote --model gpt-5.1 --input 1200 --output 800
llmcalc model --model gpt-5.1 --json
llmcalc cache clear
llmcalc --version
llmcalc -v
```

## Configuration

- `LLMCALC_CACHE_TIMEOUT`: cache TTL in seconds (default `43200`)
- `LLMCALC_PRICING_URL`: override pricing source URL
- `LLMCALC_CURRENCY`: fallback currency label if upstream omits currency
- `LLMCALC_CACHE_PATH`: override the cache file location (default: platform cache dir)
- `LLMCALC_CACHE_PATH`: optional cache file path override (JavaScript package)

## Maintainers

Contributor workflows and release validation live in `AGENTS.md`.
