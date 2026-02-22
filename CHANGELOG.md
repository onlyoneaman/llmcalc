# Changelog

## Unreleased
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
