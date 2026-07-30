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


def test_cache_path_env_override(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "custom_cache.json"
    monkeypatch.setenv("LLMCALC_CACHE_PATH", str(target))

    assert cache.cache_file_path() == target


def test_cache_path_falls_back_to_platform_dir(monkeypatch) -> None:
    monkeypatch.delenv("LLMCALC_CACHE_PATH", raising=False)

    assert cache.cache_file_path().name == "pricing_cache.json"


def test_round_trip_through_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLMCALC_CACHE_PATH", str(tmp_path / "nested" / "c.json"))

    cache.save_cached_pricing({"gpt-4o": {"input_cost_per_token": "0.0000025"}})

    assert cache.load_cached_pricing(3600) == {"gpt-4o": {"input_cost_per_token": "0.0000025"}}
