"""Dynamic paper-strategy templates must stay loadable by BitPro's DB-script sandbox."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.agent.code_sandbox import (
    validate_base_strategy_contract,
    validate_strategy_runtime_smoke,
)


ROOT = Path(__file__).resolve().parents[1]


def _template(name: str) -> str:
    return (ROOT / "data" / "strategy_templates" / name).read_text(encoding="utf-8")


def _assert_dynamic_swap_template(name: str, symbols: list[str], timeframe: str) -> None:
    code = _template(name)
    validate_base_strategy_contract(code)
    asyncio.run(
        validate_strategy_runtime_smoke(
            code,
            symbols=symbols,
            market_type="swap",
            timeframe=timeframe,
        )
    )


def test_main_account_template_passes_contract_and_runtime_smoke() -> None:
    _assert_dynamic_swap_template(
        "main-account-donchian-1d.py",
        ["BTC/USDT:USDT", "ETH/USDT:USDT"],
        "1d",
    )


def test_challenge_account_template_passes_contract_and_runtime_smoke() -> None:
    _assert_dynamic_swap_template(
        "challenge-account-vwap-4h.py",
        ["LAB/USDT:USDT", "LIT/USDT:USDT", "TRIA/USDT:USDT"],
        "4h",
    )


def test_vwap_retest_candidate_template_passes_contract_and_runtime_smoke() -> None:
    _assert_dynamic_swap_template(
        "vwap-retest-confirmation-1h.py",
        ["ETH/USDT:USDT"],
        "1h",
    )
