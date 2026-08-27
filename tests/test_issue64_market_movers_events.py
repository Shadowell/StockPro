from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import monitor  # noqa: E402
from app.domain.market.repository import MarketRepository  # noqa: E402
import app.domain.market.research_metrics as research_metrics  # noqa: E402

try:  # pragma: no cover - keeps the red test as an assertion, not collection failure.
    from app.domain.market.materialization import build_symbol_abnormal_metrics
except ModuleNotFoundError:  # pragma: no cover
    build_symbol_abnormal_metrics = None


class _CaptureCursor:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def execute(self, query, _params=()): self.queries.append(str(query))
    def fetchall(self): return []


class _CaptureConnection:
    def __init__(self, cursor: _CaptureCursor) -> None: self._cursor = cursor
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def set_session(self, **_kwargs): return None
    def cursor(self, **_kwargs): return self._cursor


def _bars(count: int, *, close_start: float = 10.0, close_step: float = 0.2) -> list[dict]:
    rows = []
    for index in range(count):
        day = index + 1
        month = 7 + (day - 1) // 31
        month_day = (day - 1) % 31 + 1
        close = close_start + index * close_step
        rows.append(
            {
                "date": f"2026-{month:02d}-{month_day:02d}",
                "open": close - 0.05,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "amount": 100_000 + index * 10_000,
            }
        )
    return rows


def test_abnormal_rule_and_windows_keep_board_st_and_directional_thresholds() -> None:
    assert hasattr(research_metrics, "abnormal_rule_for")
    assert hasattr(research_metrics, "build_abnormal_windows")
    abnormal_rule_for = research_metrics.abnormal_rule_for
    build_abnormal_windows = research_metrics.build_abnormal_windows
    main = abnormal_rule_for("600000.SH", "*ST 主板")
    gem = abnormal_rule_for("300001.SZ", "创业板")
    star = abnormal_rule_for("688001.SH", "科创板")
    bse = abnormal_rule_for("920001.BJ", "北交所")

    assert main.board == "主板"
    assert main.st is True
    assert main.thresholds[3] == (0.20, 0.20)
    assert main.thresholds[10] == (1.00, 0.50)
    assert main.thresholds[30] == (2.00, 0.70)
    assert gem.thresholds[3] == (0.30, 0.30)
    assert star.thresholds[3] == (0.30, 0.30)
    assert bse.thresholds[3] == (0.40, 0.40)

    windows = build_abnormal_windows(
        {"3d": 0.16, "10d": -0.55, "30d": 0.40},
        main,
    )

    assert windows["3d"]["value"] == 0.16
    assert windows["3d"]["value_pct"] == 16.0
    assert windows["3d"]["threshold"] == 0.20
    assert windows["3d"]["threshold_pct"] == 20.0
    assert windows["3d"]["closeness"] == 0.8
    assert windows["3d"]["direction"] == "up"
    assert windows["3d"]["status"] == "edge"
    assert windows["10d"]["threshold"] == 0.50
    assert windows["10d"]["direction"] == "down"
    assert windows["10d"]["status"] == "triggered"
    assert windows["30d"]["status"] == "watch"


def test_symbol_abnormality_exposes_windows_only_when_relative_evidence_is_complete() -> None:
    bars = _bars(61)
    benchmark = _bars(61, close_start=20.0, close_step=0.1)
    sector = _bars(61, close_start=15.0, close_step=0.12)

    assert hasattr(research_metrics, "compute_symbol_abnormality")
    compute_symbol_abnormality = research_metrics.compute_symbol_abnormality
    payload = compute_symbol_abnormality(
        bars,
        symbol="300001.SZ",
        name="示例创业板",
        trade_date="2026-08-31",
        benchmark_bars=benchmark,
        sector_bars=sector,
    )

    assert payload["data_status"] == "ok"
    assert payload["board"] == "创业板"
    assert payload["windows"]["3d"]["threshold"] == 0.30
    assert payload["windows"]["10d"]["threshold"] in {0.50, 1.00}
    assert payload["max_closeness"] is not None
    assert payload["abnormal_status"] in {"triggered", "edge", "watch"}
    assert payload["eligible"] is True

    partial = compute_symbol_abnormality(
        bars[:30],
        symbol="600000.SH",
        name="示例主板",
        trade_date="2026-08-01",
        benchmark_bars=benchmark[:30],
        sector_bars=sector[:30],
    )

    assert partial["data_status"] == "partial"
    assert partial["eligible"] is False
    assert partial["windows"] == {}
    assert any("30d" in item for item in partial["missing_inputs"])


def test_repository_abnormality_projection_keeps_snapshot_and_board_evidence() -> None:
    repository = MarketRepository("postgresql://example.invalid/db")
    row = (
        "300001.SZ", "2026-08-31", 16.0, 35.0, 80.0,
        16.0, 35.0, 80.0, 12.0, 22.0, 35.0,
        1.2, 2.0, -1.0, [], "ok", [], "ashare-abnormality.v1",
        "2026-08-31T09:30:00+08:00", "2026-08-31T17:30:00+08:00",
        7, "000300.SH", "I001", "示例创业板", "创业板",
    )

    payload = repository._abnormality_row(row)

    assert payload["source_snapshot_id"] == 7
    assert payload["board"] == "创业板"
    assert payload["eligible"] is True
    assert payload["windows"]["3d"]["threshold"] == 0.30


