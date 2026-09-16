"""Resolve and cache immutable LiteLLM pricing snapshots by repository date."""

from __future__ import annotations

import gzip
import json
import re
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import httpx

from llmcalc.cache import cache_file_path
from llmcalc.config import get_user_agent
from llmcalc.errors import PricingHistoryError, PricingSchemaError

EARLIEST_SNAPSHOT_DATE = date(2023, 9, 6)
_COMMITS_URL = "https://api.github.com/repos/BerriAI/litellm/commits"
_RAW_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/"
    "{sha}/model_prices_and_context_window.json"
)
_PRICING_PATH = "model_prices_and_context_window.json"
_SHA = re.compile(r"[0-9a-f]{40}")


def validate_snapshot_at(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("snapshot_at must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("snapshot_at must use YYYY-MM-DD") from None
    today_utc = datetime.now(UTC).date()
    if parsed >= today_utc:
        raise ValueError("snapshot_at must be a completed UTC date")
    if parsed < EARLIEST_SNAPSHOT_DATE:
        raise PricingHistoryError("LiteLLM snapshot history starts at 2023-09-06")
    return value


def history_cache_dir() -> Path:
    return Path(f"{cache_file_path()}.history")


def _date_path(snapshot_at: str) -> Path:
    return history_cache_dir() / "dates" / f"{snapshot_at}.json"


def _snapshot_path(sha: str) -> Path:
    return history_cache_dir() / "snapshots" / f"{sha}.json.gz"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temp_file:
            temp_file.write(data)
            temporary = Path(temp_file.name)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load_sha(snapshot_at: str) -> str | None:
    try:
        payload = json.loads(_date_path(snapshot_at).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sha = payload.get("sha") if isinstance(payload, dict) else None
    return sha if isinstance(sha, str) and _SHA.fullmatch(sha) else None


def _save_sha(snapshot_at: str, sha: str) -> None:
    _atomic_write(
        _date_path(snapshot_at),
        json.dumps({"sha": sha}, separators=(",", ":")).encode("utf-8"),
    )


def _load_snapshot(sha: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(gzip.decompress(_snapshot_path(sha).read_bytes()))
    except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _save_snapshot(sha: str, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    _atomic_write(_snapshot_path(sha), gzip.compress(serialized))


async def _resolve_sha(snapshot_at: str, client: httpx.AsyncClient) -> str:
    cutoff = datetime.combine(
        date.fromisoformat(snapshot_at),
        time(23, 59, 59),
        tzinfo=UTC,
    )
    try:
        response = await client.get(
            _COMMITS_URL,
            params={
                "sha": "main",
                "path": _PRICING_PATH,
                "until": cutoff.isoformat().replace("+00:00", "Z"),
                "per_page": "1",
            },
        )
        response.raise_for_status()
        commits = response.json()
    except (httpx.HTTPError, ValueError):
        raise PricingHistoryError("failed to resolve LiteLLM pricing snapshot") from None
    if not isinstance(commits, list) or not commits or not isinstance(commits[0], dict):
        raise PricingHistoryError("no LiteLLM pricing snapshot exists for that date")
    commit = commits[0]
    sha = commit.get("sha")
    commit_data = commit.get("commit")
    committer = commit_data.get("committer") if isinstance(commit_data, Mapping) else None
    committed_at = committer.get("date") if isinstance(committer, Mapping) else None
    if not isinstance(sha, str) or _SHA.fullmatch(sha) is None:
        raise PricingHistoryError("GitHub returned an invalid pricing snapshot")
    if not isinstance(committed_at, str):
        raise PricingHistoryError("GitHub returned an invalid pricing snapshot")
    try:
        committed = datetime.fromisoformat(committed_at.replace("Z", "+00:00"))
    except ValueError:
        raise PricingHistoryError("GitHub returned an invalid pricing snapshot") from None
    if committed > cutoff:
        raise PricingHistoryError("GitHub returned a pricing snapshot after the requested date")
    return sha


async def _fetch_snapshot(sha: str, client: httpx.AsyncClient) -> dict[str, Any]:
    try:
        response = await client.get(_RAW_URL.format(sha=sha))
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise PricingHistoryError("failed to fetch LiteLLM pricing snapshot") from None
    if not isinstance(payload, dict):
        raise PricingSchemaError("pricing payload must be a JSON object")
    return payload


async def get_historical_pricing_payload(snapshot_at: str) -> dict[str, Any]:
    normalized = validate_snapshot_at(snapshot_at)
    sha = _load_sha(normalized)
    if sha is not None:
        cached = _load_snapshot(sha)
        if cached is not None:
            return cached

    async with httpx.AsyncClient(
        timeout=10,
        headers={"User-Agent": get_user_agent()},
    ) as client:
        if sha is None:
            sha = await _resolve_sha(normalized, client)
            with suppress(OSError):
                _save_sha(normalized, sha)
            cached = _load_snapshot(sha)
            if cached is not None:
                return cached
        payload = await _fetch_snapshot(sha, client)

    with suppress(OSError, TypeError, ValueError):
        _save_snapshot(sha, payload)
    return payload


def clear_history_cache() -> None:
    with suppress(FileNotFoundError):
        shutil.rmtree(history_cache_dir())
