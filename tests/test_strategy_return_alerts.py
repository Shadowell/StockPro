from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.db.local_db as local_db_module  # noqa: E402
import app.services.alert_service as alert_module  # noqa: E402
from app.api.v2.endpoints import monitor  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.alert_service import Alert, AlertService, AlertType  # noqa: E402


class FakeStrategyEngine:
    def __init__(self, statuses: Dict[int, Dict[str, Any]]):
        self.statuses = statuses

    def get_strategy_status(self, strategy_id: int):
        value = self.statuses.get(int(strategy_id))
        return dict(value) if value else None


def _strategy_alert(threshold: float = -5, cooldown: int = 3600) -> Alert:
    return Alert(
        id=1,
        name="策略收益低于阈值",
        type=AlertType.STRATEGY_RETURN_BELOW,
        exchange="okx",
        symbol="strategy:12",
        condition={
            "scope": "strategy",
            "strategy_id": 12,
            "strategy_name": "亏损观察策略",
            "threshold": threshold,
            "cooldown_sec": cooldown,
        },
        notification={},
        cooldown=cooldown,
    )


def _liquidation_alert(threshold: float = 10, cooldown: int = 3600) -> Alert:
    return Alert(
        id=2,
        name="策略爆仓前告警",
        type="strategy_liquidation_risk",
        exchange="okx",
        symbol="strategy:31",
        condition={
            "scope": "strategy",
            "strategy_id": 31,
            "strategy_name": "合约风险观察策略",
            "threshold": threshold,
            "cooldown_sec": cooldown,
            "metric": "liquidation_buffer_pct",
        },
        notification={},
        cooldown=cooldown,
    )


def test_strategy_return_below_triggers(monkeypatch):
    monkeypatch.setattr(
        alert_module,
        "strategy_engine",
        FakeStrategyEngine(
            {
                12: {
                    "strategy_id": 12,
                    "name": "亏损观察策略",
                    "status": "running",
                    "return_pct": -5.1,
                    "equity": 9490,
                    "pnl": -510,
                    "total_trades": 7,
                }
            }
        ),
    )
    service = AlertService()

    event = asyncio.run(service._check_alert(_strategy_alert(threshold=-5)))

    assert event is not None
    assert event.type == "strategy_return_below"
    assert event.value == -5.1
    assert "当前收益率 -5.10%" in event.message
    assert "阈值 -5.00%" in event.message
    assert "成交数: 7" in event.message


def test_strategy_return_below_skips_above_threshold(monkeypatch):
    monkeypatch.setattr(
        alert_module,
        "strategy_engine",
        FakeStrategyEngine({12: {"status": "running", "return_pct": -4.9}}),
    )
    service = AlertService()

    event = asyncio.run(service._check_alert(_strategy_alert(threshold=-5)))

    assert event is None


def test_strategy_return_below_skips_missing_or_not_running(monkeypatch):
    service = AlertService()
    monkeypatch.setattr(alert_module, "strategy_engine", FakeStrategyEngine({}))
    assert asyncio.run(service._check_alert(_strategy_alert())) is None

    monkeypatch.setattr(
        alert_module,
        "strategy_engine",
        FakeStrategyEngine({12: {"status": "paused", "return_pct": -10}}),
    )
    assert asyncio.run(service._check_alert(_strategy_alert())) is None


def test_strategy_return_below_cooldown():
    service = AlertService()
    alert = _strategy_alert(cooldown=3600)
    now = datetime(2026, 5, 3, 8, 0, 0)
    alert.last_triggered_at = now

    assert service._cooldown_active(alert, now + timedelta(minutes=30)) is True
    assert service._cooldown_active(alert, now + timedelta(minutes=61)) is False


