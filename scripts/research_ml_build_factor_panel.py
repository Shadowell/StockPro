#!/usr/bin/env python3
"""Build the cross-sectional factor panel from the real OKX file k-line store.

Output: parquet with per-(symbol, hourly-bar) rows:
    features (no look-ahead, all computed from data up to t) + label
    label = cross-sectional z-score of forward 24h return at each timestamp.

Run on the production host with the project venv.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

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

LABEL_HORIZON = 24


def _ann_vol(close: pd.Series, window: int) -> pd.Series:
    ret = np.log(close).diff()
    return ret.rolling(window, min_periods=window // 2).std() * np.sqrt(24 * 365)


def build_symbol_frame(store, symbol: str) -> pd.DataFrame | None:
    recs = store.read_klines("okx", symbol, "1h")
    if not recs or len(recs) < 1500:
        print(f"skip {symbol}: {len(recs) if recs else 0} bars")
        return None
    df = pd.DataFrame(recs)[["timestamp", "open", "high", "low", "close", "volume"]]
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["timestamp"] = df["timestamp"].astype("int64")
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)

    c, h, l, o, v = df["close"], df["high"], df["low"], df["open"], df["volume"]
    f = pd.DataFrame({"symbol": symbol, "timestamp": df["timestamp"]})

    # --- returns ---
    for w in (6, 24, 72, 168, 360, 720):
        f[f"ret_{w}h"] = c.pct_change(w)

    # --- volatility ---
    f["vol_240"] = _ann_vol(c, 240)
    f["vol_720"] = _ann_vol(c, 720)
    f["vol_ratio"] = f["vol_240"] / f["vol_720"]

    # --- risk-adjusted momentum ---
    ret1 = np.log(c).diff()
    for w in (72, 168, 720):
        std = ret1.rolling(w, min_periods=w // 2).std()
        base = c.shift(w)
        fwd_ret = c / base - 1.0
        f[f"sharpe_{w}"] = (fwd_ret / std.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    # --- trend structure ---
    ema = lambda s, w: s.ewm(span=w, adjust=False, min_periods=w).mean()
    f["ema_dist_55"] = c / ema(c, 55) - 1.0
    f["ema_dist_200"] = c / ema(c, 200) - 1.0
    f["ema_ratio_5_20"] = ema(c, 5) / ema(c, 20) - 1.0

    # --- ADX14 (vectorized Wilder) ---
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr
    dx = ((pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan) * 100).replace([np.inf, -np.inf], np.nan)
    f["adx_14"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    # --- range position & drawdown ---
    for w in (120, 480, 1440):
        lo = l.rolling(w, min_periods=w // 2).min()
        hi = h.rolling(w, min_periods=w // 2).max()
        f[f"pos_{w}"] = (c - lo) / (hi - lo).replace(0, np.nan)
    f["dd_high_480"] = c / h.rolling(480, min_periods=240).max() - 1.0

    # --- volume ---
    f["vol_ratio_6_72"] = v.rolling(6).mean() / v.rolling(72).mean().replace(0, np.nan)
    f["turnover_mean_24"] = (c * v).rolling(24).mean()

    # --- candle anatomy ---
    rng = (h - l).replace(0, np.nan)
    f["body_mean_12"] = ((c - o).abs() / rng).rolling(12).mean()
    f["upper_wick_mean_12"] = ((h - np.maximum(c, o)) / rng).rolling(12).mean()
    f["green_pct_12"] = (c > o).astype(float).rolling(12).mean()

    # --- squeeze: bb width percentile ---
    ma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std()
    bb_width = 2 * sd20 / ma20.replace(0, np.nan)
    f["bb_width_pctile_96"] = bb_width.rolling(96, min_periods=48).rank(pct=True)

    # --- listing age ---
    f["list_age_days"] = (df["timestamp"] - df["timestamp"].iloc[0]) / 86_400_000.0

    # --- label: forward 24h return ---
    f["fwd_ret_24"] = c.shift(-LABEL_HORIZON) / c - 1.0
    return f


def main():
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
    from app.services.kline_file_store import KlineFileStore

    store = KlineFileStore()
    frames = []
    for sym in TOP39:
        fr = build_symbol_frame(store, sym)
        if fr is not None:
            frames.append(fr)
            n = len(fr)
            t0 = pd.to_datetime(fr["timestamp"].iloc[0], unit="ms")
            print(f"{sym:<22} rows={n:>7} from={t0:%Y-%m-%d}", flush=True)

    panel = pd.concat(frames, ignore_index=True)

    # --- cross-sectional context features ---
    panel["xsec_rank_ret24"] = panel.groupby("timestamp")["ret_24h"].rank(pct=True)
    panel["xsec_rank_sharpe168"] = panel.groupby("timestamp")["sharpe_168"].rank(pct=True)

    # --- cross-sectional z-scored label ---
    grp = panel.groupby("timestamp")["fwd_ret_24"]
    mu, sd = grp.transform("mean"), grp.transform("std").replace(0, np.nan)
    panel["label"] = (panel["fwd_ret_24"] - mu) / sd

    feature_cols = [c for c in panel.columns if c not in
                    ("symbol", "timestamp", "fwd_ret_24", "label")]
    panel = panel.dropna(subset=["label"])
    out = Path("/tmp/ml_research")
    out.mkdir(exist_ok=True)
    panel.to_parquet(out / "factor_panel.parquet", index=False)
    meta = {
        "symbols": sorted(panel["symbol"].unique().tolist()),
        "rows": int(len(panel)),
        "feature_cols": feature_cols,
        "label_horizon_bars": LABEL_HORIZON,
        "t_min": str(pd.to_datetime(panel["timestamp"].min(), unit="ms")),
        "t_max": str(pd.to_datetime(panel["timestamp"].max(), unit="ms")),
    }
    (out / "panel_meta.json").write_text(__import__("json").dumps(meta, indent=2))
    print("PANEL rows:", len(panel), "| features:", len(feature_cols))
    print(meta["t_min"], "->", meta["t_max"])
    print("saved to", out / "factor_panel.parquet")


if __name__ == "__main__":
    main()
