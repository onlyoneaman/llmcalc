# AGENTS.md

## Project
- Name: `llmcalc`
- Purpose: Calculate LLM token costs from `litellm` pricing data.
- Runtime:
  - Python `>=3.11` (PyPI package)
  - Node `>=20` (npm package in `js/`)

## Cross-Language Parity
- The Python package (`llmcalc`) and JavaScript package (`js/`) must maintain feature parity.
- Any user-facing behavior change in one implementation must be mirrored in the other in the same PR when feasible.
- If exact parity cannot ship together, explicitly document the gap in `CHANGELOG.md` with follow-up scope.
- Parity includes:
  - Public API surface and semantics (cost/model/usage helpers, cache clear behavior).
  - CLI commands and flags (`quote`, `model`, `cache clear`, `--version`, `-v`).
  - Default config and env vars (`LLMCALC_CACHE_TIMEOUT`, `LLMCALC_PRICING_URL`, `LLMCALC_CURRENCY`, `LLMCALC_CACHE_PATH`).
  - Pricing normalization/alias behavior and deterministic rounding expectations.
  - Error behavior for invalid input and missing models.
  - Serialized output: both CLIs must emit identical JSON, including `null` vs `""` and plain-vs-scientific decimal notation.
- Parity is mechanically enforced, not just aspirational:
  - `tests/fixtures/tiered_cases.json` is the shared contract. Both suites read it and assert identical costs. Add a case there *before* adding pricing behavior to either package.
  - `tests/test_parity.py` diffs both CLIs' JSON output for the same arguments. It runs offline via a seeded cache and needs `cd js && npm run build` first.
- Known cross-language traps, each of which has already shipped as a bug:
  - JS `split(sep, n)` limits *returned elements* and discards the rest; Python's `split(sep, n)` limits *splits* and keeps the remainder. Use an explicit split-once helper.
  - `str(Decimal)` gives `7.5E-8` where decimal.js `toString()` gives `7.5e-8`. Use `format(value, "f")` and `.toFixed()` for plain notation.
  - Python `bool` subclasses `int`, so `isinstance(True, int)` passes. Use `type(v) is int` for token counts.

## Code Style
- Keep modules small and composable.
- Centralize defaults/env parsing in `llmcalc/config.py`.
- Prefer pure helpers for deterministic logic (normalization, math, parsing).
- Keep public API typed and stable.
- Mirror equivalent module boundaries in `js/src/` when adding new capabilities.

## Local Commands
- Dev env:
  - Create: `python -m venv .venv`
  - Activate (macOS/Linux): `source .venv/bin/activate`
- Install: `pip install -e '.[dev]'`
- Lint: `python -m ruff check .`
- Type check: `python -m mypy llmcalc`
- Test: `python -m pytest`
- Build: `python -m build --no-isolation`
- Dist check: `python -m twine check dist/*`
- JS install: `cd js && npm ci`
- JS lint/typecheck: `cd js && npm run lint`
- JS test: `cd js && npm run test`
- JS pack check: `cd js && npm pack --dry-run`

## CLI Expectations
- Root command: `llmcalc`
- Version flags: `llmcalc --version` and `llmcalc -v`
- Cache defaults:
  - Default TTL: `43200` seconds
  - Env override: `LLMCALC_CACHE_TIMEOUT`
- JS CLI (`cd js`): same command semantics and flags under `llmcalc` when installed from npm.

## Release Checklist
1. Run Python lint, mypy, and tests.
2. Run JS lint/typecheck and tests.
3. Build Python distributions and run `twine check`.
4. Run JS package dry run (`npm pack --dry-run`).
5. Confirm parity notes for any API/CLI/config changes.
6. Update `CHANGELOG.md`.
7. Publish to PyPI and npm.
