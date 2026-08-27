from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.instruments.provider import TushareAshareProvider  # noqa: E402
from app.domain.instruments.scheduler import AshareDailySyncScheduler  # noqa: E402
from app.domain.instruments.service import AshareInstrumentSyncService  # noqa: E402
from app.api.v2.endpoints import market as market_endpoint  # noqa: E402
from app.api.v2.endpoints import sync as sync_endpoint  # noqa: E402
from app import main as main_module  # noqa: E402


class FakeProvider:
    def fetch_instruments(self):
        return [
            {
                "ts_code": "600519.SH",
                "symbol": "600519",
                "name": "贵州茅台",
                "industry": "白酒",
                "market": "主板",
                "exchange": "SSE",
                "list_status": "L",
                "list_date": "20010827",
                "delist_date": None,
                "is_hs": "H",
            },
            {
                "ts_code": "000001.SZ",
                "symbol": "000001",
                "name": "平安银行",
                "industry": "银行",
                "market": "主板",
                "exchange": "SZSE",
                "list_status": "L",
                "list_date": "19910403",
                "delist_date": None,
                "is_hs": "S",
            },
            {
                "ts_code": "T600018.SH",
                "symbol": "600018",
                "name": "上港集箱（退）",
                "industry": "港口",
                "market": "主板",
                "exchange": "SSE",
                "list_status": "D",
                "list_date": "20000719",
                "delist_date": "20061009",
                "is_hs": None,
            },
        ]

    def latest_open_trade_date(self):
        return "20260826"

    def fetch_daily(self, trade_date: str):
        assert trade_date == "20260826"
        return [
            {
                "ts_code": "600519.SH",
                "trade_date": trade_date,
                "open": 1500.0,
                "high": 1520.0,
                "low": 1490.0,
                "close": 1510.0,
                "pct_chg": 1.25,
                "vol": 123.0,
                "amount": 18600.0,
            }
        ]

    def fetch_daily_basic(self, trade_date: str):
        assert trade_date == "20260826"
        return [
            {
                "ts_code": "600519.SH",
                "trade_date": trade_date,
                "close": 1510.0,
                "turnover_rate": 0.42,
                "turnover_rate_f": 0.43,
                "volume_ratio": 1.1,
                "pe": 24.5,
                "pe_ttm": 24.0,
                "pb": 7.8,
                "ps": 12.0,
                "ps_ttm": 11.8,
                "dv_ratio": 1.2,
                "dv_ttm": 1.1,
                "total_mv": 1_900_000_000.0,
                "circ_mv": 1_900_000_000.0,
                "limit_status": 0,
            }
        ]

    def fetch_trade_calendar(self, start_date: str, end_date: str):
        assert start_date == "20260826"
        assert end_date == "20260826"
        return [{"exchange": "SSE", "cal_date": "20260826", "is_open": 1, "pretrade_date": "20260825"}]

    def fetch_adj_factor(self, trade_date: str):
        assert trade_date == "20260826"
        return [{"ts_code": "600519.SH", "trade_date": trade_date, "adj_factor": 12.3}]

    def fetch_suspensions(self, trade_date: str):
        assert trade_date == "20260826"
        return []

    def fetch_price_limits(self, trade_date: str):
        assert trade_date == "20260826"
        return [{"ts_code": "600519.SH", "trade_date": trade_date, "pre_close": 1491.36, "up_limit": 1640.5, "down_limit": 1342.22}]

    def fetch_corporate_actions(self, trade_date: str):
        assert trade_date == "20260826"
        return []

    def fetch_benchmark_bars(self, trade_date: str):
        assert trade_date == "20260826"
        return [
            {"ts_code": "000001.SH", "trade_date": trade_date, "open": 3000.0, "high": 3020.0, "low": 2990.0, "close": 3010.0},
            {"ts_code": "399001.SZ", "trade_date": trade_date, "open": 10000.0, "high": 10100.0, "low": 9900.0, "close": 10080.0},
            {"ts_code": "399006.SZ", "trade_date": trade_date, "open": 2000.0, "high": 2040.0, "low": 1980.0, "close": 2030.0},
            {"ts_code": "000300.SH", "trade_date": trade_date, "open": 3600.0, "high": 3650.0, "low": 3580.0, "close": 3630.0},
        ]


