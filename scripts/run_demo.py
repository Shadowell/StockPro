#!/usr/bin/env python3
"""A-share paper demo — not crypto.

Runs a sealed-snapshot-style paper round through AShareSpotBroker:
buy 600000.SH on T, sell on T+1, print the CNY cash ledger.

Optional: list isolation-DB paper instances when DATABASE_URL points at
stockpro_bitpro_rebase_dev.

Usage:
    PYTHONPATH=backend python3 scripts/run_demo.py
    PYTHONPATH=backend python3 scripts/run_demo.py --list-instances
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_demo")

ISOLATION_DB = "stockpro_bitpro_rebase_dev"
DEMO_SYMBOL = "600000.SH"
DEMO_STORAGE_SYMBOL = "SH_600000"
INITIAL_CASH = 1_000_000.0
CURRENCY = "CNY"
COST = {
    "commission_rate": 0.0003,
    "minimum_commission": 5.0,
    "stamp_duty_rate": 0.0005,
    "transfer_fee_rate": 0.00001,
}

def _require_ashare_symbol(symbol: str) -> str:
    from app.services.ashare_execution import instrument_key

    key = instrument_key(symbol)
    if not key or "." not in key:
        raise SystemExit(f"A-share demo requires code.market, got {symbol!r}")
    lowered = symbol.lower()
    if "/" in symbol or any(token in lowered for token in ("btc", "eth", "usdt")):
        raise SystemExit("A-share demo refuses crypto symbols")
    return key


def run_paper_broker_demo(symbol: str = DEMO_SYMBOL) -> dict[str, Any]:
    from app.services.ashare_backtest_engine import AShareBacktestEngine
    from app.services.ashare_execution import AShareSpotBroker, compute_fees

    key = _require_ashare_symbol(symbol)
    storage = "SH_" + key.split(".", 1)[0] if key.endswith(".SH") else DEMO_STORAGE_SYMBOL
    bars = [
        {"trade_date": "2026-08-20", "symbol": storage, "open": 10, "close": 10.2, "turnover": 5_000_000, "volume": 1_000_000},
        {"trade_date": "2026-08-21", "symbol": storage, "open": 10.2, "close": 10.1, "turnover": 5_000_000, "volume": 1_000_000},
    ]
    intents = [
        {
            "symbol": storage,
            "intent_type": "order_target_percent",
            "payload": {"value": 0.1},
            "simulated_at": "2026-08-20T15:00:00+08:00",
            "available_at": "2026-08-20T15:00:00+08:00",
        },
        {
            "symbol": storage,
            "intent_type": "order_target_percent",
            "payload": {"value": 0},
            "simulated_at": "2026-08-21T15:00:00+08:00",
            "available_at": "2026-08-21T15:00:00+08:00",
        },
    ]
    engine = AShareBacktestEngine(bars=bars, intents=intents, initial_cash=INITIAL_CASH, cost_model=COST)
    backtest = engine.run()
    buy_trade = next(item for item in backtest["trades"] if item["side"] == "buy")
    sell_price = 10.2

    broker = AShareSpotBroker(COST)
    cash = INITIAL_CASH
    ledger: list[dict[str, Any]] = []

    buy = broker.evaluate(
        side="buy",
        symbol=key,
        quantity=int(buy_trade["quantity"]),
        price=float(buy_trade["price"]),
        trade_date="2026-08-21",
        cash=cash,
        available_quantity=0,
        bar=bars[1],
    )
    if not buy.get("accepted"):
        raise SystemExit(f"Paper buy rejected: {buy.get('rejection_code')}")
    cash += float(buy["cash_delta"])
    ledger.append({"trade_date": "2026-08-21", "side": "buy", "cash": cash, **buy})

    sell = broker.evaluate(
        side="sell",
        symbol=key,
        quantity=int(buy_trade["quantity"]),
        price=sell_price,
        trade_date="2026-08-22",
        cash=cash,
        available_quantity=int(buy_trade["quantity"]),
        bar={"open": sell_price, "close": 10.1, "volume": 1000},
    )
    if not sell.get("accepted"):
        raise SystemExit(f"Paper T+1 sell rejected: {sell.get('rejection_code')}")
    cash += float(sell["cash_delta"])
    ledger.append({"trade_date": "2026-08-22", "side": "sell", "cash": cash, **sell})

    return {
        "runtime_mode": "ashare_paper",
        "currency": CURRENCY,
        "symbol": key,
        "initial_cash": INITIAL_CASH,
        "final_cash": cash,
        "pnl": cash - INITIAL_CASH,
        "trades": ledger,
        "backtest_trade_count": len(backtest["trades"]),
        "fees_aligned": compute_fees("sell", float(sell["amount"]), COST) == sell["fees"],
    }


def isolation_database_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
        raise SystemExit("DATABASE_URL must be PostgreSQL")
    name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if name != ISOLATION_DB:
        raise SystemExit(
            f"refusing non-isolated DATABASE_URL; run ./scripts/setup_isolation_db.sh "
            f"(expected /{ISOLATION_DB})"
        )
    return raw


def list_paper_instances(database_url: str) -> list[dict[str, Any]]:
    isolation_database_url(database_url)
    from app.db.postgres_db import PostgresDatabase
    from app.services.paper_runtime_service import PaperRuntimeService

    database = PostgresDatabase(database_url)
    try:
        return PaperRuntimeService(database).list_instances_light()
    finally:
        database.close_pool()


def _print_broker_demo(result: dict[str, Any]) -> None:
    logger.info("=" * 56)
    logger.info("A-share paper demo (CNY cash ledger, T+1, 100-share lots)")
    logger.info("runtime_mode=%s currency=%s symbol=%s", result["runtime_mode"], result["currency"], result["symbol"])
    logger.info("initial_cash=%.2f %s", result["initial_cash"], CURRENCY)
    for trade in result["trades"]:
        fees = trade.get("fees") or {}
        logger.info(
            "%s %s %s qty=%s px=%.2f cash_delta=%+.2f cash=%.2f commission=%.2f tax=%.2f transfer=%.2f",
            trade["trade_date"],
            trade["side"].upper(),
            trade["symbol"],
            trade["quantity"],
            float(trade["price"]),
            float(trade["cash_delta"]),
            float(trade["cash"]),
            float(fees.get("commission") or 0),
            float(fees.get("tax") or 0),
            float(fees.get("transfer_fee") or 0),
        )
    logger.info("final_cash=%.2f %s pnl=%+.2f %s", result["final_cash"], CURRENCY, result["pnl"], CURRENCY)
    logger.info("=" * 56)


def main() -> int:
    parser = argparse.ArgumentParser(description="A-share paper demo (not crypto)")
    parser.add_argument("--symbol", default=DEMO_SYMBOL, help="A-share code.market, default 600000.SH")
    parser.add_argument(
        "--list-instances",
        action="store_true",
        help="Also list paper instances from the isolation PostgreSQL.",
    )
    args = parser.parse_args()

    result = run_paper_broker_demo(args.symbol)
    _print_broker_demo(result)

    if args.list_instances:
        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url:
            logger.error("DATABASE_URL is unset. Run ./scripts/setup_isolation_db.sh")
            return 1
        instances = list_paper_instances(database_url)
        logger.info("isolation paper instances: %d", len(instances))
        for item in instances[:20]:
            logger.info(
                "  %s  %s  cash=%.2f %s  status=%s",
                item.get("id"),
                item.get("name"),
                float(item.get("cash_balance") or item.get("initial_cash") or 0),
                CURRENCY,
                item.get("status"),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
