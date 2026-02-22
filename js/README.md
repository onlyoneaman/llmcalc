# llmcalc

`llmcalc` is a native JavaScript/TypeScript implementation for estimating LLM token costs from `llmlite` pricing data.

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
- `LLMCALC_CACHE_PATH`: optional absolute cache file path override
