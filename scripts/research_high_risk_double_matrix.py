"""High-risk two-week-double exploration: three candidate structures on real OKX k-lines.

Candidates:
- chaser      : MomentumChaserPyramidStrategy (4H momentum-leader chase + pyramiding, 10x)
- squeeze     : SqueezeBreakoutStrategy (sid295 logic) on top-volatility pool, 8x
- xs_aggr     : CrossSectionalMomentumVolTargetStrategy with aggressive params, 10x

Windows: last ~120 days and last ~60 days (recent regime matters most for a
two-week horizon). Costs: taker 5bps + slippage 5bps + real funding.
"""
from __future__ import annotations

import json
import math
import sys
import time
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
from momentum_chaser_pyramid import MomentumChaserPyramidStrategy  # noqa: E402
from squeeze_breakout_hvol import SqueezeBreakoutHVOLStrategy  # noqa: E402

TOP39 = [
    "ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT",
    "XAU/USDT:USDT", "DOGE/USDT:USDT", "HYPE/USDT:USDT", "TRUMP/USDT:USDT",
    "PEPE/USDT:USDT", "BICO/USDT:USDT", "KAITO/USDT:USDT", "WLD/USDT:USDT",
    "ADA/USDT:USDT", "SHIB/USDT:USDT", "BNB/USDT:USDT", "SUI/USDT:USDT",
    "LINK/USDT:USDT", "UNI/USDT:USDT", "ONDO/USDT:USDT", "AAVE/USDT:USDT",
    "BCH/USDT:USDT", "BOME/USDT:USDT", "FIL/USDT:USDT", "AVAX/USDT:USDT",
    "NEAR/USDT:USDT", "GPS/USDT:USDT", "LTC/USDT:USDT", "PENGU/USDT:USDT",
    "XLM/USDT:USDT", "ORDI/USDT:USDT", "PEOPLE/USDT:USDT", "CRV/USDT:USDT",
    "ETC/USDT:USDT", "TRX/USDT:USDT", "JTO/USDT:USDT",
    "OP/USDT:USDT", "ARB/USDT:USDT", "ETHFI/USDT:USDT", "ICP/USDT:USDT",
]

CHASER_CONFIG = {
    "strategy_key": "contract_momentum_chaser_pyramid",
    "class_name": "MomentumChaserPyramidStrategy",
    "market_type": "swap",
    "exchange": "okx",
    "timeframe": "4h",
    "is_paper_trading": True,
    "initial_capital": 100.0,
    "loop_interval_sec": 60,
    "symbols": TOP39,
    "scan_interval_bars": 1,
    "ret_fast_window_bars": 6,
    "ret_slow_window_bars": 18,
    "rank_pct": 0.2,
    "breakout_lookback_bars": 12,
    "trend_ema_window": 55,
    "atr_window": 14,
    "min_ret_fast_abs": 0.05,
    "max_positions": 3,
    "leverage": 10,
    "target_notional_pct": 0.35,
    "max_gross_leverage": 3.0,
    "min_notional_usdt": 20.0,
    "max_position_equity_pct": 0.8,
    "pyramid_adds_max": 2,
    "add_trigger_r": 1.0,
    "add_size_mult": 1.0,
    "stop_atr_mult": 1.5,
    "hard_stop_loss_pct": 0.25,
    "hard_take_profit_pct": 0.60,
    "trail_start_r": 2.0,
    "trail_atr_mult": 3.0,
    "lock_pullback_pct": 0.45,
    "max_holding_bars": 48,
    "daily_pause_drawdown_pct": 0.08,
    "loss_cooldown_count": 3,
    "loss_cooldown_hours": 24,
    "include_funding_costs": True,
}

XS_AGGR_CONFIG = {
    "strategy_key": "contract_xs_momentum_vol_target",
    "class_name": "CrossSectionalMomentumVolTargetStrategy",
    "market_type": "swap",
    "exchange": "okx",
    "timeframe": "1h",
    "is_paper_trading": True,
    "initial_capital": 100.0,
    "include_funding_costs": True,
    "min_cross_section_symbols": 10,
}

XS_AGGR_OVERRIDES = {
    "leverage": 10,
    "max_leverage": 10,
    "mom_fast_window_bars": 96,
    "mom_slow_window_bars": 360,
    "mom_fast_weight": 0.5,
    "vol_window_bars": 240,
    "rebalance_bars": 24,
    "rank_pct_long": 0.10,
    "rank_pct_short": 0.10,
    "max_long_positions": 2,
    "max_short_positions": 2,
    "max_total_positions": 4,
    "target_portfolio_vol": 1.00,
    "max_position_equity_pct": 0.80,
    "max_gross_leverage": 3.0,
    "atr_stop_mult": 3.0,
    "peak_pullback_pct": 0.45,
    "trail_atr_mult": 3.0,
    "max_holding_bars": 240,
}

