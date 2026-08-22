from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import review  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402


BASE_TS = 1_780_000_000_000
HOUR = 60 * 60 * 1000


def _client(database: LocalDatabase, monkeypatch) -> TestClient:
    monkeypatch.setattr(review, "db", database)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(review.router, prefix="/review")
    return TestClient(app)


def _insert_strategy(
    database: LocalDatabase,
    *,
    strategy_id: int,
    name: str,
    config: str,
    symbols: str,
    status: str = "running",
) -> None:
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO strategies (id, name, description, script_content, config, status, exchange, symbols, run_started_at)
        VALUES (?, ?, '', '', ?, ?, 'okx', ?, '2026-06-05T00:00:00+00:00')
        """,
        (strategy_id, name, config, status, symbols),
    )
    conn.commit()
    conn.close()


def _sample(database: LocalDatabase, strategy_id: int, offset_hours: int, equity: float) -> None:
    assert database.insert_strategy_equity_sample(
        strategy_id,
        BASE_TS + offset_hours * HOUR,
        equity,
        total_pnl=equity - 100,
        return_pct=(equity - 100) / 100 * 100,
        source="test",
    )


def _trade(database: LocalDatabase, strategy_id: int, offset_hours: int, side: str, pnl: float) -> None:
    database.insert_strategy_trade(
        strategy_id,
        {
            "exchange": "okx",
            "symbol": "BTC/USDT:USDT",
            "timestamp": BASE_TS + offset_hours * HOUR + 30_000,
            "side": side,
            "type": "market",
            "price": 100.0,
            "quantity": 1.0,
            "fee": 0.01,
            "fee_asset": "USDT",
            "pnl": pnl,
        },
    )


def test_review_summary_groups_scores_and_tags_paper_strategies_only(tmp_path, monkeypatch) -> None:
    database = LocalDatabase(str(tmp_path / "review.db"))
    database.init_db()
    _insert_strategy(
        database,
        strategy_id=1,
        name="[合约][1H][CTA] Top20 · 动态趋势跟踪 · 100U",
        config='{"is_paper_trading": true, "market_type": "swap", "timeframe": "1h", "initial_capital": 100, "strategy_type": "cta"}',
        symbols='["BTC/USDT:USDT", "ETH/USDT:USDT"]',
    )
    _insert_strategy(
        database,
        strategy_id=2,
        name="[合约][1M][马丁] SOL · ATR马丁网格 · 100U",
        config='{"is_paper_trading": true, "market_type": "swap", "timeframe": "1m", "initial_capital": 100, "strategy_type": "martingale"}',
        symbols='["SOL/USDT:USDT"]',
    )
    _insert_strategy(
        database,
        strategy_id=3,
        name="[合约][15M][AI] Top20 · 自主多空 · 100U",
        config='{"is_paper_trading": true, "market_type": "swap", "timeframe": "15m", "initial_capital": 100, "strategy_type": "ai"}',
        symbols='["BTC/USDT:USDT"]',
    )
    _insert_strategy(
        database,
        strategy_id=4,
        name="[合约][1H][CTA] 实盘 · 不应进入复盘 · 100U",
        config='{"is_paper_trading": false, "market_type": "swap", "timeframe": "1h", "initial_capital": 100, "strategy_type": "cta"}',
        symbols='["BTC/USDT:USDT"]',
    )
    _insert_strategy(
        database,
        strategy_id=5,
        name="[合约][4H][CTA] AVAX · 尚无权益样本 · 100U",
        config='{"is_paper_trading": true, "market_type": "swap", "timeframe": "4h", "initial_capital": 100, "strategy_type": "cta"}',
        symbols='["AVAX/USDT:USDT"]',
    )
    _insert_strategy(
        database,
        strategy_id=6,
        name="[合约][1H][CTA] 停止策略 · 旧样本不应进入复盘 · 100U",
        config='{"is_paper_trading": true, "market_type": "swap", "timeframe": "1h", "initial_capital": 100, "strategy_type": "cta"}',
        symbols='["BTC/USDT:USDT"]',
        status="stopped",
    )
    _insert_strategy(
        database,
        strategy_id=7,
        name="[合约][1H][CTA] 暂停策略 · 不应进入复盘 · 100U",
        config='{"is_paper_trading": true, "market_type": "swap", "timeframe": "1h", "initial_capital": 100, "strategy_type": "cta"}',
        symbols='["ETH/USDT:USDT"]',
        status="paused",
    )

    for offset, equity in enumerate([100, 103, 108, 112]):
        _sample(database, 1, offset, equity)
    for offset, equity in enumerate([100, 96, 88, 82]):
        _sample(database, 2, offset, equity)
    for offset, equity in enumerate([100, 102]):
        _sample(database, 3, offset, equity)
    for offset, equity in enumerate([100, 140]):
        _sample(database, 4, offset, equity)
    for offset, equity in enumerate([100, 180], start=48):
        _sample(database, 6, offset, equity)
    for offset, equity in enumerate([100, 40], start=48):
        _sample(database, 7, offset, equity)

    for side, pnl in [("close_long", 5), ("close_long", 4), ("close_short", -1), ("open_long", 0)]:
        _trade(database, 1, 3, side, pnl)
    for side, pnl in [("close_long", 1), ("close_long", 1), ("close_long", -12)]:
        _trade(database, 2, 2, side, pnl)
    _trade(database, 6, 49, "close_long", 80)
    _trade(database, 7, 49, "close_long", -60)

    client = _client(database, monkeypatch)
    response = client.get("/review/summary?window=24h&bucket=1h")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["overview"]["strategy_count"] == 4
    assert data["overview"]["sample_strategy_count"] == 3
    assert data["overview"]["sample_health_pct"] == 75.0
    assert data["overview"]["review_window"] == "24h"
    assert data["overview"]["bucket"] == "1h"
    assert data["overview"]["overall_return_pct"] == -1.3333

    group_keys = {item["group_key"] for item in data["groups"]}
    assert "[合约][1H][CTA] · 100U" in group_keys
    assert "[合约][1M][马丁] · 100U" in group_keys
    assert "[合约][15M][AI] · 100U" in group_keys
    all_leader_names = [item["name"] for section in data["leaderboard"].values() for item in section]
    assert all("实盘" not in name for name in all_leader_names)
    assert all("停止策略" not in name for name in all_leader_names)
    assert all("暂停策略" not in name for name in all_leader_names)
    assert all("停止策略" not in row["group_key"] for row in data["groups"])
    assert all("暂停策略" not in row["group_key"] for row in data["groups"])
    grouped_strategy_names = [
        strategy["name"]
        for group in data["groups"]
        for strategy in group["strategies"]
    ]
    assert "[合约][1H][CTA] Top20 · 动态趋势跟踪 · 100U" in grouped_strategy_names
    assert "[合约][1M][马丁] SOL · ATR马丁网格 · 100U" in grouped_strategy_names
    assert all("实盘" not in name for name in grouped_strategy_names)
    assert all("停止策略" not in name for name in grouped_strategy_names)
    assert all("暂停策略" not in name for name in grouped_strategy_names)

    martingale = next(item for item in data["groups"] if item["group_key"] == "[合约][1M][马丁] · 100U")
    assert martingale["score"] < 45
    assert martingale["verdict"] in {"复查降仓", "暂停复查"}
    assert martingale["return_pct"] < 0
    assert martingale["max_drawdown_pct"] >= 18
    assert martingale["strategies"][0]["strategy_id"] == 2
    assert martingale["strategies"][0]["tags"]
    assert "持续失血" in martingale["strategies"][0]["tags"]

    observe_names = [item["name"] for item in data["leaderboard"]["observe"]]
    review_names = [item["name"] for item in data["leaderboard"]["review"]]
    assert "[合约][1H][CTA] Top20 · 动态趋势跟踪 · 100U" in observe_names
    assert "[合约][1M][马丁] SOL · ATR马丁网格 · 100U" in review_names

    tag_labels = {item["label"] for item in data["tags"]}
    assert "马丁回撤风险" in tag_labels
    assert "样本不足" in tag_labels
    assert data["heatmap"][0]["buckets"][0]["hour"]
    assert data["next_actions"]


def test_review_summary_labels_negative_low_sample_as_equity_pullback(tmp_path, monkeypatch) -> None:
    database = LocalDatabase(str(tmp_path / "review-low-sample.db"))
    database.init_db()
    _insert_strategy(
        database,
        strategy_id=11,
        name="[合约][15M][CTA] TOP12 · 硬止盈3:1激进版 · 100U",
        config='{"is_paper_trading": true, "market_type": "swap", "timeframe": "15m", "initial_capital": 100, "strategy_type": "cta"}',
        symbols='["BTC/USDT:USDT"]',
    )

    for offset, equity in enumerate([100, 99.9, 99.8, 99.7]):
        _sample(database, 11, offset, equity)

    client = _client(database, monkeypatch)
    response = client.get("/review/summary?window=24h&bucket=1h")

    assert response.status_code == 200
    data = response.json()["data"]
    item = data["leaderboard"]["review"][0]
    assert item["trade_count"] == 0
    assert item["return_pct"] < 0
    assert item["verdict"] == "等待样本"
    assert "样本不足" in item["tags"]
    assert "权益回落" in item["tags"]
    assert "持续失血" not in item["tags"]

    tag_labels = {tag["label"] for tag in data["tags"]}
    assert "权益回落" in tag_labels
    assert "持续失血" not in tag_labels


def test_review_summary_rejects_invalid_window_and_bucket(tmp_path, monkeypatch) -> None:
    database = LocalDatabase(str(tmp_path / "review-invalid.db"))
    database.init_db()
    client = _client(database, monkeypatch)

    bad_window = client.get("/review/summary?window=90d&bucket=1h")
    assert bad_window.status_code == 400
    assert bad_window.json()["error"]["code"] == "BAD_REQUEST"

    bad_bucket = client.get("/review/summary?window=24h&bucket=5m")
    assert bad_bucket.status_code == 400
    assert bad_bucket.json()["error"]["code"] == "BAD_REQUEST"
