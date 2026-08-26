from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_websocket_manager_uses_structured_subscription_keys_for_swap_symbols():
    source = (ROOT / "frontend/src/services/websocketManager.ts").read_text()

    assert "JSON.stringify([channel, exchange, symbol || '', timeframe || ''])" in source
    assert "JSON.parse(key) as [string, string, string, string]" in source
    assert "rest.indexOf(':')" not in source


def test_websocket_endpoint_forwards_timeframe_to_backend_subscriptions():
    source = (ROOT / "backend/app/api/v2/endpoints/websocket.py").read_text()

    assert 'timeframe = message.get("timeframe")' in source
    assert "connection_manager.subscribe(websocket, channel, exchange, symbol, timeframe)" in source
    assert 'message.get("timeframe")' in source[source.index("connection_manager.unsubscribe("):]
