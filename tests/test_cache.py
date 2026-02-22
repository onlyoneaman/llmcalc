import json
import time
from pathlib import Path

from llmcalc import cache


def _set_cache_path(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(cache, "cache_file_path", lambda: path)


def test_save_and_load_cache(tmp_path, monkeypatch) -> None:
    file_path = tmp_path / "pricing_cache.json"
    _set_cache_path(monkeypatch, file_path)

    data = {"gpt-5.1": {"input_cost_per_token": 0.1, "output_cost_per_token": 0.2}}
    cache.save_cached_pricing(data)

    loaded = cache.load_cached_pricing(max_age_seconds=3600)
    assert loaded == data


def test_load_cache_expired(tmp_path, monkeypatch) -> None:
    file_path = tmp_path / "pricing_cache.json"
    _set_cache_path(monkeypatch, file_path)

    payload = {
        "fetched_at": time.time() - 10,
        "data": {"gpt-5.1": {"input_cost_per_token": 1, "output_cost_per_token": 2}},
    }
    file_path.write_text(json.dumps(payload), encoding="utf-8")

    assert cache.load_cached_pricing(max_age_seconds=1) is None


def test_clear_cache(tmp_path, monkeypatch) -> None:
    file_path = tmp_path / "pricing_cache.json"
    _set_cache_path(monkeypatch, file_path)

    file_path.write_text("{}", encoding="utf-8")
    assert file_path.exists()

    cache.clear_cache()
    assert not file_path.exists()
