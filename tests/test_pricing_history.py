import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from llmcalc import pricing_client, pricing_history
from llmcalc.errors import PricingHistoryError
from llmcalc.pricing_client import get_pricing_table

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "history_snapshots.json").read_text(
        encoding="utf-8"
    )
)


def test_snapshot_date_validation() -> None:
    assert pricing_history.validate_snapshot_at("2024-01-01") == "2024-01-01"
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        pricing_history.validate_snapshot_at("01-01-2024")
    with pytest.raises(PricingHistoryError, match="starts at"):
        pricing_history.validate_snapshot_at("2023-09-05")
    today = datetime.now(UTC).date()
    with pytest.raises(ValueError, match="completed UTC date"):
        pricing_history.validate_snapshot_at(today.isoformat())
    with pytest.raises(ValueError, match="completed UTC date"):
        pricing_history.validate_snapshot_at((today + timedelta(days=1)).isoformat())


class _Response:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise httpx.HTTPStatusError(
                "request failed",
                request=httpx.Request("GET", "https://example.test"),
                response=httpx.Response(self.status),
            )

    def json(self) -> object:
        return self.payload


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response

    async def get(self, *_args, **_kwargs) -> _Response:
        return self.response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "no LiteLLM pricing snapshot"),
        (
            [{"sha": "invalid", "commit": {"committer": {"date": "2024-01-01T00:00:00Z"}}}],
            "invalid pricing snapshot",
        ),
        (
            [{"sha": "a" * 40, "commit": {"committer": "invalid"}}],
            "invalid pricing snapshot",
        ),
        (
            [{"sha": "a" * 40, "commit": {"committer": {"date": "2024-01-02T00:00:00Z"}}}],
            "after the requested date",
        ),
    ],
)
async def test_commit_resolution_rejects_invalid_results(
    payload: object, message: str
) -> None:
    with pytest.raises(PricingHistoryError, match=message):
        await pricing_history._resolve_sha("2024-01-01", _Client(_Response(payload)))


@pytest.mark.asyncio
async def test_commit_resolution_reports_http_failure() -> None:
    with pytest.raises(PricingHistoryError, match="failed to resolve"):
        await pricing_history._resolve_sha("2024-01-01", _Client(_Response({}, 403)))


@pytest.mark.asyncio
async def test_historical_payload_is_cached_by_date_and_sha(
    monkeypatch, tmp_path: Path
) -> None:
    snapshot = FIXTURE["snapshots"][0]
    monkeypatch.setenv("LLMCALC_CACHE_PATH", str(tmp_path / "pricing.json"))
    calls = {"resolve": 0, "fetch": 0}

    async def resolve(snapshot_at: str, client: object) -> str:
        _ = client
        calls["resolve"] += 1
        assert snapshot_at == snapshot["snapshot_at"]
        return snapshot["sha"]

    async def fetch(sha: str, client: object) -> dict:
        _ = client
        calls["fetch"] += 1
        assert sha == snapshot["sha"]
        return snapshot["payload"]

    monkeypatch.setattr(pricing_history, "_resolve_sha", resolve)
    monkeypatch.setattr(pricing_history, "_fetch_snapshot", fetch)

    first = await pricing_history.get_historical_pricing_payload(snapshot["snapshot_at"])
    second = await pricing_history.get_historical_pricing_payload(snapshot["snapshot_at"])
    assert first == second == snapshot["payload"]
    assert calls == {"resolve": 1, "fetch": 1}


@pytest.mark.asyncio
async def test_get_pricing_table_uses_historical_payload(monkeypatch) -> None:
    snapshot = FIXTURE["snapshots"][1]

    async def historical(snapshot_at: str) -> dict:
        assert snapshot_at == snapshot["snapshot_at"]
        return snapshot["payload"]

    monkeypatch.setattr(pricing_client, "get_historical_pricing_payload", historical)
    table = await get_pricing_table(snapshot_at=snapshot["snapshot_at"])
    assert table["history-model"].input_cost_per_token is not None
    assert format(table["history-model"].input_cost_per_token, "f") == "0.03"


@pytest.mark.asyncio
async def test_snapshot_rejects_custom_pricing_source() -> None:
    with pytest.raises(ValueError, match="default LiteLLM"):
        await get_pricing_table(
            pricing_url="https://example.com/pricing.json",
            snapshot_at="2024-01-01",
        )
