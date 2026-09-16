"""Cross-language parity: both CLIs must agree, byte for byte.

Both read one seeded cache file, so this runs offline and deterministically.
A divergence between the packages fails here instead of shipping as two
different prices for the same call.
"""

import gzip
import json
import shutil
import subprocess
import time
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llmcalc.cli import app
from llmcalc.config import DEFAULT_PRICING_URL

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_CLI = REPO_ROOT / "js" / "dist" / "cli.js"
DIMENSIONS_FIXTURE = json.loads(
    (REPO_ROOT / "tests" / "fixtures" / "pricing_dimensions.json").read_text(
        encoding="utf-8"
    )
)
HISTORY_FIXTURE = json.loads(
    (REPO_ROOT / "tests" / "fixtures" / "history_snapshots.json").read_text(
        encoding="utf-8"
    )
)

# Pricing covering both tier families, an asymmetric threshold, and an
# untiered control.
SEED_DATA = {
    "gpt-5.5": {
        "input_cost_per_token": "0.000005",
        "output_cost_per_token": "0.00003",
        "input_cost_per_token_above_272k_tokens": "0.00001",
        "output_cost_per_token_above_272k_tokens": "0.000045",
        "cache_read_input_token_cost": "0.0000005",
        "cache_read_input_token_cost_above_272k_tokens": "0.000001",
        "output_cost_per_reasoning_token": "0.00006",
        "currency": "USD",
    },
    "gpt-4o": {
        "input_cost_per_token": "0.0000025",
        "output_cost_per_token": "0.00001",
        "currency": "USD",
    },
    "precision-model": {
        "input_cost_per_token": "0.12345678901234567890123456789",
        "output_cost_per_token": "0",
        "currency": "USD",
    },
    "rounding-tie-model": {
        "input_cost_per_token": "0." + "1" * 49 + "25",
        "output_cost_per_token": "0",
        "currency": "USD",
    },
    "per-million-precision-model": {
        "input_cost_per_million_tokens": "0.123456789012345678901234567890123456789",
        "output_cost_per_million_tokens": "0.987654321098765432109876543210987654321",
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
    "claude-sonnet": {
        "input_cost_per_token": "0.000003",
        "output_cost_per_token": "0.000015",
        "cache_read_input_token_cost": "0.0000003",
        "cache_creation_input_token_cost": "0.00000375",
        "currency": "USD",
    },
    "dimension-model": DIMENSIONS_FIXTURE["pricing"],
    "query-dimension-model": {
        "tiered_pricing": [
            {"input_cost_per_query": "0.005", "max_results_range": [0, 25]},
            {"input_cost_per_query": "0.025", "max_results_range": [26, 100]},
        ],
        "currency": "USD",
    },
    "diagnostic-model": {
        "input_cost_per_token": "0.01",
        "input_cost_per_token_above_1k_tokens": "bad",
    },
}

QUOTE_CASES = [
    ("gpt-5.5", 300_000, 5_000),
    ("gpt-5.5", 272_000, 1_000),
    ("gpt-5.5", 272_001, 1_000),
    ("gpt-5.5", 100_000, 5_000),
    ("gpt-4o", 1_000, 500),
    ("precision-model", 9_007_199_254_740_991, 0),
    ("rounding-tie-model", 1, 0),
    ("dashscope/qwen-flash", 300_000, 1_000),
    ("dashscope/qwen-flash", 1, 0),
    ("dashscope/qwen-flash", 1_200_000, 0),
    ("gemini/gemini-1.5-flash", 200_000, 1_000),
    ("gemini/gemini-1.5-flash", 100_000, 1_000),
]

MODEL_CASES = [
    "gpt-5.5",
    "gpt-4o",
    "dashscope/qwen-flash",
    "gemini/gemini-1.5-flash",
    "per-million-precision-model",
    "dimension-model",
    "query-dimension-model",
]

# (model, input, output, cached, cache_creation, reasoning)
CACHE_CASES = [
    ("gpt-5.5", 100_000, 1_000, 90_000, 0, 0),
    ("gpt-5.5", 300_000, 1_000, 100_000, 0, 0),
    ("gpt-5.5", 1_000, 5_000, 0, 0, 4_000),
    ("claude-sonnet", 100_000, 500, 90_000, 2_000, 0),
    ("gpt-4o", 1_000, 500, 0, 0, 0),
    ("dashscope/qwen-flash", 50_000, 1_000, 20_000, 0, 0),
]

requires_js = pytest.mark.skipif(
    shutil.which("node") is None or not JS_CLI.exists(),
    reason="needs node and `cd js && npm run build`",
)


@pytest.fixture
def seeded_cache(tmp_path: Path, monkeypatch) -> Path:
    cache_path = tmp_path / "pricing_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": time.time(),
                "source_hash": sha256(DEFAULT_PRICING_URL.encode("utf-8")).hexdigest(),
                "data": SEED_DATA,
            }
        ),
        encoding="utf-8",
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