SQUEEZE_CONFIG = {
    "strategy_key": "contract_squeeze_breakout_hvol",
    "class_name": "SqueezeBreakoutHVOLStrategy",
    "market_type": "swap",
    "exchange": "okx",
    "timeframe": "4h",
    "is_paper_trading": True,
    "initial_capital": 100.0,
    "loop_interval_sec": 60,
    "bb_period": 20,
    "squeeze_lookback": 42,
    "squeeze_pct": 0.35,
    "breakout_period": 12,
    "volume_period": 15,
    "volume_mult": 1.25,
    "atr_period": 14,
    "stop_atr": 2.0,
    "trail_atr": 3.5,
    "max_holding_bars": 42,
    "cooldown_bars": 3,
    "risk_pct": 0.03,
    "leverage": 8,
    "allow_short": True,
    "include_funding_costs": True,
}


def pick_top_vol_pool(n=20):
    from app.services.kline_file_store import KlineFileStore

    store = KlineFileStore()
    rows = []
    for s in TOP39:
        try:
            recs = store.read_klines("okx", s, "1d")
            if not recs or len(recs) < 60:
                continue
            closes = [float(r["close"]) for r in recs[-90:]]
            rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            ann = math.sqrt(var) * math.sqrt(365)
            rows.append((s, ann))
        except Exception:
            continue
    rows.sort(key=lambda x: -x[1])
    pool = [s for s, _ in rows[:n]]
    print("[POOL] top-vol:", pool, flush=True)
    return pool


def run_one(label, strategy_class, symbols, timeframe, start, end, config):
    t0 = time.time()
    report = backtrader_engine.run_strategy(
        strategy_class=strategy_class,
        exchange="okx",
        symbol=symbols[0],
        symbols=symbols,
        timeframe=timeframe,
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
        "status": getattr(report, "status", None),
        "final_capital": getattr(report, "final_capital", None),
        "total_return_pct": getattr(report, "total_return_pct", None),
        "annual_return_pct": getattr(report, "annual_return_pct", None),
        "max_drawdown_pct": getattr(report, "max_drawdown_pct", None),
        "win_rate_pct": getattr(report, "win_rate_pct", None),
        "profit_factor": getattr(report, "profit_factor", None),
        "total_trades": getattr(report, "total_trades", None),
        "avg_holding_bars": getattr(report, "avg_holding_bars", None),
        "total_fees": getattr(report, "total_fees", None),
        "funding_fee": getattr(report, "funding_fee", None),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    trades = getattr(report, "trades", None) or []
    best = sorted(trades, key=lambda t: float(t.get("pnl_net", t.get("pnl", 0)) or 0), reverse=True)[:3]
    summary["top_trades_pnl"] = [round(float(t.get("pnl_net", t.get("pnl", 0)) or 0), 2) for t in best]
    return summary


WINDOWS = {
    "w120": ("2026-04-25", "2026-08-22"),
    "w60": ("2026-06-23", "2026-08-22"),
}

JOBS = []
XS_FULL = {**XS_AGGR_CONFIG, **XS_AGGR_OVERRIDES, "symbols": TOP39}
for wname, (start, end) in WINDOWS.items():
    JOBS.append((f"chaser_{wname}", MomentumChaserPyramidStrategy, TOP39, "4h", start, end, CHASER_CONFIG))
    JOBS.append((f"xs_aggr_{wname}", CrossSectionalMomentumVolTargetStrategy, TOP39, "1h", start, end, XS_FULL))
    JOBS.append((f"squeeze_{wname}", SqueezeBreakoutHVOLStrategy, None, "4h", start, end, SQUEEZE_CONFIG))

if __name__ == "__main__":
    results = []
    vol_pool = pick_top_vol_pool()
    for label, cls, syms, tf, start, end, cfg in JOBS:
        if syms is None:
            syms = vol_pool
            cfg = {**cfg, "symbols": vol_pool}
        print(f"[RUN] {label}: {start}~{end} n_symbols={len(syms)}", flush=True)
        try:
            s = run_one(label, cls, syms, tf, start, end, cfg)
            results.append(s)
            print(f"[DONE] {label}: ret={s['total_return_pct']:.2f}% mdd={s['max_drawdown_pct']:.2f}% "
                  f"pf={s['profit_factor']} wr={s['win_rate_pct']} trades={s['total_trades']} "
                  f"top={s['top_trades_pnl']}", flush=True)
        except Exception as exc:
            print(f"[FAIL] {label}: {exc!r}", flush=True)
            results.append({"label": label, "error": repr(exc)})
    Path("/tmp/hrisk_summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
