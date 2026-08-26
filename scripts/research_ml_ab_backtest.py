#!/usr/bin/env python3
"""A/B backtest: baseline handwritten momentum score vs walk-forward LightGBM score.

Same framework, same params as production 446 seed; the only variable is the
cross-sectional ranking source. Windows: main + split_a + split_b.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (
    str(PROJECT_ROOT / "backend"),
    str(PROJECT_ROOT / "strategies"),
    "/tmp/ml_research",
):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.services.backtrader_engine import backtrader_engine  # noqa: E402
from cross_sectional_momentum_vol_target import (  # noqa: E402
    CrossSectionalMomentumVolTargetStrategy,
)
from xs_momentum_ml_score import XSMomentumMLScoreStrategy  # noqa: E402

TOP39 = [
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
    "warmup_bars": 740,
    "leverage": 5,
    "max_leverage": 5,
    "symbols": TOP39,
    "rebalance_bars": 24,
    "min_symbol_turnover_usdt": 50000.0,
    "liquidity_window_bars": 24,
    "min_cross_section_symbols": 10,
    "mom_fast_window_bars": 168,
    "mom_slow_window_bars": 720,
    "mom_fast_weight": 0.5,
    "vol_window_bars": 480,
    "trend_ema_window": 200,
    "adx_window": 14,
    "entry_min_adx": 15.0,
    "rank_pct_long": 0.25,
    "rank_pct_short": 0.25,
    "exit_rank_long": 0.5,
    "exit_rank_short": 0.5,
    "max_long_positions": 3,
    "max_short_positions": 3,
    "max_total_positions": 6,
    "target_portfolio_vol": 0.30,
    "max_position_equity_pct": 0.35,
    "max_gross_leverage": 1.5,
    "min_notional_usdt": 20.0,
    "atr_window": 14,
    "atr_stop_mult": 2.5,
    "hard_stop_loss_pct": 0.12,
    "hard_take_profit_pct": 0.45,
    "break_even_at_r": 1.0,
    "break_even_buffer_bps": 10,
    "profit_trailing_start_r": 1.5,
    "trail_atr_mult": 3.0,
    "peak_pullback_pct": 0.45,
    "max_holding_bars": 240,
    "daily_pause_drawdown_pct": 0.04,
    "loss_cooldown_count": 3,
    "loss_cooldown_hours": 12,
    "include_funding_costs": True,
}

WINDOWS = {
    "main": ("2025-07-01", "2026-08-22"),
    "split_a": ("2025-07-01", "2026-01-31"),
    "split_b": ("2026-02-01", "2026-08-22"),
}


def run_one(label, strategy_class, start, end, config):
    t0 = time.time()
    report = backtrader_engine.run_strategy(
        strategy_class=strategy_class,
        exchange="okx",
        symbol=TOP39[0],
        symbols=TOP39,
        timeframe="1h",
        start_date=start,
        end_date=end,
        initial_capital=100.0,
        commission=0.0005,
        slippage=0.0005,
        strategy_config=dict(config),
    )
    summary = {
        "label": label,
        "window": f"{start}~{end}",
        "total_return_pct": getattr(report, "total_return_pct", None),
        "annual_return_pct": getattr(report, "annual_return_pct", None),
        "max_drawdown_pct": getattr(report, "max_drawdown_pct", None),
        "profit_factor": getattr(report, "profit_factor", None),
        "win_rate_pct": getattr(report, "win_rate_pct", None),
        "total_trades": getattr(report, "total_trades", None),
        "sharpe": getattr(report, "sharpe_ratio", None),
        "calmar": getattr(report, "calmar_ratio", None),
        "total_fees": getattr(report, "total_fees", None),
        "funding_fee": getattr(report, "funding_fee", None),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    return summary


if __name__ == "__main__":
    ml_config = {**BASE_CONFIG, "ml_scores_path": "/tmp/ml_research/oos_scores.parquet"}
    jobs = []
    for wname, (start, end) in WINDOWS.items():
        jobs.append((f"baseline_{wname}", CrossSectionalMomentumVolTargetStrategy, start, end, BASE_CONFIG))
        jobs.append((f"ml_{wname}", XSMomentumMLScoreStrategy, start, end, ml_config))

    results = []
    for label, cls, start, end, cfg in jobs:
        print(f"[RUN] {label}: {start}~{end}", flush=True)
        try:
            s = run_one(label, cls, start, end, cfg)
            results.append(s)
            print(f"[DONE] {label}: ret={s['total_return_pct']:.2f}% mdd={s['max_drawdown_pct']:.2f}% "
                  f"pf={s['profit_factor']} wr={s['win_rate_pct']} trades={s['total_trades']} "
                  f"sharpe={s['sharpe']}", flush=True)
        except Exception as exc:
            print(f"[FAIL] {label}: {exc!r}", flush=True)
            results.append({"label": label, "error": repr(exc)})
    Path("/tmp/ml_research/ab_summary.json").write_text(json.dumps(results, indent=2, default=str))
    print(json.dumps(results, indent=2, default=str))
