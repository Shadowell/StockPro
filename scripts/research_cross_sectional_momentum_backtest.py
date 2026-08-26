#!/usr/bin/env python3
"""Cross-sectional momentum + vol-target strategy: official Backtrader backtest.

Runs on the production host against the real OKX file k-line store:

    /opt/bitpro/backend/venv/bin/python scripts/research_cross_sectional_momentum_backtest.py \
        --quick   # single main window only

Windows (contract acceptance):
- main      : 2025-07-01 ~ 2026-08-22 (full-pool warmup complete)
- split_a   : 2025-07-01 ~ 2026-01-31 (out-of-sample front half)
- split_b   : 2026-02-01 ~ 2026-08-22 (out-of-sample back half)
- heavy_cost: main window with taker 8bps + slippage 4bps (cost stress)

Costs include real OKX funding cashflows via include_funding_costs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (
    str(PROJECT_ROOT / "backend"),
    str(PROJECT_ROOT / "strategies"),
):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.services.backtrader_engine import backtrader_engine  # noqa: E402
from cross_sectional_momentum_vol_target import (  # noqa: E402
    CrossSectionalMomentumVolTargetStrategy,
)

TOP40 = [
    "ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT",
    "XAU/USDT:USDT", "DOGE/USDT:USDT", "HYPE/USDT:USDT", "TRUMP/USDT:USDT",
    "PEPE/USDT:USDT", "BICO/USDT:USDT", "KAITO/USDT:USDT", "WLD/USDT:USDT",
    "ADA/USDT:USDT", "SHIB/USDT:USDT", "BNB/USDT:USDT", "SUI/USDT:USDT",
    "LINK/USDT:USDT", "UNI/USDT:USDT", "ONDO/USDT:USDT", "AAVE/USDT:USDT",
    "BCH/USDT:USDT", "BOME/USDT:USDT", "FIL/USDT:USDT", "AVAX/USDT:USDT",
    "NEAR/USDT:USDT", "GPS/USDT:USDT", "LTC/USDT:USDT", "PENGU/USDT:USDT",
    "XLM/USDT:USDT", "ORDI/USDT:USDT", "PEOPLE/USDT:USDT", "CRV/USDT:USDT",
    "DOT/USDT:USDT", "ETC/USDT:USDT", "TRX/USDT:USDT", "JTO/USDT:USDT",
    "OP/USDT:USDT", "ARB/USDT:USDT", "ETHFI/USDT:USDT", "ICP/USDT:USDT",
]

BASE_CONFIG = {
    "strategy_key": "contract_xs_momentum_vol_target",
    "class_name": "CrossSectionalMomentumVolTargetStrategy",
    "market_type": "swap",
    "exchange": "okx",
    "timeframe": "1h",
    "is_paper_trading": True,
    "initial_capital": 100.0,
    "loop_interval_sec": 60,
    "warmup_bars": 500,
    "leverage": 5,
    "max_leverage": 5,
    "symbols": TOP40,
    # cadence
    "rebalance_bars": 4,
    "min_symbol_turnover_usdt": 50000.0,
    "liquidity_window_bars": 24,
    "min_cross_section_symbols": 10,
    # momentum
    "mom_fast_window_bars": 72,
    "mom_slow_window_bars": 168,
    "mom_fast_weight": 0.6,
    "vol_window_bars": 480,
    # trend filter
    "trend_ema_window": 200,
    "adx_window": 14,
    "entry_min_adx": 15.0,
    # ranking & caps
    "rank_pct_long": 0.25,
    "rank_pct_short": 0.25,
    "exit_rank_long": 0.5,
    "exit_rank_short": 0.5,
    "max_long_positions": 3,
    "max_short_positions": 3,
    "max_total_positions": 6,
    # vol targeting
    "target_portfolio_vol": 0.30,
    "max_position_equity_pct": 0.35,
    "max_gross_leverage": 1.5,
    "min_notional_usdt": 20.0,
    # exits (mandatory protection stack)
    "atr_window": 14,
    "atr_stop_mult": 2.0,
    "hard_stop_loss_pct": 0.12,
    "hard_take_profit_pct": 0.45,
    "break_even_at_r": 1.0,
    "break_even_buffer_bps": 10,
    "profit_trailing_start_r": 1.5,
    "trail_atr_mult": 2.5,
    "peak_pullback_pct": 0.35,
    "max_holding_bars": 96,
    # portfolio risk
    "daily_pause_drawdown_pct": 0.04,
    "loss_cooldown_count": 3,
    "loss_cooldown_hours": 12,
    # funding realism for contract backtests
    "include_funding_costs": True,
}

WINDOWS = {
    "main": ("2025-07-01", "2026-08-22"),
    "split_a": ("2025-07-01", "2026-01-31"),
    "split_b": ("2026-02-01", "2026-08-22"),
}


def run_one(label, start, end, commission, slippage):
    t0 = time.time()
    report = backtrader_engine.run_strategy(
        strategy_class=CrossSectionalMomentumVolTargetStrategy,
        exchange="okx",
        symbol=TOP40[0],
        symbols=TOP40,
        timeframe="1h",
        start_date=start,
        end_date=end,
        initial_capital=100.0,
        commission=commission,
        slippage=slippage,
        strategy_config=dict(BASE_CONFIG),
    )
    data = report.to_dict() if hasattr(report, "to_dict") else vars(report)
    summary = {
        "label": label,
        "window": f"{start}~{end}",
        "status": getattr(report, "status", None),
        "initial_capital": getattr(report, "initial_capital", None),
        "final_capital": getattr(report, "final_capital", None),
        "total_return_pct": getattr(report, "total_return_pct", None),
        "annual_return_pct": getattr(report, "annual_return_pct", None),
        "max_drawdown_pct": getattr(report, "max_drawdown_pct", None),
        "sharpe": getattr(report, "sharpe_ratio", None),
        "sortino": getattr(report, "sortino_ratio", None),
        "calmar": getattr(report, "calmar_ratio", None),
        "win_rate_pct": getattr(report, "win_rate_pct", None),
        "profit_factor": getattr(report, "profit_factor", None),
        "total_trades": getattr(report, "total_trades", None),
        "winning_trades": getattr(report, "winning_trades", None),
        "losing_trades": getattr(report, "losing_trades", None),
        "avg_holding_bars": getattr(report, "avg_holding_bars", None),
        "total_fees": getattr(report, "total_fees", None),
        "funding_fee": getattr(report, "funding_fee", None),
        "funding_events": getattr(report, "funding_events", None),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    return summary, data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--output", default="/tmp/xs_momentum_backtest.json")
    args = parser.parse_args()

    jobs = [("main", *WINDOWS["main"], 0.0005, 0.0005)]
    if not args.quick:
        jobs.append(("split_a", *WINDOWS["split_a"], 0.0005, 0.0005))
        jobs.append(("split_b", *WINDOWS["split_b"], 0.0005, 0.0005))
        jobs.append(("heavy_cost", *WINDOWS["main"], 0.0008, 0.0004))

    results = []
    full = {}
    for job in jobs:
        label, start, end, comm, slip = job
        print(f"[RUN] {label}: {start}~{end} comm={comm} slip={slip}", flush=True)
        try:
            summary, data = run_one(label, start, end, comm, slip)
            results.append(summary)
            full[label] = data
            print(f"[DONE] {label}: ret={summary['total_return_pct']}% "
                  f"mdd={summary['max_drawdown_pct']}% pf={summary['profit_factor']} "
                  f"trades={summary['total_trades']} elapsed={summary['elapsed_sec']}s",
                  flush=True)
        except Exception as exc:  # keep running the matrix
            print(f"[FAIL] {label}: {exc!r}", flush=True)
            results.append({"label": label, "error": repr(exc)})

    Path(args.output).write_text(json.dumps(full, ensure_ascii=False, default=str))
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