def test_abnormality_list_query_qualifies_metrics_columns_after_instrument_join(monkeypatch) -> None:
    cursor = _CaptureCursor()
    repository = MarketRepository(
        "postgresql://example.invalid/db",
        connection_factory=lambda *_args, **_kwargs: _CaptureConnection(cursor),
    )
    monkeypatch.setattr(repository, "_table_exists", lambda *_args: True)

    repository.list_symbol_abnormalities(limit=10)

    query = cursor.queries[-1]
    assert "SELECT m.symbol,m.trade_date,m.return_3d" in query
    assert "m.tags,m.status,m.missing_inputs,m.definition_version" in query
    assert "WHERE m.trade_date=(SELECT MAX(latest.trade_date) FROM symbol_abnormal_metrics latest)" in query
    assert "ORDER BY m.trade_date DESC,ABS(COALESCE(m.benchmark_deviation_3d,0)) DESC,m.symbol" in query


def test_history_materializer_builds_latest_eligible_metrics_from_real_stock_benchmark_and_industry_rows() -> None:
    assert build_symbol_abnormal_metrics is not None
    instruments = [
        {"symbol": "600001.SH", "name": "示例甲", "industry": "示例行业", "board": "主板"},
        {"symbol": "600002.SH", "name": "示例乙", "industry": "示例行业", "board": "主板"},
    ]
    daily_rows = []
    benchmark_rows = []
    for index in range(40):
        day = f"2026-07-{index + 1:02d}" if index < 31 else f"2026-08-{index - 30:02d}"
        benchmark_rows.append({"symbol": "000300.SH", "trade_date": day, "open": 100 + index, "high": 101 + index, "low": 99 + index, "close": 100 + index, "amount": 1_000_000})
        for offset, instrument in enumerate(instruments):
            close = 10 + index * (0.2 + offset * 0.05)
            daily_rows.append({"symbol": instrument["symbol"], "trade_date": day, "open": close - 0.1, "high": close + 0.2, "low": close - 0.2, "close": close, "amount": 100_000 + index * 1_000, "change_percent": 1 + offset})

    metrics = build_symbol_abnormal_metrics(
        daily_rows=daily_rows,
        benchmark_rows=benchmark_rows,
        instruments=instruments,
        trade_date="2026-08-09",
    )

    assert len(metrics) == 2
    assert {item["symbol"] for item in metrics} == {"600001.SH", "600002.SH"}
    assert all(item["eligible"] is True for item in metrics)
    assert all(item["sector_code"] == "示例行业" for item in metrics)
    assert all(item["benchmark_code"] == "000300.SH" for item in metrics)
    assert all(set(item["windows"]) == {"3d", "10d", "30d"} for item in metrics)
    assert all(item["available_at"] and item["knowledge_cutoff_at"] for item in metrics)


def test_monitor_events_endpoint_is_read_only_and_filters_the_persisted_stream(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(monitor.router, prefix="/api/v2/monitor")

    captured: dict[str, object] = {}
    assert hasattr(monitor, "market_domain_service")

    async def fake_events(*, limit: int, source: str | None, severity: str | None):
        captured.update({"limit": limit, "source": source, "severity": severity})
        return {
            "events": [
                {
                    "event_id": "evt-1",
                    "source": "abnormal",
                    "severity": "warning",
                    "symbol": "600000.SH",
                    "name": "示例主板",
                    "message": "3日异动边缘",
                    "rule_id": "ashare-abnormal-3d",
                    "triggered_at": "2026-08-31T09:30:00+08:00",
                    "orders_created": 0,
                }
            ],
            "data_status": "ok",
            "unavailable_reason": None,
            "orders_created": 0,
        }

    monkeypatch.setattr(monitor.market_domain_service, "list_market_events", fake_events)
    client = TestClient(app)

    response = client.get(
        "/api/v2/monitor/events",
        params={"limit": 10, "source": "abnormal", "severity": "warning"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["events"][0]["source"] == "abnormal"
    assert body["data"]["orders_created"] == 0
    assert captured == {"limit": 10, "source": "abnormal", "severity": "warning"}


def test_issue64_home_contract_contains_movers_windows_event_stream_and_safe_drilldowns() -> None:
    home = (ROOT / "frontend/src/pages/Home.tsx").read_text(encoding="utf-8")
    monitor_page = (ROOT / "frontend/src/pages/Monitor.tsx").read_text(encoding="utf-8")
    client = (ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    migration_path = ROOT / "backend/postgres/migrations/202608270004_market_alert_events.sql"
    assert migration_path.exists()
    migration = migration_path.read_text(encoding="utf-8")

    assert "异动边缘" in home
    assert "告警事件流" in home
    assert "3日" in home and "10日" in home and "30日" in home
    assert "abnormalStatus" in home
    assert "marketApi.getDashboard()" in home
    assert "dashboard.events.events" in home
    assert "monitorApi.getEvents" not in home
    assert "navigate('/market')" in home or "navigate(`/market" in home
    assert "监控中心" in home
    assert "getEvents" in client
    assert "MarketEventHistory" in monitor_page
    assert "monitorApi.getEvents(100)" in monitor_page
    assert "market_alert_events" in migration
    assert "orders_created" in migration
    assert "CHECK (orders_created = 0)" in migration