class FakeRepository:
    def __init__(self, run_id=17):
        self.run_id = run_id
        self.completed = None
        self.failed = None

    def begin_run(self, trigger: str):
        self.trigger = trigger
        return self.run_id

    def complete_run(self, run_id, instruments, daily_rows, trade_date, *, auxiliary_datasets=None):
        self.completed = {
            "run_id": run_id,
            "instruments": instruments,
            "daily_rows": daily_rows,
            "trade_date": trade_date,
            "auxiliary_datasets": auxiliary_datasets or {},
        }
        return {
            "run_id": run_id,
            "status": "success",
            "instrument_count": len(instruments),
            "daily_count": len(daily_rows),
            "trade_date": trade_date,
        }

    def fail_run(self, run_id, error):
        self.failed = (run_id, str(error))


def test_full_a_share_sync_persists_names_and_daily_rows_atomically():
    repository = FakeRepository()
    result = AshareInstrumentSyncService(repository=repository, provider=FakeProvider()).sync_all(trigger="manual")

    assert result == {
        "run_id": 17,
        "status": "success",
        "instrument_count": 3,
        "daily_count": 1,
        "trade_date": "2026-08-26",
    }
    assert repository.trigger == "manual"
    assert repository.failed is None
    maotai = next(item for item in repository.completed["instruments"] if item["symbol"] == "600519.SH")
    assert maotai["name"] == "贵州茅台"
    retired = next(item for item in repository.completed["instruments"] if item["symbol"] == "T600018.SH")
    assert retired["list_status"] == "D"
    assert repository.completed["daily_rows"][0]["storage_symbol"] == "SH_600519"
    assert repository.completed["daily_rows"][0]["name"] == "贵州茅台"
    assert repository.completed["daily_rows"][0]["volume"] == 12300
    assert repository.completed["daily_rows"][0]["amount"] == 18_600_000.0
    assert set(repository.completed["auxiliary_datasets"]) == {
        "trade_calendar",
        "daily_basic",
        "adj_factor",
        "suspensions",
        "price_limits",
        "corporate_actions",
        "benchmark_bars",
    }
    assert len(repository.completed["auxiliary_datasets"]["benchmark_bars"]) == 4


def test_full_a_share_sync_reuses_running_database_gate():
    repository = FakeRepository(run_id=None)
    result = AshareInstrumentSyncService(repository=repository, provider=FakeProvider()).sync_all(trigger="scheduled")

    assert result == {"status": "locked", "trigger": "scheduled"}
    assert repository.completed is None


def test_full_a_share_sync_fails_without_trade_date_rows():
    class EmptyDailyProvider(FakeProvider):
        def fetch_daily(self, trade_date: str):
            return []

    repository = FakeRepository()
    try:
        AshareInstrumentSyncService(repository=repository, provider=EmptyDailyProvider()).sync_all(trigger="scheduled")
    except RuntimeError as error:
        assert "daily" in str(error)
    else:
        raise AssertionError("an open-day sync without daily rows must fail")
    assert repository.completed is None
    assert repository.failed and repository.failed[0] == 17


