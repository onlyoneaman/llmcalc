# llmcalc

`llmcalc` is a Python package to calculate LLM token costs from `llmlite` pricing data.

## Install

```bash
pip install llmcalc
```

## Python usage

```python
import asyncio
from llmcalc import calculate_token_cost

result = asyncio.run(calculate_token_cost("gpt-4o-mini", 1200, 800))
if result:
    print(result.total_cost)
```

## CLI usage

```bash
llmcalc quote --model gpt-4o-mini --input 1200 --output 800
llmcalc model --model gpt-4o-mini --json
llmcalc cache clear
llmcalc --version
```

## Defaults

- Default cache TTL is `43200` seconds (12 hours).
- Override cache TTL with `LLMCALC_CACHE_TIMEOUT`.
- Override pricing source with `LLMCALC_PRICING_URL`.
- Set fallback currency label with `LLMCALC_CURRENCY` (used only when upstream omits currency).

## Release Validation

```bash
python -m build --no-isolation
python -m twine check dist/*
```
