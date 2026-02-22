# Changelog

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
