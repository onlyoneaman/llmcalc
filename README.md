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

Pricing is pulled from [`llmlite`](https://github.com/llmlite/llmlite) model pricing data and cached locally.

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
- `LLMCALC_CACHE_PATH`: optional cache file path override (JavaScript package)

## Maintainers

Contributor workflows and release validation live in `AGENTS.md`.
