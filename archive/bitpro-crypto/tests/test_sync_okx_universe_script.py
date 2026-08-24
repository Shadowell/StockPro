from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "sync_okx_universe.py"

spec = importlib.util.spec_from_file_location("sync_okx_universe", SCRIPT_PATH)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)


def test_select_supported_usdt_symbols_keeps_only_active_usdt_swaps() -> None:
    markets = [
        {"symbol": "BTC/USDT", "active": True, "spot": True, "quote": "USDT"},
        {"symbol": "BTC/USDT:USDT", "active": True, "swap": True, "quote": "USDT", "settle": "USDT"},
        {"symbol": "OPENAI/USDT:USDT", "active": None, "swap": True, "quote": "USDT", "settle": "USDT"},
        {"symbol": "ETH/USDC", "active": True, "spot": True, "quote": "USDC"},
        {"symbol": "DOGE/USDT:USDC", "active": True, "swap": True, "quote": "USDT", "settle": "USDC"},
        {"symbol": "SOL/USDT", "active": False, "spot": True, "quote": "USDT"},
        {"symbol": "XRP/USDT:USDT", "active": True, "future": True, "quote": "USDT", "settle": "USDT"},
    ]

    assert module.select_supported_usdt_symbols(markets) == [
        "BTC/USDT:USDT",
        "OPENAI/USDT:USDT",
    ]


def test_normalize_timeframe_sequence_preserves_required_sync_order() -> None:
    requested = ["15m", "1d", "1m", "4h", "30m", "1h", "1d", "5m"]

    assert module.normalize_timeframe_sequence(requested) == [
        "1d",
        "4h",
        "1h",
        "30m",
        "15m",
    ]


def test_full_sync_defaults_to_contract_timeframes_and_ninety_days() -> None:
    assert module.FULL_SYNC_TIMEFRAME_ORDER == ["1d", "12h", "4h", "1h", "30m", "15m"]
    assert module.DEFAULT_HISTORY_DAYS == 90


def test_thread_exchange_force_reloads_complete_okx_market_catalog(monkeypatch) -> None:
    calls = []

    class FakeOKXExchange:
        def __init__(self, config) -> None:
            calls.append(("config", config))

        def initialize(self) -> None:
            calls.append("initialize")

        def load_markets(self, force: bool = False) -> None:
            calls.append(("load_markets", force))

    monkeypatch.setattr(module, "_backend", lambda: {"OKXExchange": FakeOKXExchange})
    if hasattr(module._THREAD_STATE, "okx_exchange"):
        delattr(module._THREAD_STATE, "okx_exchange")

    module._get_thread_exchange()

    assert calls == [
        ("config", {"testnet": False}),
        "initialize",
        ("load_markets", True),
    ]


def test_explicit_window_repair_ignores_newer_metadata_checkpoint(monkeypatch) -> None:
    requested_start = module._sync_start_date_ms("2026-05-01")
    requested_end = module._sync_end_date_ms("2026-05-02")
    seen: list[int] = []

    class FakeDb:
        def get_sync_metadata(self, *args):
            return {"last_timestamp": requested_end + 86_400_000}

        def update_sync_metadata(self, *args, **kwargs):
            return None

    class FakeStore:
        def get_stats(self, *args):
            return {"record_count": 0}

    class FakeExchange:
        def fetch_ohlcv(self, symbol, timeframe, limit, since):
            seen.append(since)
            return []

    monkeypatch.setattr(module, "_get_thread_exchange", lambda: FakeExchange())
    monkeypatch.setattr(module, "_backend", lambda: {
        "db": FakeDb(),
        "kline_store": FakeStore(),
        "TIMEFRAME_MS": {"1h": 3_600_000},
        "MAX_KLINES_PER_REQUEST": 300,
        "MAX_CONSECUTIVE_ERRORS": 5,
        "API_REQUEST_DELAY": 0,
        "SyncStatus": type("Status", (), {"COMPLETED": type("Value", (), {"value": "completed"}), "ERROR": type("Value", (), {"value": "error"})}),
    })

    result = module.sync_symbol_timeframe(
        exchange_name="okx",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        start_date="2026-05-01",
        end_date="2026-05-02",
    )

    assert seen == [requested_start]
    assert result["status"] == "error"
    assert "未返回 K 线" in (result["error"] or "")


def test_sparse_contract_sync_starts_at_listing_and_continues_after_short_batches(monkeypatch) -> None:
    requested_start = module._sync_start_date_ms("2026-05-01")
    listing_ms = requested_start + 10 * 3_600_000
    seen: list[int] = []
    stored_rows: list[dict] = []

    class FakeCcxt:
        @staticmethod
        def market(symbol):
            return {"created": listing_ms, "info": {"listTime": str(listing_ms)}}

    class FakeExchange:
        exchange = FakeCcxt()

        def fetch_ohlcv(self, symbol, timeframe, limit, since):
            seen.append(since)
            if since == listing_ms:
                return [
                    {"timestamp": listing_ms, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
                    {"timestamp": listing_ms + 3_600_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
                ]
            if since == listing_ms + 2 * 3_600_000:
                return [
                    {"timestamp": listing_ms + 2 * 3_600_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
                ]
            return []

    class FakeDb:
        def update_sync_metadata(self, *args, **kwargs):
            return None

    class FakeStore:
        def append_klines(self, exchange, symbol, timeframe, rows):
            stored_rows.extend(rows)
            return len(rows)

        def get_stats(self, *args):
            return {"record_count": len(stored_rows)}

    monkeypatch.setattr(module, "_get_thread_exchange", lambda: FakeExchange())
    monkeypatch.setattr(module, "_backend", lambda: {
        "db": FakeDb(),
        "kline_store": FakeStore(),
        "TIMEFRAME_MS": {"1h": 3_600_000},
        "MAX_KLINES_PER_REQUEST": 300,
        "MAX_CONSECUTIVE_ERRORS": 5,
        "API_REQUEST_DELAY": 0,
        "SyncStatus": type("Status", (), {"COMPLETED": type("Value", (), {"value": "completed"}), "ERROR": type("Value", (), {"value": "error"})}),
    })

    result = module.sync_symbol_timeframe(
        exchange_name="okx",
        symbol="ADBE/USDT:USDT",
        timeframe="1h",
        start_date="2026-05-01",
        end_date="2026-05-01",
    )

    assert seen == [listing_ms, listing_ms + 2 * 3_600_000, listing_ms + 3 * 3_600_000]
    assert result["status"] == "completed"
    assert result["fetched"] == 3
