# Changelog

## 0.2.0

### Fixed
- Pricing source pointed at `llmlite/llmlite`, a repository that has never existed, so every uncached call raised `PricingFetchError`. Now uses `BerriAI/litellm`. Every existing test stubbed the fetch, so nothing ever resolved the default URL.
- Long-context and tiered pricing were ignored entirely. `gpt-5.5` at 300k input / 5k output was quoted at `1.6500` instead of `3.2250`, a 1.95x understatement.
- 18 tiered chat models (dashscope, volcengine) returned `None` from `cost()`: they carry no base per-token rates, so parsing raised and dropped them from the table. The parsed table goes from 2497 to 2515 models.
- Bedrock model ids ending in a version suffix (`...-v1:0`) normalized to `"0"`, so `resolve_model_key("0")` returned a real Claude model with real prices. 220 ids were affected.
- `total_cost` rounded each leg and then rounded their sum again; it is now derived from the unrounded legs.
- `bool` token counts were accepted because `bool` subclasses `int`, billing `True` as one token.
- JS `normalizeModelName` used `split(sep, 2)`, which truncates rather than limiting splits, so `openai/foo/bar` normalized to `foo` in JS and `foo/bar` in Python.
- Python `usage()` rejected the camelCase keys JS accepted.
- Python ignored `LLMCALC_CACHE_PATH`, which JS honoured.
- The two CLIs stringified `Decimal` differently: `str(Decimal)` yields `7.5E-8` where JS `toString()` yields `7.5e-8`. Both now emit plain decimal notation. The JS `model` command also emitted `""` for absent `provider`/`last_updated` where Python emitted `null`.

### Added
- **Cached and reasoning token pricing.** `cost()` takes `cached_tokens`, `cache_creation_tokens` and `reasoning_tokens` (JS: `cachedTokens`, `cacheCreationTokens`, `reasoningTokens` on the options object), each priced at its own rate with a fallback to the plain input/output rate. Covers 710 models with a cache-read rate, 243 with a cache-creation rate, and 53 with a reasoning rate; also reads DeepSeek's `input_cost_per_token_cache_hit` spelling. `input_tokens` is the total prompt count, inclusive of both cache subsets.
- `usage()` now normalizes the two opposite provider conventions by key name rather than guessing: OpenAI reports `prompt_tokens_details.cached_tokens` as a **subset** of `prompt_tokens`, while Anthropic reports `cache_read_input_tokens` **in addition to** `input_tokens`. Previously a cache-heavy OpenAI call was over-billed ~4x and an Anthropic one under-billed ~3.5x.
- `CostBreakdown.cache_read_cost`, `.cache_creation_cost`, `.reasoning_cost` (JS: `cacheReadCost`, `cacheCreationCost`, `reasoningCost`) so the components of a total are visible. `input_cost` and `output_cost` include them; `total_cost` is always their sum.
- CLI `quote` gains `--cached`, `--cache-creation` and `--reasoning`, and reports the three component costs.
- Threshold pricing now swaps the cache-read and cache-creation rates too, not just input/output, matching litellm.
- `CostBreakdown.tier_applied` / `tierApplied`, naming the tier that produced a price (`above_272k_tokens`, `tiered_pricing`, or `None`).
- `ModelPricing.thresholds` and `.tiered_pricing` / `.tieredPricing`.
- CLI `quote` reports `tier_applied`; `model` reports `thresholds` and `tier_count`.
- `LLMCALC_CACHE_PATH` in Python, matching JS.
- `tests/fixtures/tiered_cases.json`, a shared fixture both test suites assert against.
- `tests/test_parity.py`, which diffs both CLIs' JSON output offline.
- Network-marked tests that resolve the real pricing URL.

### Changed
- **Breaking:** `ModelPricing.input_cost_per_token` and `.output_cost_per_token` are now optional, since tiered models publish no base rates. Consumers reading them directly must handle `None`.
- `ModelPricing` gains `cache_read_cost_per_token`, `cache_creation_cost_per_token` and `reasoning_cost_per_token` (JS: camelCase equivalents).
- Strings and message arrays now raise an error explaining that llmcalc takes token counts and does not tokenize. Token counts remain the only supported input.

## 0.1.2
- Added a separate JavaScript/TypeScript implementation under `js/` for npm publishing.
- Added a native Node CLI (`llmcalc`) with `quote`, `model`, `cache clear`, and version flags.
- Added JS module parity for config, normalization, pricing parsing/fetching, cache, and API helpers.
- Added JavaScript tests for API, pricing client, normalization, cache, models, and CLI behavior.
- Extended CI with a dedicated JavaScript job (`build`, `typecheck`, `test`, `npm pack --dry-run`).

## 0.1.1
- Simplified public API naming to short helpers:
  - Sync: `cost`, `usage`, `model`
  - Async: `cost_async`, `usage_async`, `model_async`
- Updated CLI internals to use sync API helpers directly.
- Improved `README.md` with badges, clearer quickstart, and current model examples (`gpt-5.1`).
- Refreshed tests and model fixtures to use `gpt-5.1`.
- Added `gpt-5.1-latest` normalization alias.
- Added `.venv/` to `.gitignore` and documented `.venv` dev setup in `AGENTS.md`.

## 0.1.0
- Initial release with pricing fetch, cache, normalization, API, and CLI.
