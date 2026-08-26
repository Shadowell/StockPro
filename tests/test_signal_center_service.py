import asyncio
import sys
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.local_db import LocalDatabase
from app.services.signal_center_service import (
    SignalCenterService,
    okx_inst_id_from_contract_symbol,
)


def make_service(tmp_path: Path) -> SignalCenterService:
    return SignalCenterService(db=LocalDatabase(str(tmp_path / "signals.db")))


def test_contract_signal_builds_okx_payload_preview_and_dedupes(tmp_path):
    service = make_service(tmp_path)
    service.set_strategy_signal_enabled(7, True)

    signal = service.record_contract_paper_signal(
        strategy_id=7,
        strategy_name="[合约] Demo",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        price=50_000.0,
        margin=200.0,
        notional_usdt=1_000.0,
        leverage=5.0,
        ratio=None,
        bar_ts_ms=1_714_000_000_000,
        reason="breakout confirmed",
        confidence="high",
        risk_note="paper signal only",
        raw_context={"source": "test"},
    )
    duplicate = service.record_contract_paper_signal(
        strategy_id=7,
        strategy_name="[合约] Demo",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        price=50_000.0,
        margin=200.0,
        notional_usdt=1_000.0,
        leverage=5.0,
        ratio=None,
        bar_ts_ms=1_714_000_000_000,
    )

    assert okx_inst_id_from_contract_symbol("BTC/USDT:USDT") == "BTC-USDT-SWAP"
    assert okx_inst_id_from_contract_symbol("SPACEX/USDT:USDT") == "SPCX-USDT-SWAP"
    assert signal["id"] == duplicate["id"]
    assert signal["action"] == "ENTER_LONG"
    assert signal["okx_inst_id"] == "BTC-USDT-SWAP"
    assert signal["suggested_investment_type"] == "percentage_balance"
    assert signal["suggested_amount"] == pytest.approx(100.0)
    assert signal["status"] == "pending_approval"
    assert signal["okx_payload_preview"]["action"] == "ENTER_LONG"
    assert signal["okx_payload_preview"]["instrument"] == "BTC-USDT-SWAP"
    assert signal["okx_payload_preview"]["maxLag"] == "30"
    assert signal["okx_payload_preview"]["orderType"] == "market"
    assert signal["okx_payload_preview"]["orderPriceOffset"] == ""
    assert signal["okx_payload_preview"]["investmentType"] == "percentage_balance"
    assert signal["okx_payload_preview"]["amount"] == "100"
    assert signal["okx_payload_preview"]["signalToken"] == "<channel-signal-token>"


def test_contract_close_signal_uses_okx_exit_payload_format(tmp_path):
    service = make_service(tmp_path)
    service.set_strategy_signal_enabled(7, True)

    signal = service.record_contract_paper_signal(
        strategy_id=7,
        strategy_name="[合约] Demo",
        symbol="BTC/USDT:USDT",
        action="close",
        side="long",
        price=50_000.0,
        margin=0.0,
        notional_usdt=1_000.0,
        leverage=5.0,
        ratio=0.5,
        bar_ts_ms=1_714_000_000_001,
    )

    assert signal["action"] == "EXIT_LONG"
    assert signal["risk_note"] == ""
    assert signal["suggested_investment_type"] == "percentage_position"
    assert signal["suggested_amount"] == pytest.approx(50.0)
    assert signal["okx_payload_preview"] == {
        "action": "EXIT_LONG",
        "instrument": "BTC-USDT-SWAP",
        "signalToken": "<channel-signal-token>",
        "timestamp": signal["okx_payload_preview"]["timestamp"],
        "maxLag": "30",
        "orderType": "market",
        "orderPriceOffset": "",
        "investmentType": "percentage_position",
        "amount": "50",
    }


def test_legacy_default_risk_note_is_hidden_when_listing_signals(tmp_path):
    service = make_service(tmp_path)
    service.set_strategy_signal_enabled(7, True)

    signal = service.record_contract_paper_signal(
        strategy_id=7,
        strategy_name="[合约] Demo",
        symbol="BTC/USDT:USDT",
        action="open",
        side="short",
        price=50_000.0,
        margin=200.0,
        notional_usdt=1_000.0,
        leverage=5.0,
        bar_ts_ms=1_714_000_000_002,
        risk_note="人工确认后才会推送 OKX Signal Bot；BitPro 不直接通过交易 API 下单。",
    )

    assert signal["risk_note"] == ""
    assert service.list_signals(strategy_id=7)[0]["risk_note"] == ""


