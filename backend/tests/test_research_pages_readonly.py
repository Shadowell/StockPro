from __future__ import annotations

from test_market_current_api import FakeMarketRepository, _client


def test_research_gets_never_write_or_call_provider() -> None:
    repository = FakeMarketRepository()
    client = _client(repository)

    for path in (
        "/api/market/overview",
        "/api/market/instruments?q=&limit=10",
        "/api/market/instruments/600519.SH",
    ):
        client.get(path)

    assert repository.executed_writes == []
    assert repository.provider_calls == []
