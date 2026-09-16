# Changelog

## Unreleased

## 0.2.2 - 2026-09-16

### Fixed
- The installed npm `llmcalc` executable now resolves its package-manager symlink before checking whether the CLI module is the process entrypoint. Version `0.2.1` could exit successfully without running a command when invoked through `node_modules/.bin`.

## 0.2.1 - 2026-09-16

### Fixed
- Token tiers now select one request-wide rate from total input length, including LiteLLM's cache, reasoning and input-only-tier fallbacks. The previous graduated calculation underquoted `dashscope/qwen-flash` at 300k input / 1k output by about 68.6%.
- Long-context thresholds now include the exact cutoff for xAI and remain strictly above the cutoff for other providers.
- Live provider metadata now reads LiteLLM's `litellm_provider` field instead of returning `null` for every model.
- Explicit zero-priced cache rates remain free in Python instead of falling back to the base input rate.
- `usage()` now recognizes Gemini and Gemini Live usage metadata, Anthropic thinking tokens, Bedrock cache-write aggregates, OpenAI Responses cache-write details, provider processing modes, one-hour cache creation, audio/image token details, web-search requests, and Google Maps grounding requests. Inconsistent totals and unpriced dimensions are rejected instead of silently applying standard text-token rates.
- Custom pricing URLs no longer reuse a cache populated from another source, raw source URLs and credentials are not persisted or exposed in fetch errors, cache writes are atomic and best-effort, and implausible future cache timestamps are rejected.
- `LLMCALC_CURRENCY` now applies only to custom pricing sources; it is a label override, not currency conversion.
- Both CLIs reject partial, non-ASCII and unsafe integer forms, accept `--option=value`, use the last duplicate option, and reject unknown options and stray arguments consistently.
- Cross-language parity now runs in a dedicated CI job after building the JavaScript CLI. A scheduled live-data job checks every current range-tier schedule, provider metadata, threshold, cache and input-only pricing surfaces.
- Package fallback versions and npm lockfile metadata now agree with version `0.2.1`.
- Python distributions now emit PEP 639 license metadata and the author URL; development installs include the backend required by the documented no-isolation build.
- Batch discounts now stack with long-context pricing, Gemini batch cache and modality rules follow the provider's published behavior, and mode-specific reasoning follows the selected output rate instead of retaining a standard-mode rate.

### Added
- Standard, batch, priority, flex, and fast processing-mode selection, including mode-specific long-context, cache, audio, and image rates. Provider-reported service tiers take precedence when calculating from a usage object.
- One-hour and audio cache-creation pricing, cached audio pricing, audio/image input and output token pricing, direct and result-tiered per-query pricing, selectable low/medium/high-context web-search pricing, Google Maps grounding pricing, US/EU data-residency uplifts, and Vertex non-global endpoint uplifts. Cost results expose each new component, the selected processing mode, and the regional multiplier.
- Completed-day LiteLLM repository snapshots through `snapshot_at` in Python, `snapshotAt` in JavaScript, and `--snapshot-at YYYY-MM-DD` in both CLIs. History begins on `2023-09-06`, uses the final root-file commit for the requested UTC day, and is cached by commit. Snapshot history represents data recorded in LiteLLM, not authoritative provider effective dates or invoice reconstruction.
- Structured pricing-parser diagnostics through `pricing_report()` / `pricing_report_async()` and `pricingReport()` / `pricingReportAsync()`. Diagnostics identify skipped entries and ignored fields with a severity, stable code, action, path, and message.
- `llmcalc pricing check [--strict] [--json]` for inspecting the complete parser report. Strict mode exits nonzero for warnings or errors after printing the report; informational exclusions remain allowed.

### Changed
- Library calculations use 50 significant digits; six-decimal rounding is limited to CLI serialization.
- Input-only token-priced models can be quoted when output tokens are zero.
- CI covers Python 3.11 through 3.14 and Node 20, 22, and 24 with GitHub Actions pinned to immutable commits.
- The Typer minimum is now `0.27.2`; the previous `0.12` floor is incompatible with current Click releases and could make every CLI command fail.
- The JavaScript package now builds with TypeScript 7 and declares Node's types explicitly.

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
