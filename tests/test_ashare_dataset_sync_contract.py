from app.domain.instruments.service import AshareInstrumentSyncService


class FakeRepository:
    def __init__(self):
        self.auxiliary_datasets = None
        self.instruments = None
        self.daily_rows = None
        self.trade_date = None
        self.failed = None

    def begin_run(self, trigger: str):
        assert trigger == "manual"
        return 101

    def complete_run(self, run_id, instruments, daily_rows, trade_date, *, auxiliary_datasets=None):
        assert run_id == 101
        self.instruments = instruments
        self.daily_rows = daily_rows
        self.trade_date = trade_date
        self.auxiliary_datasets = auxiliary_datasets or {}
        return {
            "run_id": run_id,
            "status": "success",
            "instrument_count": len(instruments),
            "daily_count": len(daily_rows),
            "trade_date": trade_date,
            "dataset_snapshot": {
                "status": "sealed",
                "dataset_codes": [
                    "security_master",
                    "trade_calendar",
                    "daily_bars",
                    "adj_factor",
                    "daily_basic",
                    "suspensions",
                    "price_limits",
                    "corporate_actions",
                    "benchmark_bars",
                ],
            },
        }

    def fail_run(self, run_id, error):
        self.failed = (run_id, error)


class FakeProvider:
    def fetch_instruments(self):
        return [
            {
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "industry": "白酒",
                "market": "主板",
                "list_status": "L",
                "list_date": "20010827",
            },
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "industry": "银行",
                "market": "主板",
                "list_status": "L",
                "list_date": "19910403",
            },
        ]

    def latest_open_trade_date(self):
        return "20260826"

    def fetch_trade_calendar(self, start_date, end_date):
        assert start_date == "20260826"
        assert end_date == "20260826"
        return [{"exchange": "SSE", "cal_date": "20260826", "is_open": 1, "pretrade_date": "20260825"}]

    def fetch_daily_basic(self, trade_date):
        assert trade_date == "20260826"
        return [
            {
                "ts_code": "600519.SH",
                "trade_date": "20260826",
                "close": 1520.0,
                "turnover_rate": 0.8,
                "turnover_rate_f": 0.9,
                "volume_ratio": 1.2,
                "pe": 25,
                "pe_ttm": 24,
                "pb": 8,
                "ps": 10,
                "ps_ttm": 9,
                "dv_ratio": 1.5,
                "dv_ttm": 1.4,
                "total_mv": 1900000,
                "circ_mv": 1900000,
                "limit_status": 0,
            },
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260826",
                "close": 12.3,
                "turnover_rate": 1.1,
                "turnover_rate_f": 1.2,
                "volume_ratio": 0.9,
                "pe": 6,
                "pe_ttm": 5.8,
                "pb": 0.7,
                "ps": 1.2,
                "ps_ttm": 1.1,
                "dv_ratio": 3.1,
                "dv_ttm": 3.0,
                "total_mv": 230000,
                "circ_mv": 230000,
                "limit_status": 0,
            },
        ]

    def fetch_daily(self, trade_date):
        assert trade_date == "20260826"
        return [
            {
                "ts_code": "600519.SH",
                "trade_date": "20260826",
                "open": 1500,
                "high": 1530,
                "low": 1490,
                "close": 1520,
                "pre_close": 1510,
                "pct_chg": 0.66,
                "vol": 12000,
                "amount": 1824000,
            },
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260826",
                "open": 12,
                "high": 12.5,
                "low": 11.9,
                "close": 12.3,
                "pre_close": 12.1,
                "pct_chg": 1.65,
                "vol": 800000,
                "amount": 984000,
            },
        ]

    def fetch_adj_factor(self, trade_date):
        assert trade_date == "20260826"
        return [
            {"ts_code": "600519.SH", "trade_date": "20260826", "adj_factor": 12.1},
            {"ts_code": "000001.SZ", "trade_date": "20260826", "adj_factor": 108.2},
        ]

    def fetch_suspensions(self, trade_date):
        assert trade_date == "20260826"
        return []

    def fetch_price_limits(self, trade_date):
        assert trade_date == "20260826"
        return [
            {"ts_code": "600519.SH", "trade_date": "20260826", "pre_close": 1510, "up_limit": 1661, "down_limit": 1359},
            {"ts_code": "000001.SZ", "trade_date": "20260826", "pre_close": 12.1, "up_limit": 13.31, "down_limit": 10.89},
        ]

    def fetch_corporate_actions(self, trade_date):
        assert trade_date == "20260826"
        return []

    def fetch_benchmark_bars(self, trade_date):
        assert trade_date == "20260826"
        return [
            {"ts_code": "000001.SH", "trade_date": "20260826", "open": 3000, "high": 3030, "low": 2990, "close": 3020},
            {"ts_code": "399001.SZ", "trade_date": "20260826", "open": 10000, "high": 10100, "low": 9900, "close": 10080},
            {"ts_code": "399006.SZ", "trade_date": "20260826", "open": 2000, "high": 2040, "low": 1980, "close": 2030},
            {"ts_code": "000300.SH", "trade_date": "20260826", "open": 3600, "high": 3650, "low": 3580, "close": 3630},
        ]


def test_ashare_sync_publishes_research_ready_dataset_inputs():
    repository = FakeRepository()
    service = AshareInstrumentSyncService(repository=repository, provider=FakeProvider())

    result = service.sync_all()

    assert result["status"] == "success"
    assert result["trade_date"] == "2026-08-26"
    assert result["dataset_snapshot"]["status"] == "sealed"
    assert repository.trade_date == "2026-08-26"
    assert repository.failed is None
    assert [row["name"] for row in repository.instruments] == ["平安银行", "贵州茅台"]
    assert {row["symbol"]: row["name"] for row in repository.daily_rows} == {
        "000001.SZ": "平安银行",
        "600519.SH": "贵州茅台",
    }

    assert set(repository.auxiliary_datasets) == {
        "trade_calendar",
        "daily_basic",
        "adj_factor",
        "suspensions",
        "price_limits",
        "corporate_actions",
        "benchmark_bars",
    }
    assert repository.auxiliary_datasets["trade_calendar"][0]["trade_date"] == "2026-08-26"
    assert len(repository.auxiliary_datasets["daily_basic"]) == 2
    assert len(repository.auxiliary_datasets["adj_factor"]) == 2
    assert len(repository.auxiliary_datasets["price_limits"]) == 2
    assert len(repository.auxiliary_datasets["benchmark_bars"]) == 4
