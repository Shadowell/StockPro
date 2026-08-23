from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402
from app.api import public as public_api  # noqa: E402
from app.api.v2.endpoints import settings as settings_endpoint  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402


class FakeStrategyEngine:
    def get_strategy_status(self, strategy_id: int) -> dict | None:
        if strategy_id != 17:
            return None
        return {
            "status": "running",
            "equity": 102.4,
            "initial_capital": 100.0,
            "total_trades": 2,
            "positions": {},
        }


def _paper_strategy(database: LocalDatabase) -> None:
    database.init_db()
    now = datetime.now(timezone.utc)
    started_at = now - timedelta(hours=1)
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO strategies (id, name, description, script_content, config, status, exchange, symbols)
        VALUES (17, ?, '', '', ?, 'running', 'okx', ?)
        """,
        (
            "[合约][4H][CTA] BTC · 公开卡片测试 · 100U",
            '{"initial_capital":100,"is_paper_trading":true,"taker_fee_bps":5,"slippage_bps":2}',
            '["BTC/USDT:USDT","ETH/USDT:USDT"]',
        ),
    )
    conn.commit()
    database.close_connection()
    row = database.get_strategy_by_id(17)
    instance = database.create_paper_instance(
        strategy_id=17,
        strategy_version="sha256:public-card-strategy",
        config_version="sha256:public-card-config",
        config_snapshot=row["config"],
        configured_at=started_at.isoformat(),
    )
    database.mark_paper_instance_started(instance["instance_id"], started_at.isoformat())
    config = dict(row["config"])
    config["paper_instance_id"] = instance["instance_id"]
    database.update_strategy_config(17, config)
    for minutes, equity in ((0, 100.0), (30, 104.0), (60, 102.4)):
        at = started_at + timedelta(minutes=minutes)
        database.insert_strategy_equity_sample(17, int(at.timestamp() * 1000), equity)
    for minutes, pnl in ((35, 2.0), (50, -1.0)):
        at = started_at + timedelta(minutes=minutes)
        database.insert_strategy_trade(
            17,
            {
                "exchange": "okx",
                "symbol": "BTC/USDT:USDT",
                "timestamp": int(at.timestamp() * 1000),
                "side": "close_long",
                "type": "market",
                "price": 100000,
                "quantity": 0.001,
                "pnl": pnl,
            },
        )


def test_unconfigured_public_card_returns_safe_json_without_internal_identity() -> None:
    response = TestClient(app).get("/api/public/v1/strategy-cards/github-profile")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, max-age=60"
    assert response.headers["x-strategy-card-state"] == "unavailable"
    payload = response.json()
    assert payload == {
        "schema_version": 1,
        "state": "unavailable",
        "mode": "paper",
        "data": None,
        "as_of": payload["as_of"],
    }
    serialized = response.text.lower()
    assert "strategy_id" not in serialized
    assert "instance_id" not in serialized
    assert "strategy_name" not in serialized


def test_admin_mapping_switches_alias_to_a_valid_paper_strategy(monkeypatch, tmp_path) -> None:
    database = LocalDatabase(str(tmp_path / "public-card.db"))
    _paper_strategy(database)
    monkeypatch.setattr(settings_endpoint, "db", database)
    monkeypatch.setattr(public_api, "db", database, raising=False)
    monkeypatch.setattr(public_api, "strategy_engine", FakeStrategyEngine(), raising=False)

    response = TestClient(app).put(
        "/api/v2/settings/public-strategy-cards/github-profile",
        json={"strategy_id": 17},
    )

    assert response.status_code == 200
    assert response.json() == {
        "alias": "github-profile",
        "strategy_id": 17,
        "mode": "paper",
        "configured": True,
    }


def test_public_card_returns_live_paper_metrics_without_internal_identity(monkeypatch, tmp_path) -> None:
    database = LocalDatabase(str(tmp_path / "public-card.db"))
    _paper_strategy(database)
    monkeypatch.setattr(settings_endpoint, "db", database)
    monkeypatch.setattr(public_api, "db", database, raising=False)
    monkeypatch.setattr(public_api, "strategy_engine", FakeStrategyEngine(), raising=False)
    client = TestClient(app)
    configured = client.put(
        "/api/v2/settings/public-strategy-cards/github-profile",
        json={"strategy_id": 17},
    )
    assert configured.status_code == 200

    response = client.get("/api/public/v1/strategy-cards/github-profile")

    assert response.status_code == 200
    assert response.headers["x-strategy-card-state"] == "ok"
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["state"] == "ok"
    assert payload["mode"] == "paper"
    data = payload["data"]
    assert data["status"] == "running"
    assert data["currency"] == "USDT"
    assert data["account_equity"] == 102.4
    assert data["total_pnl"] == 2.4
    assert data["return_pct"] == 2.4
    assert data["win_rate_pct"] == 50.0
    assert data["profit_factor"] == 2.0
    assert data["trade_count"] == 2
    assert data["max_drawdown_30d_pct"] == 1.538462
    assert 3500 <= data["runtime_seconds"] <= 3700
    assert data["symbols"] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert [point["value"] for point in data["equity_curve"]] == [100.0, 104.0, 102.4]
    assert [point["value_pct"] for point in data["drawdown_curve"]] == [0.0, 0.0, -1.538462]
    assert data["includes_fees"] is True
    assert data["includes_slippage"] is True
    serialized = response.text.lower()
    assert "strategy_id" not in serialized
    assert "instance_id" not in serialized
    assert "公开卡片测试" not in serialized


def test_public_card_allows_shadowell_pages_and_reuses_etag_for_unchanged_metrics(monkeypatch, tmp_path) -> None:
    database = LocalDatabase(str(tmp_path / "public-card.db"))
    _paper_strategy(database)
    monkeypatch.setattr(settings_endpoint, "db", database)
    monkeypatch.setattr(public_api, "db", database, raising=False)
    monkeypatch.setattr(public_api, "strategy_engine", FakeStrategyEngine(), raising=False)
    client = TestClient(app)
    assert client.put(
        "/api/v2/settings/public-strategy-cards/github-profile",
        json={"strategy_id": 17},
    ).status_code == 200

    first = client.get(
        "/api/public/v1/strategy-cards/github-profile",
        headers={"Origin": "https://shadowell.github.io"},
    )
    second = client.get(
        "/api/public/v1/strategy-cards/github-profile",
        headers={"Origin": "https://shadowell.github.io"},
    )

    assert first.headers["access-control-allow-origin"] == "https://shadowell.github.io"
    assert first.headers["etag"] == second.headers["etag"]


def test_invalid_switch_keeps_the_previous_public_mapping(monkeypatch, tmp_path) -> None:
    database = LocalDatabase(str(tmp_path / "public-card.db"))
    _paper_strategy(database)
    monkeypatch.setattr(settings_endpoint, "db", database)
    monkeypatch.setattr(public_api, "db", database, raising=False)
    monkeypatch.setattr(public_api, "strategy_engine", FakeStrategyEngine(), raising=False)
    client = TestClient(app)
    assert client.put(
        "/api/v2/settings/public-strategy-cards/github-profile",
        json={"strategy_id": 17},
    ).status_code == 200

    rejected = client.put(
        "/api/v2/settings/public-strategy-cards/github-profile",
        json={"strategy_id": 999},
    )

    assert rejected.status_code == 400
    assert client.get("/api/public/v1/strategy-cards/github-profile").json()["state"] == "ok"


def test_public_read_bypasses_login_but_mapping_change_requires_auth(monkeypatch) -> None:
    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True)
    client = TestClient(app)

    assert client.get("/api/public/v1/strategy-cards/github-profile").status_code == 200
    protected = client.put(
        "/api/v2/settings/public-strategy-cards/github-profile",
        json={"strategy_id": 17},
    )
    assert protected.status_code == 401
