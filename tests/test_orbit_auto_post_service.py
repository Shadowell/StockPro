from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.services.orbit_auto_post_service as orbit_service_module  # noqa: E402
from app.services.orbit_auto_post_service import BrowserOrbitPublisher, OrbitAutoPostService  # noqa: E402


class MemorySettingsDB:
    def __init__(self) -> None:
        self.settings: dict[str, str | None] = {}

    def get_app_setting(self, key: str, default: str | None = None) -> str | None:
        return self.settings.get(key, default)

    def set_app_setting(self, key: str, value: str | None) -> None:
        self.settings[key] = value


class FakeAccountService:
    def list_accounts(self):
        return [
            {
                "account_id": "default",
                "name": "默认 OKX 实盘账户",
                "enabled": True,
                "configured": True,
            }
        ]

    def exchange_alias_for_account(self, account_id: str) -> str:
        return f"okx:{account_id}"


class FakeTradingService:
    def __init__(self) -> None:
        self.position_requests = 0

    async def get_positions(self, exchange_name: str, symbol: str | None = None):
        self.position_requests += 1
        assert exchange_name == "okx:default"
        return [
            {
                "symbol": "SPCX/USDT:USDT",
                "side": "short",
                "contracts": "0.02",
                "entry_price": "2113",
                "mark_price": "2105.2",
                "unrealized_pnl": "0.72",
                "margin": "8.4",
                "leverage": "5",
            },
            {
                "symbol": "BTC/USDT:USDT",
                "side": "long",
                "contracts": "0.001",
                "entry_price": "80000",
                "mark_price": "80100",
                "unrealized_pnl": "0.05",
                "margin": "10",
                "leverage": "5",
            },
        ]


class FakePublisher:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    async def publish(self, payload: dict) -> dict:
        self.posts.append(payload)
        return {"status": "published", "url": "https://www.okx.com/zh-hans/orbit/post/test"}

    async def status(self) -> dict:
        return {"available": True, "logged_in": True, "mode": "fake"}


def test_orbit_auto_post_filters_live_swap_positions_by_margin_roi_and_cooldown() -> None:
    db = MemorySettingsDB()
    publisher = FakePublisher()
    service = OrbitAutoPostService(
        database=db,
        account_service=FakeAccountService(),
        trading_service=FakeTradingService(),
        publisher=publisher,
        now_fn=lambda: datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
        llm_enabled_fn=lambda: False,
    )
    service.update_config(
        {
            "enabled": True,
            "account_id": "default",
            "min_margin_roi_pct": 5,
            "max_posts_per_run": 1,
            "cooldown_hours": 24,
        }
    )

    candidates = asyncio.run(service.preview_candidates())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["symbol"] == "SPCX/USDT:USDT"
    assert candidate["side"] == "short"
    assert candidate["margin_roi_pct"] > 8.5
    assert candidate["eligible"] is True

    first = asyncio.run(service.run_once(force=True))
    assert first["posted_count"] == 1
    assert publisher.posts[0]["candidate"]["symbol"] == "SPCX/USDT:USDT"
    assert "不构成投资建议" in publisher.posts[0]["content"]

    second = asyncio.run(service.run_once(force=False))
    assert second["posted_count"] == 0
    assert second["skipped"] == "no_eligible_candidates"
    assert "cooldown" in second["candidates"][0]["blocked_reason"]


def test_orbit_auto_post_config_defaults_are_single_account_truthful_mode() -> None:
    service = OrbitAutoPostService(
        database=MemorySettingsDB(),
        account_service=FakeAccountService(),
        trading_service=FakeTradingService(),
    )

    config = service.get_config()

    assert config["enabled"] is False
    assert config["account_id"] == "default"
    assert config["min_margin_roi_pct"] == 5.0
    assert config["max_posts_per_run"] == 1
    assert config["publish_mode"] == "orbit_web"
    assert config["truthful_only"] is True


def test_orbit_candidate_preview_reuses_short_lived_position_snapshot() -> None:
    trading_service = FakeTradingService()
    service = OrbitAutoPostService(
        database=MemorySettingsDB(),
        account_service=FakeAccountService(),
        trading_service=trading_service,
        llm_enabled_fn=lambda: False,
    )

    first = asyncio.run(service.preview_candidates())
    second = asyncio.run(service.preview_candidates())

    assert second == first
    assert trading_service.position_requests == 1


def test_orbit_candidate_preview_can_force_fresh_positions() -> None:
    trading_service = FakeTradingService()
    service = OrbitAutoPostService(
        database=MemorySettingsDB(),
        account_service=FakeAccountService(),
        trading_service=trading_service,
        llm_enabled_fn=lambda: False,
    )

    asyncio.run(service.preview_candidates())
    asyncio.run(service.preview_candidates(force_refresh=True))

    assert trading_service.position_requests == 2


def test_orbit_publish_scan_does_not_reuse_preview_position_cache() -> None:
    class MutableTradingService:
        def __init__(self) -> None:
            self.position_requests = 0
            self.positions = [
                {
                    "symbol": "SPCX/USDT:USDT",
                    "side": "short",
                    "contracts": "0.02",
                    "entry_price": "2113",
                    "mark_price": "2105.2",
                    "unrealized_pnl": "0.72",
                    "margin": "8.4",
                    "leverage": "5",
                }
            ]

        async def get_positions(self, exchange_name: str, symbol: str | None = None):
            self.position_requests += 1
            return list(self.positions)

    trading_service = MutableTradingService()
    service = OrbitAutoPostService(
        database=MemorySettingsDB(),
        account_service=FakeAccountService(),
        trading_service=trading_service,
        publisher=FakePublisher(),
        llm_enabled_fn=lambda: False,
    )
    asyncio.run(service.preview_candidates())
    trading_service.positions = []

    result = asyncio.run(service.run_once(force=True))

    assert result["posted_count"] == 0
    assert result["skipped"] == "no_eligible_candidates"
    assert trading_service.position_requests == 2


def test_browser_publisher_drops_broken_proxy_environment(monkeypatch) -> None:
    captured: dict[str, dict[str, str]] = {}

    def fake_run(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout='{"status":"ready","available":true}', stderr="")

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setattr(orbit_service_module.subprocess, "run", fake_run)

    result = asyncio.run(BrowserOrbitPublisher(command="node fake.js").status())

    assert result["status"] == "ready"
    assert "HTTP_PROXY" not in captured["env"]
    assert "HTTPS_PROXY" not in captured["env"]
    assert "ALL_PROXY" not in captured["env"]
    assert captured["env"]["NO_PROXY"] == "*"
