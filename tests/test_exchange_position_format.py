import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.exchange.base import BaseExchange  # noqa: E402


class DummyExchange(BaseExchange):
    @property
    def name(self) -> str:
        return "dummy"

    def _create_exchange(self):
        return None


def test_format_position_preserves_okx_contract_display_fields():
    exchange = DummyExchange()

    formatted = exchange._format_position(
        {
            "symbol": "DOGE/USDT:USDT",
            "side": "short",
            "contracts": 0.1,
            "contractSize": 1000,
            "entryPrice": 0.10862,
            "markPrice": 0.10853,
            "liquidationPrice": 1.26664,
            "unrealizedPnl": 0.01,
            "percentage": 0.08,
            "leverage": 1,
            "marginMode": "cross",
            "initialMargin": 10.85,
            "maintenanceMargin": 0.007,
            "marginRatio": 1536.092,
        }
    )

    assert formatted["symbol"] == "DOGE/USDT:USDT"
    assert formatted["side"] == "short"
    assert formatted["amount"] == 0.1
    assert formatted["contracts"] == 0.1
    assert formatted["contract_size"] == 1000
    assert formatted["base_amount"] == 100
    assert formatted["entry_price"] == 0.10862
    assert formatted["mark_price"] == 0.10853
    assert formatted["liquidation_price"] == 1.26664
    assert formatted["unrealized_pnl"] == 0.01
    assert formatted["unrealized_pnl_pct"] == 0.08
    assert formatted["leverage"] == 1
    assert formatted["margin_mode"] == "cross"
    assert formatted["margin"] == 10.85
    assert formatted["initial_margin"] == 10.85
    assert formatted["maintenance_margin"] == 0.007
    assert formatted["margin_ratio"] == 1536.092
