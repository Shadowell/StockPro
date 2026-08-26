import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import signals
from app.core.errors import register_exception_handlers


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(signals.router, prefix="/api/v2")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_signal_center_api_lists_signals_and_channels(monkeypatch):
    class FakeService:
        def list_signals(self, **kwargs):
            assert kwargs["status"] == "pending_approval"
            return [
                {
                    "id": 1,
                    "action": "ENTER_LONG",
                    "symbol": "BTC/USDT:USDT",
                    "status": "pending_approval",
                }
            ]

        def list_channels(self):
            return [
                {
                    "id": 2,
                    "name": "内部Bot-A",
                    "enabled": True,
                    "masked_webhook_url": "https://example.test/***",
                    "signal_token": "********oken",
                }
            ]

        def list_signal_strategies(self):
            return [
                {
                    "strategy_id": 7,
                    "strategy_name": "[合约] Demo",
                    "signal_enabled": True,
                }
            ]

    monkeypatch.setattr(signals, "signal_center_service", FakeService())
    client = build_client()

    signal_res = client.get("/api/v2/signals?status=pending_approval&limit=20")
    channel_res = client.get("/api/v2/signal-channels")
    strategy_res = client.get("/api/v2/signal-strategies")

    assert signal_res.status_code == 200
    assert signal_res.json()["data"]["signals"][0]["action"] == "ENTER_LONG"
    assert channel_res.status_code == 200
    assert channel_res.json()["data"]["channels"][0]["name"] == "内部Bot-A"
    assert "example.test" in channel_res.json()["data"]["channels"][0]["masked_webhook_url"]
    assert strategy_res.status_code == 200
    assert strategy_res.json()["data"]["strategies"][0]["signal_enabled"] is True


def test_signal_center_api_approves_cancels_retries_and_tests_channel(monkeypatch):
    calls = []

    class FakeService:
        async def approve_signal(self, signal_id, channel_ids):
            calls.append(("approve", signal_id, channel_ids))
            return {"id": signal_id, "status": "sent", "deliveries": [{"status": "sent"}]}

        def cancel_signal(self, signal_id):
            calls.append(("cancel", signal_id))
            return {"id": signal_id, "status": "canceled"}

        async def retry_signal(self, signal_id):
            calls.append(("retry", signal_id))
            return {"id": signal_id, "status": "sent"}

        async def test_channel(
            self,
            channel_id,
            send=False,
            action="ENTER_LONG",
            instrument="DOGE-USDT-SWAP",
            investment_type="margin",
            amount=0.1,
        ):
            calls.append(("test", channel_id, send, action, instrument, investment_type, amount))
            return {"channel_id": channel_id, "dry_run": not send}

        def update_channel(self, channel_id, payload):
            calls.append(("update_channel", channel_id, payload))
            return {"id": channel_id, "allowed_strategy_ids": payload["allowed_strategy_ids"]}

        def delete_channel(self, channel_id):
            calls.append(("delete_channel", channel_id))
            return {"deleted": True, "channel_id": channel_id, "canceled_deliveries": 0}

        def set_strategy_signal_enabled(self, strategy_id, enabled):
            calls.append(("set_strategy", strategy_id, enabled))
            return {"strategy_id": strategy_id, "signal_enabled": enabled}

        def update_strategy_signal_settings(
            self,
            strategy_id,
            enabled=None,
            manual_approval_required=None,
        ):
            calls.append(("update_strategy_settings", strategy_id, enabled, manual_approval_required))
            return {
                "strategy_id": strategy_id,
                "signal_enabled": bool(enabled),
                "manual_approval_required": bool(manual_approval_required),
            }

    monkeypatch.setattr(signals, "signal_center_service", FakeService())
    client = build_client()

    approve = client.post("/api/v2/signals/11/approve", json={"channel_ids": [2, 3]})
    cancel = client.post("/api/v2/signals/11/cancel")
    retry = client.post("/api/v2/signals/11/retry")
    test = client.post(
        "/api/v2/signal-channels/2/test",
        json={
            "send": True,
            "action": "ENTER_LONG",
            "instrument": "DOGE-USDT-SWAP",
            "investment_type": "margin",
            "amount": 0.1,
        },
    )
    set_strategy = client.patch("/api/v2/signal-strategies/7", json={"enabled": True})
    set_manual_approval = client.put(
        "/api/v2/signal-strategies/7",
        json={"manual_approval_required": True},
    )
    update_channel = client.put("/api/v2/signal-channels/2", json={"allowed_strategy_ids": [7]})
    delete_channel = client.delete("/api/v2/signal-channels/2")

    assert approve.status_code == 200
    assert approve.json()["data"]["status"] == "sent"
    assert cancel.status_code == 200
    assert retry.status_code == 200
    assert test.status_code == 200
    assert set_strategy.status_code == 200
    assert set_strategy.json()["data"]["strategy"]["signal_enabled"] is True
    assert set_manual_approval.status_code == 200
    assert set_manual_approval.json()["data"]["strategy"]["manual_approval_required"] is True
    assert update_channel.status_code == 200
    assert update_channel.json()["data"]["channel"]["allowed_strategy_ids"] == [7]
    assert delete_channel.status_code == 200
    assert delete_channel.json()["data"]["deleted"] is True
    assert calls == [
        ("approve", 11, [2, 3]),
        ("cancel", 11),
        ("retry", 11),
        ("test", 2, True, "ENTER_LONG", "DOGE-USDT-SWAP", "margin", 0.1),
        ("update_strategy_settings", 7, True, None),
        ("update_strategy_settings", 7, None, True),
        ("update_channel", 2, {"allowed_strategy_ids": [7]}),
        ("delete_channel", 2),
    ]