def test_channel_approval_masks_secret_and_sends_okx_payload(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    service.set_strategy_signal_enabled(7, True)
    signal = service.record_contract_paper_signal(
        strategy_id=7,
        strategy_name="[合约] Demo",
        symbol="ETH/USDT:USDT",
        action="open",
        side="short",
        price=3_000.0,
        margin=120.0,
        notional_usdt=600.0,
        leverage=5.0,
        bar_ts_ms=1_714_000_000_000,
    )
    channel = service.create_channel(
        {
            "name": "内部Bot-A",
            "webhook_url": "https://example.test/okx-signal",
            "signal_token": "super-secret-token",
            "allowed_strategy_ids": [7],
            "allowed_symbols": ["ETH/USDT:USDT"],
            "allowed_actions": ["ENTER_SHORT"],
            "max_margin_usdt": 200,
            "max_lag_sec": 45,
        }
    )

    sent_payloads = []

    async def fake_post(webhook_url, payload):
        sent_payloads.append((webhook_url, payload))
        return {"status_code": 200, "body": "ok"}

    monkeypatch.setattr(service, "_post_webhook", fake_post)
    approved = asyncio.run(service.approve_signal(signal["id"], [channel["id"]]))

    listed_channel = service.list_channels()[0]
    assert listed_channel["webhook_url"] == "https://example.test/okx-signal"
    assert listed_channel["masked_webhook_url"].startswith("https://example.test")
    assert listed_channel["signal_token"] == "********oken"
    assert "super-secret-token" not in str(listed_channel)
    assert approved["status"] == "sent"
    assert approved["deliveries"][0]["status"] == "sent"
    assert sent_payloads == [
        (
            "https://example.test/okx-signal",
            {
                "action": "ENTER_SHORT",
                "instrument": "ETH-USDT-SWAP",
                "signalToken": "super-secret-token",
                "timestamp": signal["okx_payload_preview"]["timestamp"],
                "maxLag": "45",
                "orderType": "market",
                "orderPriceOffset": "",
                "investmentType": "percentage_balance",
                "amount": "100",
            },
        )
    ]


def test_strategy_signal_auto_sends_by_default(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    enabled = service.set_strategy_signal_enabled(7, True)
    assert enabled["signal_enabled"] is True
    assert enabled["manual_approval_required"] is False
    channel = service.create_channel(
        {
            "name": "自动发送Bot",
            "webhook_url": "https://example.test/auto",
            "signal_token": "auto-secret-token",
            "allowed_strategy_ids": [7],
            "allowed_actions": ["ENTER_LONG"],
            "max_margin_usdt": 200,
        }
    )
    sent_payloads = []

    async def fake_post(webhook_url, payload):
        sent_payloads.append((webhook_url, payload))
        return {"status_code": 200, "body": "ok"}

    monkeypatch.setattr(service, "_post_webhook", fake_post)

    signal = service.record_contract_paper_signal(
        strategy_id=7,
        strategy_name="[合约] Demo",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        price=50_000.0,
        margin=100.0,
        notional_usdt=500.0,
        leverage=5.0,
        bar_ts_ms=1_714_000_000_003,
    )

    assert signal["status"] == "sent"
    assert signal["deliveries"][0]["channel_id"] == channel["id"]
    assert signal["deliveries"][0]["status"] == "sent"
    assert sent_payloads == [
        (
            "https://example.test/auto",
            {
                "action": "ENTER_LONG",
                "instrument": "BTC-USDT-SWAP",
                "signalToken": "auto-secret-token",
                "timestamp": signal["okx_payload_preview"]["timestamp"],
                "maxLag": "30",
                "orderType": "market",
                "orderPriceOffset": "",
                "investmentType": "percentage_balance",
                "amount": "100",
            },
        )
    ]


def test_strategy_signal_manual_approval_switch_blocks_auto_send(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    setting = service.update_strategy_signal_settings(
        7,
        enabled=True,
        manual_approval_required=True,
    )
    assert setting["signal_enabled"] is True
    assert setting["manual_approval_required"] is True
    service.create_channel(
        {
            "name": "人工确认Bot",
            "webhook_url": "https://example.test/manual",
            "signal_token": "manual-secret-token",
            "allowed_strategy_ids": [7],
            "allowed_actions": ["ENTER_LONG"],
            "max_margin_usdt": 200,
        }
    )

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("webhook must not be called when manual approval is required")

    monkeypatch.setattr(service, "_post_webhook", fail_if_called)

    signal = service.record_contract_paper_signal(
        strategy_id=7,
        strategy_name="[合约] Demo",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        price=50_000.0,
        margin=100.0,
        notional_usdt=500.0,
        leverage=5.0,
        bar_ts_ms=1_714_000_000_004,
    )

    assert signal["status"] == "pending_approval"
    assert signal["deliveries"] == []


def test_channel_dry_run_uses_okx_custom_json_payload(tmp_path):
    service = make_service(tmp_path)
    channel = service.create_channel(
        {
            "name": "内部Bot-Test",
            "webhook_url": "https://example.test/okx-signal",
            "signal_token": "super-secret-token",
            "max_lag_sec": 300,
        }
    )

    result = asyncio.run(service.test_channel(channel["id"], send=False))

    assert result["status"] == "dry_run"
    assert result["payload"] == {
        "action": "ENTER_LONG",
        "instrument": "DOGE-USDT-SWAP",
        "signalToken": "<redacted>",
        "timestamp": result["payload"]["timestamp"],
        "maxLag": "300",
        "orderType": "market",
        "orderPriceOffset": "",
        "investmentType": "margin",
        "amount": "0.1",
    }


def test_channel_real_test_sends_small_doge_margin_payload(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    channel = service.create_channel(
        {
            "name": "真实测试Bot",
            "enabled": True,
            "webhook_url": "https://example.test/okx-signal",
            "signal_token": "real-secret-token",
            "max_lag_sec": 30,
        }
    )
    sent_payloads = []

    async def fake_post(url, payload):
        sent_payloads.append((url, payload))
        return {"status_code": 200, "body": "ok"}

    monkeypatch.setattr(service, "_post_webhook", fake_post)

    result = asyncio.run(service.test_channel(channel["id"], send=True))

    assert result["status"] == "sent"
    assert result["payload"]["signalToken"] == "<redacted>"
    assert sent_payloads == [
        (
            "https://example.test/okx-signal",
            {
                "action": "ENTER_LONG",
                "instrument": "DOGE-USDT-SWAP",
                "signalToken": "real-secret-token",
                "timestamp": sent_payloads[0][1]["timestamp"],
                "maxLag": "30",
                "orderType": "market",
                "orderPriceOffset": "",
                "investmentType": "margin",
                "amount": "0.1",
            },
        )
    ]


def test_channel_real_test_network_error_returns_failed_result(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    channel = service.create_channel(
        {
            "name": "连接失败测试Bot",
            "enabled": True,
            "webhook_url": "https://example.test/okx-signal",
            "signal_token": "real-secret-token",
            "max_lag_sec": 30,
        }
    )

    async def fail_post(_url, _payload):
        raise httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(service, "_post_webhook", fail_post)

    result = asyncio.run(service.test_channel(channel["id"], send=True))

    assert result["status"] == "failed"
    assert result["response_status"] is None
    assert "ConnectError: All connection attempts failed" in result["response_body"]
    assert result["payload"]["signalToken"] == "<redacted>"


def test_channel_defaults_use_low_margin_and_30_second_lag(tmp_path):
    service = make_service(tmp_path)
    service.set_strategy_signal_enabled(7, True)

    channel = service.create_channel(
        {
            "name": "默认风控Bot",
            "webhook_url": "https://example.test/defaults",
            "signal_token": "default-secret",
        }
    )
    signal = service.record_contract_paper_signal(
        strategy_id=7,
        strategy_name="[合约] Demo",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        price=50_000.0,
        margin=12.0,
        notional_usdt=60.0,
        leverage=5.0,
        bar_ts_ms=1_714_000_000_123,
    )
    dry_run = asyncio.run(service.test_channel(channel["id"], send=False))

    assert channel["max_margin_usdt"] == pytest.approx(10.0)
    assert channel["max_lag_sec"] == 30
    assert signal["okx_payload_preview"]["maxLag"] == "30"
    assert dry_run["payload"]["maxLag"] == "30"


def test_expired_signal_and_channel_margin_limit_block_delivery(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    service.set_strategy_signal_enabled(8, True)
    signal = service.record_contract_paper_signal(
        strategy_id=8,
        strategy_name="[合约] Demo",
        symbol="SOL/USDT:USDT",
        action="open",
        side="long",
        price=150.0,
        margin=300.0,
        notional_usdt=900.0,
        leverage=3.0,
        bar_ts_ms=1_714_000_000_000,
    )
    blocked_channel = service.create_channel(
        {
            "name": "低额度Bot",
            "webhook_url": "https://example.test/low",
            "signal_token": "low-secret",
            "allowed_strategy_ids": [8],
            "allowed_symbols": ["SOL/USDT:USDT"],
            "allowed_actions": ["ENTER_LONG"],
            "max_margin_usdt": 100,
        }
    )

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("webhook must not be called when validation fails")

    monkeypatch.setattr(service, "_post_webhook", fail_if_called)
    result = asyncio.run(service.approve_signal(signal["id"], [blocked_channel["id"]]))
    assert result["status"] == "failed"
    assert result["deliveries"][0]["status"] == "failed"
    assert "超过通道最大保证金" in result["deliveries"][0]["error"]

    service.db.get_connection().execute(
        "UPDATE strategy_signals SET expires_at = '2000-01-01T00:00:00' WHERE id = ?",
        (signal["id"],),
    )
    with pytest.raises(ValueError, match="信号已过期"):
        asyncio.run(service.approve_signal(signal["id"], [blocked_channel["id"]]))


def test_delete_channel_removes_config_and_cancels_unsent_deliveries(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    service.set_strategy_signal_enabled(8, True)
    signal = service.record_contract_paper_signal(
        strategy_id=8,
        strategy_name="[合约] Demo",
        symbol="SOL/USDT:USDT",
        action="open",
        side="long",
        price=150.0,
        margin=300.0,
        notional_usdt=900.0,
        leverage=3.0,
        bar_ts_ms=1_714_000_000_000,
    )
    channel = service.create_channel(
        {
            "name": "待删除Bot",
            "webhook_url": "https://example.test/delete-me",
            "signal_token": "delete-secret",
            "allowed_strategy_ids": [8],
            "allowed_symbols": ["SOL/USDT:USDT"],
            "allowed_actions": ["ENTER_LONG"],
            "max_margin_usdt": 100,
        }
    )

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("webhook must not be called when validation fails")

    monkeypatch.setattr(service, "_post_webhook", fail_if_called)
    failed = asyncio.run(service.approve_signal(signal["id"], [channel["id"]]))
    assert failed["deliveries"][0]["status"] == "failed"

    deleted = service.delete_channel(channel["id"])

    assert deleted == {
        "deleted": True,
        "channel_id": channel["id"],
        "channel_name": "待删除Bot",
        "canceled_deliveries": 1,
    }
    assert service.list_channels() == []
    assert service.get_signal(signal["id"])["deliveries"][0]["status"] == "canceled"
    with pytest.raises(ValueError, match="信号通道不存在"):
        service.delete_channel(channel["id"])


def test_signal_strategy_payload_includes_runtime_profit_metrics(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    conn = service.db.get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY,
            name TEXT,
            status TEXT,
            exchange TEXT,
            symbols TEXT,
            config TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO strategies (id, name, status, exchange, symbols, config)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            7,
            "[合约] Demo",
            "running",
            "okx",
            '["BTC/USDT:USDT"]',
            '{"market_type":"swap"}',
        ),
    )
    conn.commit()
    service.set_strategy_signal_enabled(7, True)
    monkeypatch.setattr(
        service,
        "_runtime_strategy_metrics",
        lambda strategy_id: {"total_pnl": 123.45, "return_pct": 1.2345},
    )

    listed = service.list_signal_strategies()

    assert listed[0]["strategy_id"] == 7
    assert listed[0]["total_pnl"] == pytest.approx(123.45)
    assert listed[0]["return_pct"] == pytest.approx(1.2345)


def test_contract_signal_generation_requires_enabled_strategy(tmp_path):
    service = make_service(tmp_path)

    skipped = service.record_contract_paper_signal(
        strategy_id=42,
        strategy_name="[合约] Not Selected",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        price=50_000.0,
        margin=100.0,
        notional_usdt=500.0,
        leverage=5.0,
        bar_ts_ms=1_714_000_000_000,
    )
    assert skipped is None
    assert service.list_signals(limit=10) == []

    enabled = service.set_strategy_signal_enabled(42, True)
    assert enabled["signal_enabled"] is True
    signal = service.record_contract_paper_signal(
        strategy_id=42,
        strategy_name="[合约] Selected",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        price=50_000.0,
        margin=100.0,
        notional_usdt=500.0,
        leverage=5.0,
        bar_ts_ms=1_714_000_000_001,
    )
    assert signal is not None
    assert signal["status"] == "pending_approval"

    disabled = service.set_strategy_signal_enabled(42, False)
    assert disabled["signal_enabled"] is False
    assert service.get_signal(signal["id"])["status"] == "canceled"
    assert service.record_contract_paper_signal(
        strategy_id=42,
        strategy_name="[合约] Selected",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        price=50_000.0,
        margin=100.0,
        notional_usdt=500.0,
        leverage=5.0,
        bar_ts_ms=1_714_000_000_002,
    ) is None


def test_signal_center_service_does_not_import_real_trading_service():
    source = (BACKEND / "app" / "services" / "signal_center_service.py").read_text(encoding="utf-8")

    assert "trading_service" not in source
    assert "LiveBroker" not in source
