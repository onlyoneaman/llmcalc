"""Cross-language parity: both CLIs must agree, byte for byte.

Both read one seeded cache file, so this runs offline and deterministically.
A divergence between the packages fails here instead of shipping as two
different prices for the same call.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llmcalc.cli import app

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_CLI = REPO_ROOT / "js" / "dist" / "cli.js"

# Pricing covering both tier families, an asymmetric threshold, and an
# untiered control.
SEED_DATA = {
    "gpt-5.5": {
        "input_cost_per_token": "0.000005",
        "output_cost_per_token": "0.00003",
        "input_cost_per_token_above_272k_tokens": "0.00001",
        "output_cost_per_token_above_272k_tokens": "0.000045",
        "currency": "USD",
    },
    "gpt-4o": {
        "input_cost_per_token": "0.0000025",
        "output_cost_per_token": "0.00001",
        "currency": "USD",
    },
    "dashscope/qwen-flash": {
        "tiered_pricing": [
            {
                "range": [0, 256000],
                "input_cost_per_token": "0.00000005",
                "output_cost_per_token": "0.0000004",
            },
            {
                "range": [256000, 1000000],
                "input_cost_per_token": "0.00000025",
                "output_cost_per_token": "0.000002",
            },
        ],
        "currency": "USD",
    },
    "gemini/gemini-1.5-flash": {
        "input_cost_per_token": "0.000000075",
        "output_cost_per_token": "0",
        "input_cost_per_token_above_128k_tokens": "0.00000015",
        "currency": "USD",
    },
}

QUOTE_CASES = [
    ("gpt-5.5", 300_000, 5_000),
    ("gpt-5.5", 272_000, 1_000),
    ("gpt-5.5", 272_001, 1_000),
    ("gpt-5.5", 100_000, 5_000),
    ("gpt-4o", 1_000, 500),
    ("dashscope/qwen-flash", 300_000, 1_000),
    ("dashscope/qwen-flash", 1, 0),
    ("dashscope/qwen-flash", 1_200_000, 0),
    ("gemini/gemini-1.5-flash", 200_000, 1_000),
    ("gemini/gemini-1.5-flash", 100_000, 1_000),
]

MODEL_CASES = ["gpt-5.5", "gpt-4o", "dashscope/qwen-flash", "gemini/gemini-1.5-flash"]

requires_js = pytest.mark.skipif(
    shutil.which("node") is None or not JS_CLI.exists(),
    reason="needs node and `cd js && npm run build`",
)


@pytest.fixture
def seeded_cache(tmp_path: Path, monkeypatch) -> Path:
    cache_path = tmp_path / "pricing_cache.json"
    cache_path.write_text(
        json.dumps({"fetched_at": time.time(), "data": SEED_DATA}), encoding="utf-8"
    )
    monkeypatch.setenv("LLMCALC_CACHE_PATH", str(cache_path))
    return cache_path


def _run_both(args: list[str], seeded_cache: Path) -> tuple[dict, dict]:
    python_result = CliRunner().invoke(app, args)
    assert python_result.exit_code == 0, python_result.stdout

    js_result = subprocess.run(
        [shutil.which("node") or "node", str(JS_CLI), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "LLMCALC_CACHE_PATH": str(seeded_cache)},
    )
    assert js_result.returncode == 0, js_result.stderr

    return json.loads(python_result.stdout), json.loads(js_result.stdout)


@requires_js
@pytest.mark.parametrize("model,input_tokens,output_tokens", QUOTE_CASES)
def test_cli_quote_is_identical_across_languages(
    seeded_cache: Path, model: str, input_tokens: int, output_tokens: int
) -> None:
    args = [
        "quote",
        "--model",
        model,
        "--input",
        str(input_tokens),
        "--output",
        str(output_tokens),
        "--json",
    ]
    python_payload, js_payload = _run_both(args, seeded_cache)
    assert python_payload == js_payload


@requires_js
@pytest.mark.parametrize("model", MODEL_CASES)
def test_cli_model_is_identical_across_languages(seeded_cache: Path, model: str) -> None:
    # Covers Decimal serialization: str(Decimal) gives '7.5E-8' where JS
    # toString() gives '7.5e-8'. Both must emit plain decimal notation.
    python_payload, js_payload = _run_both(["model", "--model", model, "--json"], seeded_cache)
    assert python_payload == js_payload
