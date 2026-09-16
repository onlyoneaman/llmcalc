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
    assert cache.load_cached_pricing(max_age_seconds=None) == payload["data"]


def test_cache_source_must_match(tmp_path, monkeypatch) -> None:
    file_path = tmp_path / "pricing_cache.json"
    _set_cache_path(monkeypatch, file_path)

    data = {"gpt-5.1": {"input_cost_per_token": 1, "output_cost_per_token": 2}}
    cache.save_cached_pricing(data, source_url="https://example.com/a.json")

    assert cache.load_cached_pricing(3600, source_url="https://example.com/a.json") == data
    assert cache.load_cached_pricing(3600, source_url="https://example.com/b.json") is None
    serialized = file_path.read_text(encoding="utf-8")
    assert "https://example.com/a.json" not in serialized
    assert "source_hash" in json.loads(serialized)


def test_non_finite_cache_timestamp_is_rejected(tmp_path, monkeypatch) -> None:
    file_path = tmp_path / "pricing_cache.json"
    _set_cache_path(monkeypatch, file_path)
    data = {"gpt-5.1": {"input_cost_per_token": 1}}

    for fetched_at in (float("nan"), float("inf"), float("-inf")):
        file_path.write_text(
            json.dumps({"fetched_at": fetched_at, "data": data}),
            encoding="utf-8",
        )
        assert cache.load_cached_pricing(3600) is None


def test_far_future_cache_timestamp_is_rejected(tmp_path, monkeypatch) -> None:
    file_path = tmp_path / "pricing_cache.json"
    _set_cache_path(monkeypatch, file_path)
    file_path.write_text(
        json.dumps({"fetched_at": time.time() + 3600, "data": {"model": {}}}),
        encoding="utf-8",
    )
    assert cache.load_cached_pricing(3600) is None


def test_non_object_cache_payload_is_rejected(tmp_path, monkeypatch) -> None:
    file_path = tmp_path / "pricing_cache.json"
    _set_cache_path(monkeypatch, file_path)

    for payload in ([], None, "cache", 1):
        file_path.write_text(json.dumps(payload), encoding="utf-8")
        assert cache.load_cached_pricing(3600) is None


def test_clear_cache(tmp_path, monkeypatch) -> None:
    file_path = tmp_path / "pricing_cache.json"
    _set_cache_path(monkeypatch, file_path)

    file_path.write_text("{}", encoding="utf-8")
    history_file = Path(f"{file_path}.history") / "snapshots" / "snapshot.json.gz"
    history_file.parent.mkdir(parents=True)
    history_file.write_bytes(b"snapshot")
    assert file_path.exists()
    assert history_file.exists()

    cache.clear_cache()
    assert not file_path.exists()
    assert not Path(f"{file_path}.history").exists()


def test_cache_path_env_override(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "custom_cache.json"
    monkeypatch.setenv("LLMCALC_CACHE_PATH", str(target))

    assert cache.cache_file_path() == target


def test_cache_path_falls_back_to_platform_dir(monkeypatch) -> None:
    monkeypatch.delenv("LLMCALC_CACHE_PATH", raising=False)

    assert cache.cache_file_path().name == "pricing_cache.json"


def test_whitespace_cache_path_falls_back_to_platform_dir(monkeypatch) -> None:
    monkeypatch.setenv("LLMCALC_CACHE_PATH", "   ")

    assert cache.cache_file_path().name == "pricing_cache.json"
    assert cache.cache_file_path() != Path("   ")


def test_round_trip_through_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLMCALC_CACHE_PATH", str(tmp_path / "nested" / "c.json"))

    cache.save_cached_pricing({"gpt-4o": {"input_cost_per_token": "0.0000025"}})

    assert cache.load_cached_pricing(3600) == {"gpt-4o": {"input_cost_per_token": "0.0000025"}}
