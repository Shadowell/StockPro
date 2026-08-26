from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.strategy_exit_protection import audit_strategy_exit_protection  # noqa: E402


def test_lab_vwap_strategy_has_mandatory_stop_loss_and_take_profit() -> None:
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(
        item
        for item in entries
        if (item.get("config") or {}).get("strategy_key") == "contract_vwap_volume_profile_lab_4h_100u"
    )

    audit = audit_strategy_exit_protection(entry["config"])

    assert audit.passed is True
    assert audit.has_stop_loss is True
    assert audit.has_take_profit is True
    assert "stop_buffer_atr" in audit.stop_loss_fields
    assert "risk_reward_ratio" in audit.take_profit_fields


def test_exit_protection_audit_rejects_missing_stop_loss() -> None:
    audit = audit_strategy_exit_protection(
        {
            "market_type": "swap",
            "take_profit_bps": 100,
            "max_holding_bars": 20,
        }
    )

    assert audit.passed is False
    assert audit.has_stop_loss is False
    assert audit.has_take_profit is True


def test_exit_protection_audit_rejects_missing_take_profit() -> None:
    audit = audit_strategy_exit_protection(
        {
            "market_type": "swap",
            "stop_loss_bps": 50,
            "max_holding_bars": 20,
        }
    )

    assert audit.passed is False
    assert audit.has_stop_loss is True
    assert audit.has_take_profit is False
