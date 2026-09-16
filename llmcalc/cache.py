"""Filesystem cache helpers for pricing payloads."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import time
from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir

CACHE_DIR_NAME = "llmcalc"
CACHE_FILE_NAME = "pricing_cache.json"
MAX_FUTURE_SKEW_SECONDS = 300


def _source_hash(source_url: str | None) -> str | None:
    if source_url is None:
        return None
    return sha256(source_url.encode("utf-8")).hexdigest()


def cache_file_path() -> Path:
    override = os.getenv("LLMCALC_CACHE_PATH")
    if override and override.strip():
        return Path(override)

    base_dir = Path(user_cache_dir(appname=CACHE_DIR_NAME, appauthor=CACHE_DIR_NAME))
    return base_dir / CACHE_FILE_NAME


def load_cached_pricing(
    max_age_seconds: int | None,
    source_url: str | None = None,
) -> dict[str, Any] | None:
    path = cache_file_path()
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None

    fetched_at = payload.get("fetched_at")
    data = payload.get("data")
    if (
        isinstance(fetched_at, bool)
        or not isinstance(fetched_at, (int, float))
        or not math.isfinite(fetched_at)
        or not isinstance(data, dict)
    ):
        return None
    if source_url is not None:
        stored_hash = payload.get("source_hash")
        legacy_source = payload.get("source_url")
        if stored_hash is not None and stored_hash != _source_hash(source_url):
            return None
        if stored_hash is None and legacy_source != source_url:
            return None

    now = time.time()
    if fetched_at > now + MAX_FUTURE_SKEW_SECONDS:
        return None
    if max_age_seconds is not None and now - fetched_at > max_age_seconds:
        return None

    return data


def save_cached_pricing(data: dict[str, Any], source_url: str | None = None) -> None:
    path = cache_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "fetched_at": time.time(),
        "source_hash": _source_hash(source_url),
        "data": data,
    }

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temp_file:
            json.dump(payload, temp_file, separators=(",", ":"))
            temp_path = Path(temp_file.name)
        temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def clear_cache() -> None:
    path = cache_file_path()
    with suppress(FileNotFoundError):
        path.unlink()
    with suppress(FileNotFoundError):
        shutil.rmtree(Path(f"{path}.history"))