def _run_both_for_status(args: list[str], seeded_cache: Path) -> tuple[int, int]:
    python_result = CliRunner().invoke(app, args)
    js_result = subprocess.run(
        [shutil.which("node") or "node", str(JS_CLI), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "LLMCALC_CACHE_PATH": str(seeded_cache)},
    )
    return python_result.exit_code, js_result.returncode


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
def test_cli_equals_option_syntax_is_identical(seeded_cache: Path) -> None:
    python_payload, js_payload = _run_both(
        ["quote", "--model=gpt-4o", "--input=1000", "--output=500", "--json"],
        seeded_cache,
    )
    assert python_payload == js_payload


@requires_js
def test_cli_pricing_dimensions_are_identical(seeded_cache: Path) -> None:
    python_payload, js_payload = _run_both(
        [
            "quote",
            "--model",
            "dimension-model",
            "--input",
            "100",
            "--output",
            "50",
            "--processing-mode",
            "priority",
            "--cache-creation",
            "20",
            "--cache-creation-1h",
            "5",
            "--cache-creation-audio",
            "5",
            "--input-audio",
            "10",
            "--output-image",
            "5",
            "--queries",
            "2",
            "--web-searches",
            "3",
            "--web-search-context",
            "high",
            "--maps-grounding",
            "1",
            "--region",
            "us",
            "--json",
        ],
        seeded_cache,
    )
    assert python_payload == js_payload


@requires_js
def test_cli_query_result_tiers_are_identical(seeded_cache: Path) -> None:
    python_payload, js_payload = _run_both(
        [
            "quote",
            "--model",
            "query-dimension-model",
            "--input",
            "0",
            "--output",
            "0",
            "--queries",
            "2",
            "--query-results",
            "26",
            "--json",
        ],
        seeded_cache,
    )
    assert python_payload == js_payload


@requires_js
def test_cli_pricing_diagnostics_are_identical(seeded_cache: Path) -> None:
    python_payload, js_payload = _run_both(
        ["pricing", "check", "--json"],
        seeded_cache,
    )
    assert python_payload == js_payload
    assert python_payload["diagnostic_count"] == 1
    assert python_payload["diagnostics"][0]["code"] == "invalid_threshold_rate"


@requires_js
def test_cli_snapshot_history_is_identical(seeded_cache: Path) -> None:
    snapshot = HISTORY_FIXTURE["snapshots"][0]
    history_root = Path(f"{seeded_cache}.history")
    date_dir = history_root / "dates"
    snapshot_dir = history_root / "snapshots"
    date_dir.mkdir(parents=True)
    snapshot_dir.mkdir(parents=True)
    (date_dir / f"{snapshot['snapshot_at']}.json").write_text(
        json.dumps({"sha": snapshot["sha"]}),
        encoding="utf-8",
    )
    (snapshot_dir / f"{snapshot['sha']}.json.gz").write_bytes(
        gzip.compress(json.dumps(snapshot["payload"]).encode("utf-8"))
    )

    python_payload, js_payload = _run_both(
        [
            "quote",
            "--model",
            "history-model",
            "--input",
            "100",
            "--output",
            "50",
            "--snapshot-at",
            snapshot["snapshot_at"],
            "--json",
        ],
        seeded_cache,
    )
    assert python_payload == js_payload


@requires_js
@pytest.mark.parametrize(
    "args",
    [
        ["quote", "--model", "gpt-4o", "--input", "1.5", "--output", "0"],
        ["quote", "--model", "gpt-4o", "--input", "1_000", "--output", "0"],
        ["quote", "--model", "gpt-4o", "--input", "١٠٠٠", "--output", "0"],
        ["quote", "--model", "gpt-4o", "--input", str(2**53), "--output", "0"],
        ["quote", "--model", "gpt-4o", "--input", "1", "--output", "0", "-v"],
        ["cache", "clear", "junk"],
    ],
)
def test_cli_invalid_input_fails_in_both_languages(
    seeded_cache: Path, args: list[str]
) -> None:
    python_status, js_status = _run_both_for_status(args, seeded_cache)
    assert python_status != 0
    assert js_status != 0


@requires_js
@pytest.mark.parametrize("model", MODEL_CASES)
def test_cli_model_is_identical_across_languages(seeded_cache: Path, model: str) -> None:
    # Covers Decimal serialization: str(Decimal) gives '7.5E-8' where JS
    # toString() gives '7.5e-8'. Both must emit plain decimal notation.
    python_payload, js_payload = _run_both(["model", "--model", model, "--json"], seeded_cache)
    assert python_payload == js_payload


@requires_js
@pytest.mark.parametrize(
    "model,input_tokens,output_tokens,cached,creation,reasoning", CACHE_CASES
)
def test_cli_quote_with_cache_and_reasoning_is_identical(
    seeded_cache: Path,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached: int,
    creation: int,
    reasoning: int,
) -> None:
    args = [
        "quote",
        "--model",
        model,
        "--input",
        str(input_tokens),
        "--output",
        str(output_tokens),
        "--cached",
        str(cached),
        "--cache-creation",
        str(creation),
        "--reasoning",
        str(reasoning),
        "--json",
    ]
    python_payload, js_payload = _run_both(args, seeded_cache)
    assert python_payload == js_payload

    # The whole point: the total must equal the sum of its legs.
    assert Decimal(python_payload["input_cost"]) + Decimal(
        python_payload["output_cost"]
    ) == Decimal(python_payload["total_cost"])
