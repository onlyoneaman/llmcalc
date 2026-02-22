"""Filesystem cache helpers for pricing payloads."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir

CACHE_DIR_NAME = "llmprice"
CACHE_FILE_NAME = "pricing_cache.json"


def cache_file_path() -> Path:
    base_dir = Path(user_cache_dir(appname=CACHE_DIR_NAME, appauthor=CACHE_DIR_NAME))
    return base_dir / CACHE_FILE_NAME


def load_cached_pricing(max_age_seconds: int) -> dict[str, Any] | None:
    path = cache_file_path()
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    fetched_at = payload.get("fetched_at")
    data = payload.get("data")
    if not isinstance(fetched_at, (int, float)) or not isinstance(data, dict):
        return None

    if time.time() - fetched_at > max_age_seconds:
        return None

    return data


def save_cached_pricing(data: dict[str, Any]) -> None:
    path = cache_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "fetched_at": time.time(),
        "data": data,
    }

    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def clear_cache() -> None:
    path = cache_file_path()
    if path.exists():
        path.unlink()
