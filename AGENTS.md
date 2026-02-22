# AGENTS.md

## Project
- Name: `llmcalc`
- Purpose: Calculate LLM token costs from `llmlite` pricing data.
- Runtime: Python `>=3.11`.

## Code Style
- Keep modules small and composable.
- Centralize defaults/env parsing in `llmcalc/config.py`.
- Prefer pure helpers for deterministic logic (normalization, math, parsing).
- Keep public API typed and stable.

## Local Commands
- Install: `pip install -e '.[dev]'`
- Lint: `python -m ruff check .`
- Type check: `python -m mypy llmcalc`
- Test: `python -m pytest`
- Build: `python -m build --no-isolation`
- Dist check: `python -m twine check dist/*`

## CLI Expectations
- Root command: `llmcalc`
- Version flags: `llmcalc --version` and `llmcalc -v`
- Cache defaults:
  - Default TTL: `43200` seconds
  - Env override: `LLMCALC_CACHE_TIMEOUT`

## Release Checklist
1. Run lint, mypy, and tests.
2. Build distributions.
3. Run `twine check`.
4. Update `CHANGELOG.md`.
5. Publish to PyPI.