def test_recent_history_sync_fetches_every_open_day_before_one_atomic_commit():
    class HistoryProvider(FakeProvider):
        def __init__(self):
            self.daily_dates = []
            self.benchmark_dates = []

        def fetch_trade_calendar(self, start_date: str, end_date: str, is_open=None):
            assert (start_date, end_date, is_open) == ("20260825", "20260826", "1")
            return [
                {"cal_date": "20260825", "is_open": 1},
                {"cal_date": "20260826", "is_open": 1},
            ]

        def fetch_daily(self, trade_date: str):
            self.daily_dates.append(trade_date)
            return [
                {
                    "ts_code": "600519.SH",
                    "trade_date": trade_date,
                    "open": 1500.0,
                    "high": 1520.0,
                    "low": 1490.0,
                    "close": 1510.0,
                    "pct_chg": 1.25,
                    "vol": 123.0,
                    "amount": 18600.0,
                },
                {
                    "ts_code": "000001.SZ",
                    "trade_date": trade_date,
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10.1,
                    "pct_chg": 1.0,
                    "vol": 456.0,
                    "amount": 4600.0,
                },
            ]

        def fetch_benchmark_bars(self, trade_date: str, benchmarks=None):
            assert benchmarks == ["000300.SH"]
            self.benchmark_dates.append(trade_date)
            day_offset = 0 if trade_date == "20260825" else 1
            return [{
                "ts_code": "000300.SH", "trade_date": trade_date,
                "open": 3600 + day_offset, "high": 3610 + day_offset,
                "low": 3590 + day_offset, "close": 3605 + day_offset,
                "pct_chg": 0.1, "vol": 1000, "amount": 1_000_000,
            }]

    class HistoryRepository(FakeRepository):
        def __init__(self):
            super().__init__()
            self.progress = []
            self.history_completed = None

        def update_history_progress(self, run_id, **payload):
            self.progress.append((run_id, payload))

        def complete_history_run(self, run_id, instruments, daily_rows, start_date, end_date, *, trade_date_count, benchmark_rows, abnormal_metrics):
            self.history_completed = {
                "run_id": run_id,
                "instruments": instruments,
                "daily_rows": daily_rows,
                "start_date": start_date,
                "end_date": end_date,
                "trade_date_count": trade_date_count,
                "benchmark_rows": benchmark_rows,
                "abnormal_metrics": abnormal_metrics,
            }
            return {
                "run_id": run_id,
                "status": "success",
                "sync_scope": "history",
                "instrument_count": len(instruments),
                "daily_count": len(daily_rows),
                "start_date": start_date,
                "end_date": end_date,
                "trade_date_count": trade_date_count,
            }

    provider = HistoryProvider()
    repository = HistoryRepository()
    result = AshareInstrumentSyncService(repository=repository, provider=provider).sync_history(
        history_days=2,
        end_date="2026-08-26",
    )

    assert provider.daily_dates == ["20260825", "20260826"]
    assert provider.benchmark_dates == ["20260825", "20260826"]
    assert result == {
        "run_id": 17,
        "status": "success",
        "sync_scope": "history",
        "instrument_count": 3,
        "daily_count": 4,
        "start_date": "2026-08-25",
        "end_date": "2026-08-26",
        "trade_date_count": 2,
        "benchmark_count": 2,
        "abnormal_metric_count": 2,
        "eligible_abnormal_metric_count": 0,
    }
    assert repository.history_completed["daily_rows"][0]["trade_date"] == "2026-08-25"
    assert len(repository.history_completed["benchmark_rows"]) == 2
    assert len(repository.history_completed["abnormal_metrics"]) == 2
    assert all(item["status"] == "partial" for item in repository.history_completed["abnormal_metrics"])
    assert repository.progress[-1][1]["processed_trade_dates"] == 2
    assert repository.failed is None


def test_recent_history_sync_fails_before_commit_when_an_open_day_is_empty():
    class EmptyHistoryProvider(FakeProvider):
        def fetch_trade_calendar(self, start_date: str, end_date: str, is_open=None):
            return [{"cal_date": "20260825", "is_open": 1}, {"cal_date": "20260826", "is_open": 1}]

        def fetch_daily(self, trade_date: str):
            if trade_date == "20260825":
                return []
            return super().fetch_daily(trade_date)

    repository = FakeRepository()
    try:
        AshareInstrumentSyncService(repository=repository, provider=EmptyHistoryProvider()).sync_history(
            history_days=2,
            end_date="2026-08-26",
        )
    except RuntimeError as error:
        assert "2026-08-25" in str(error)
    else:
        raise AssertionError("an empty interior open day must abort the whole history commit")
    assert repository.completed is None
    assert repository.failed and repository.failed[0] == 17


def test_recent_history_sync_reuses_running_database_gate_without_provider_calls():
    class NoCallProvider(FakeProvider):
        def fetch_instruments(self):
            raise AssertionError("locked history sync must not call the provider")

    repository = FakeRepository(run_id=None)
    result = AshareInstrumentSyncService(repository=repository, provider=NoCallProvider()).sync_history(
        history_days=180,
        end_date="2026-08-26",
    )

    assert result == {"status": "locked", "trigger": "manual", "sync_scope": "history"}
    assert repository.completed is None