def test_create_strategy_return_below_alert_api(monkeypatch, tmp_path):
    database = LocalDatabase(str(tmp_path / "alerts.db"))
    database.init_db()
    strategy_id = database.save_strategy(
        name="亏损观察策略",
        script_content="class Demo: pass",
        config={"is_paper_trading": True},
        exchange="okx",
        symbols=["BTC/USDT"],
    )
    database.set_feishu_webhook_url("https://open.feishu.cn/open-apis/bot/v2/hook/test-token")
    service = AlertService()
    monkeypatch.setattr(local_db_module, "db_instance", database)
    monkeypatch.setattr(alert_module, "db", database)
    monkeypatch.setattr(monitor, "alert_service", service)

    app = FastAPI()
    app.include_router(monitor.router, prefix="/api/v2/monitor")
    register_exception_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v2/monitor/alerts",
        json={
            "name": "策略收益低于 -5%",
            "type": "strategy_return_below",
            "strategy_id": strategy_id,
            "threshold": -5,
            "cooldown_sec": 3600,
        },
    )

    assert response.status_code == 200
    alerts = service.get_alerts()
    assert len(alerts) == 1
    condition = alerts[0]["condition"]
    assert condition["scope"] == "strategy"
    assert condition["strategy_id"] == strategy_id
    assert condition["threshold"] == -5
    assert condition["cooldown_sec"] == 3600
    assert condition["strategy_name"] == "亏损观察策略"
    saved_alert = next(iter(service._alerts.values()))
    assert "webhook" not in saved_alert.notification


def test_strategy_liquidation_risk_triggers_when_buffer_below_threshold(monkeypatch):
    monkeypatch.setattr(
        alert_module,
        "strategy_engine",
        FakeStrategyEngine(
            {
                31: {
                    "strategy_id": 31,
                    "name": "合约风险观察策略",
                    "status": "running",
                    "positions": {
                        "BTC/USDT:USDT:long": {
                            "symbol": "BTC/USDT:USDT",
                            "pos_side": "long",
                            "contracts": 2,
                            "mark_price": 100,
                            "liq_price": 93,
                            "leverage": 5,
                            "unrealized_pnl": -42,
                        }
                    },
                }
            }
        ),
    )
    service = AlertService()

    event = asyncio.run(service._check_alert(_liquidation_alert(threshold=10)))

    assert event is not None
    assert event.type == "strategy_liquidation_risk"
    assert event.value == 7
    assert "爆仓距离 7.00%" in event.message
    assert "阈值 10.00%" in event.message
    assert "强平价: 93.00 USDT" in event.message
    assert "BTC/USDT:USDT long" in event.message


def test_strategy_liquidation_risk_skips_safe_or_without_liq_price(monkeypatch):
    service = AlertService()
    monkeypatch.setattr(
        alert_module,
        "strategy_engine",
        FakeStrategyEngine(
            {
                31: {
                    "status": "running",
                    "positions": {
                        "BTC/USDT:USDT:short": {
                            "symbol": "BTC/USDT:USDT",
                            "pos_side": "short",
                            "mark_price": 100,
                            "liq_price": 130,
                        }
                    },
                }
            }
        ),
    )
    assert asyncio.run(service._check_alert(_liquidation_alert(threshold=10))) is None

    monkeypatch.setattr(
        alert_module,
        "strategy_engine",
        FakeStrategyEngine(
            {
                31: {
                    "status": "running",
                    "positions": {
                        "BTC/USDT:USDT:long": {
                            "symbol": "BTC/USDT:USDT",
                            "pos_side": "long",
                            "mark_price": 100,
                        }
                    },
                }
            }
        ),
    )
    assert asyncio.run(service._check_alert(_liquidation_alert(threshold=10))) is None


def test_create_strategy_liquidation_risk_alert_api(monkeypatch, tmp_path):
    database = LocalDatabase(str(tmp_path / "liquidation-alerts.db"))
    database.init_db()
    strategy_id = database.save_strategy(
        name="[合约] 合约风险观察策略",
        script_content="class Demo: pass",
        config={"is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    service = AlertService()
    monkeypatch.setattr(local_db_module, "db_instance", database)
    monkeypatch.setattr(alert_module, "db", database)
    monkeypatch.setattr(monitor, "alert_service", service)

    app = FastAPI()
    app.include_router(monitor.router, prefix="/api/v2/monitor")
    register_exception_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v2/monitor/alerts",
        json={
            "name": "爆仓距离低于 10%",
            "type": "strategy_liquidation_risk",
            "strategy_id": strategy_id,
            "threshold": 10,
            "cooldown_sec": 3600,
        },
    )

    assert response.status_code == 200
    alerts = service.get_alerts()
    assert len(alerts) == 1
    condition = alerts[0]["condition"]
    assert condition["scope"] == "strategy"
    assert condition["strategy_id"] == strategy_id
    assert condition["strategy_name"] == "[合约] 合约风险观察策略"
    assert condition["threshold"] == 10
    assert condition["cooldown_sec"] == 3600
    assert condition["metric"] == "liquidation_buffer_pct"