def test_history_sync_endpoint_requires_admin_and_uses_half_year_default(monkeypatch):
    calls = []

    class Service:
        def reserve_history(self, **payload):
            calls.append(payload)
            return {
                "run_id": 18,
                "status": "accepted",
                "sync_scope": "history",
                "start_date": "2026-03-01",
                "end_date": "2026-08-27",
            }

        def sync_history(self, **_payload):
            return {"status": "success"}

    monkeypatch.setattr(sync_endpoint, "instrument_sync_service", Service())
    request = SimpleNamespace(state=SimpleNamespace(auth={"role": "admin"}))
    payload = sync_endpoint.AshareHistorySyncRequest()
    result = asyncio.run(sync_endpoint.sync_ashare_history(payload, request))

    assert result["data"]["status"] == "accepted"
    assert calls == [{"history_days": 180, "start_date": None, "end_date": None, "trigger": "manual"}]


def test_tushare_provider_fetches_all_listing_states_and_latest_open_day():
    class Frame:
        def __init__(self, rows):
            self.rows = rows

        def to_dict(self, orient):
            assert orient == "records"
            return self.rows

    class Pro:
        def __init__(self):
            self.statuses = []

        def stock_basic(self, **kwargs):
            self.statuses.append(kwargs["list_status"])
            return Frame([{"ts_code": f"00000{len(self.statuses)}.SZ", "name": f"证券{len(self.statuses)}"}])

        def trade_cal(self, **_):
            return Frame([{"cal_date": "20260825"}, {"cal_date": "20260826"}])

        def daily(self, **kwargs):
            return Frame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"]}])

        def daily_basic(self, **kwargs):
            return Frame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"]}])

    pro = Pro()
    provider = TushareAshareProvider(client=pro)

    assert len(provider.fetch_instruments()) == 3
    assert pro.statuses == ["L", "P", "D"]
    assert provider.latest_open_trade_date() == "20260826"
    assert provider.fetch_daily("20260826")[0]["trade_date"] == "20260826"
    assert provider.fetch_daily_basic("20260826")[0]["trade_date"] == "20260826"


def test_daily_scheduler_registers_one_coalesced_a_share_job():
    class Scheduler:
        def __init__(self):
            self.jobs = []
            self.running = False

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append((func, trigger, kwargs))

        def start(self):
            self.running = True

        def shutdown(self, wait=False):
            self.running = False

    scheduler = Scheduler()
    configured = SimpleNamespace(
        A_SHARE_DAILY_SYNC_ENABLED=True,
        A_SHARE_DAILY_SYNC_HOUR=18,
        A_SHARE_DAILY_SYNC_MINUTE=10,
        A_SHARE_DAILY_SYNC_TIMEZONE="Asia/Shanghai",
        TUSHARE_TOKEN="configured",
    )
    service = SimpleNamespace(sync_all=lambda **_: {"status": "success"})
    daily = AshareDailySyncScheduler(
        service=service,
        configured_settings=configured,
        scheduler=scheduler,
        trigger_factory=lambda **kwargs: kwargs,
    )

    daily.start()

    assert scheduler.running is True
    assert len(scheduler.jobs) == 1
    _, trigger, options = scheduler.jobs[0]
    assert trigger == {"hour": 18, "minute": 10, "timezone": "Asia/Shanghai"}
    assert options["id"] == "a-share-daily-instrument-sync"
    assert options["coalesce"] is True
    assert options["max_instances"] == 1


def test_data_config_lists_repository_instruments_with_chinese_names(monkeypatch):
    instruments = [
        {"symbol": "000001.SZ", "name": "平安银行", "display_name": "平安银行 000001.SZ", "asset_class": "stock"},
        {"symbol": "600519.SH", "name": "贵州茅台", "display_name": "贵州茅台 600519.SH", "asset_class": "stock"},
    ]
    repository = SimpleNamespace(list_instruments=lambda **_: instruments, latest_run=lambda: {"status": "success"})
    monkeypatch.setattr(sync_endpoint, "instrument_repository", repository)

    payload = asyncio.run(sync_endpoint.config())["data"]

    assert payload["default_symbols"] == ["000001.SZ", "600519.SH"]
    assert payload["instruments"] == instruments
    assert payload["symbols_count"] == 2


def test_market_symbols_returns_name_first_instrument_contract(monkeypatch):
    instruments = [
        {"symbol": "600519.SH", "name": "贵州茅台", "display_name": "贵州茅台 600519.SH", "asset_class": "stock"}
    ]
    service = SimpleNamespace(get_instruments=lambda *_args, **_kwargs: instruments)
    async def get_instruments(*args, **kwargs):
        return service.get_instruments(*args, **kwargs)
    monkeypatch.setattr(market_endpoint.market_domain_service, "get_instruments", get_instruments)

    payload = asyncio.run(market_endpoint.get_symbols(exchange="CN", quote="CNY", market_type="stock"))["data"]

    assert payload == {"symbols": ["600519.SH"], "instruments": instruments}


def test_market_symbol_name_lookup_returns_input_and_canonical_aliases(monkeypatch):
    async def lookup_names(symbols):
        assert symbols == ["SH_600519", "000001.SZ"]
        return {"SH_600519": "贵州茅台", "600519.SH": "贵州茅台", "000001.SZ": "平安银行"}
    monkeypatch.setattr(market_endpoint.market_domain_service, "lookup_names", lookup_names)

    payload = asyncio.run(market_endpoint.lookup_symbol_names(symbols="SH_600519,000001.SZ"))["data"]

    assert payload["names"]["600519.SH"] == "贵州茅台"
    assert payload["names"]["000001.SZ"] == "平安银行"


def test_application_lifespan_starts_and_stops_daily_a_share_scheduler(monkeypatch):
    events = []
    scheduler = SimpleNamespace(start=lambda: events.append("start"), stop=lambda: events.append("stop"))
    monkeypatch.setattr(main_module, "a_share_daily_sync_scheduler", scheduler)

    async def exercise():
        async with main_module.safe_lifespan(None):
            events.append("running")

    asyncio.run(exercise())

    assert events == ["start", "running", "stop"]


def test_data_manager_exposes_admin_only_half_year_a_share_history_sync():
    root = Path(__file__).resolve().parents[2]
    source = (root / "frontend/src/pages/DataManager.tsx").read_text(encoding="utf-8")
    client = (root / "frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "syncAllAshareHistory" in client
    assert "postReq('/sync/history/sync-all'" in client
    assert "const dataExchange = 'CN'" in source
    assert 'data-testid="ashare-history-sync-button"' in source
    assert "historyDays: SYNC_HISTORY_DAYS" in source
    assert "SYNC_HISTORY_DAYS = 180" in source
    assert "disabled={!isAdmin || isBusy || ashareHistorySyncing}" in source
    assert "拉取近半年 A股" in source


def test_sync_status_exposes_durable_history_job_id_and_trade_date_progress(monkeypatch):
    monkeypatch.setattr(
        sync_endpoint,
        "_snapshot",
        lambda: {
            "rows": 10,
            "symbols": 2,
            "instrument_count": 2,
            "first_date": "2026-03-01",
            "last_date": "2026-03-02",
            "first_ms": 1,
            "last_ms": 2,
        },
    )
    monkeypatch.setattr(
        sync_endpoint.instrument_repository,
        "latest_run",
        lambda: {
            "run_id": 19,
            "trigger": "manual",
            "status": "running",
            "provider": "tushare",
            "sync_scope": "history",
            "start_date": "2026-03-01",
            "end_date": "2026-08-27",
            "trade_date_count": 124,
            "processed_trade_dates": 42,
            "last_processed_trade_date": "2026-04-30",
            "instrument_count": 5889,
            "daily_count": 230000,
            "error_message": None,
            "started_at": "2026-08-27T15:00:00+08:00",
            "finished_at": None,
        },
    )

    payload = asyncio.run(sync_endpoint.status())
    current = payload["data"]["current_job"]

    assert current["job_id"] == "19"
    assert current["sync_scope"] == "history"
    assert current["trade_date_count"] == 124
    assert current["processed_trade_dates"] == 42
