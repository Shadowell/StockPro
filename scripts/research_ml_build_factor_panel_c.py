#!/usr/bin/env python3
"""Round C factor panel: round-B panel + OI dynamics from the backfilled series.

New OI features (hourly, from open_interest_history exchange='binanceusdm',
2022-01 ~ present, joined per base symbol):
- oi_change_24h / oi_change_72h : OI rate-of-change
- oi_percentile_30d             : OI level percentile over trailing 30d
- oi_mom_interaction            : oi_change_24h * ret_24h (leverage-driven move)
- price_oi_divergence           : ret_24h - oi_change_24h (spot-led vs OI-led)

Training objective returns to round-A z-score regression (LambdaRank was
falsified in round B). list_age_days stays removed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.kline_file_store import KlineFileStore  # noqa: E402
from app.db.local_db import db_instance as db  # noqa: E402

TOP39_BASES = [
    "ETH", "BTC", "SOL", "XRP", "XAU", "DOGE", "HYPE", "TRUMP",
    "PEPE", "BICO", "KAITO", "WLD", "ADA", "SHIB", "BNB", "SUI",
    "LINK", "UNI", "ONDO", "AAVE", "BCH", "BOME", "FIL", "AVAX",
    "NEAR", "GPS", "LTC", "PENGU", "XLM", "ORDI", "PEOPLE", "CRV",
    "ETC", "TRX", "JTO", "OP", "ARB", "ETHFI", "ICP",
]

LABEL_HORIZON = 24


def _ann_vol(close: pd.Series, window: int) -> pd.Series:
    ret = np.log(close).diff()
    return ret.rolling(window, min_periods=window // 2).std() * np.sqrt(24 * 365)


def load_oi_frame() -> pd.DataFrame:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT symbol, timestamp, open_interest FROM open_interest_history "
            "WHERE exchange='binanceusdm' ORDER BY symbol, timestamp"
        ).fetchall()
    finally:
        conn.close()
    fr = pd.DataFrame(rows, columns=["symbol_raw", "timestamp", "oi"])
    # BTCUSDT -> BTC ; skip non-pool formats defensively
    fr["base"] = fr["symbol_raw"].str.replace("USDT", "", regex=False)
    return fr[["base", "timestamp", "oi"]]


def build_symbol_frame(store, symbol: str, oi_frame: pd.DataFrame | None) -> pd.DataFrame | None:
    recs = store.read_klines("okx", symbol, "1h")
    if not recs or len(recs) < 1500:
        return None
    df = pd.DataFrame(recs)[["timestamp", "open", "high", "low", "close", "volume"]]
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["timestamp"] = df["timestamp"].astype("int64")
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)

    c, h, l, o, v = df["close"], df["high"], df["low"], df["open"], df["volume"]
    f = pd.DataFrame({"symbol": symbol, "timestamp": df["timestamp"]})

    for w in (6, 24, 72, 168, 360, 720):
        f[f"ret_{w}h"] = c.pct_change(w)

    f["vol_240"] = _ann_vol(c, 240)
    f["vol_720"] = _ann_vol(c, 720)
    f["vol_ratio"] = f["vol_240"] / f["vol_720"]

    ret1 = np.log(c).diff()
    for w in (72, 168, 720):
        std = ret1.rolling(w, min_periods=w // 2).std()
        base = c.shift(w)
        fwd_ret = c / base - 1.0
        f[f"sharpe_{w}"] = (fwd_ret / std.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    ema = lambda s, w: s.ewm(span=w, adjust=False, min_periods=w).mean()
    f["ema_dist_55"] = c / ema(c, 55) - 1.0
    f["ema_dist_200"] = c / ema(c, 200) - 1.0
    f["ema_ratio_5_20"] = ema(c, 5) / ema(c, 20) - 1.0

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

    for w in (120, 480, 1440):
        lo = l.rolling(w, min_periods=w // 2).min()
        hi = h.rolling(w, min_periods=w // 2).max()
        f[f"pos_{w}"] = (c - lo) / (hi - lo).replace(0, np.nan)
    f["dd_high_480"] = c / h.rolling(480, min_periods=240).max() - 1.0

    f["vol_ratio_6_72"] = v.rolling(6).mean() / v.rolling(72).mean().replace(0, np.nan)
    f["turnover_mean_24"] = (c * v).rolling(24).mean()

    rng = (h - l).replace(0, np.nan)
    f["body_mean_12"] = ((c - o).abs() / rng).rolling(12).mean()
    f["upper_wick_mean_12"] = ((h - np.maximum(c, o)) / rng).rolling(12).mean()
    f["green_pct_12"] = (c > o).astype(float).rolling(12).mean()

    ma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std()
    bb_width = 2 * sd20 / ma20.replace(0, np.nan)
    f["bb_width_pctile_96"] = bb_width.rolling(96, min_periods=48).rank(pct=True)

    f["fwd_ret_24"] = c.shift(-LABEL_HORIZON) / c - 1.0

    # ---- OI dynamics (join hourly backfilled series) ----
    if oi_frame is not None and len(oi_frame):
        og = oi_frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
        merged = pd.merge_asof(
            f.sort_values("timestamp"), og, on="timestamp", direction="backward",
            tolerance=2 * 3_600_000,
        )
        oi = merged["oi"]
        f["oi_change_24h"] = oi / oi.shift(24) - 1.0
        f["oi_change_72h"] = oi / oi.shift(72) - 1.0
        f["oi_percentile_30d"] = oi.rolling(720, min_periods=240).rank(pct=True)
        f["oi_mom_interaction"] = f["oi_change_24h"] * f["ret_24h"]
        f["price_oi_divergence"] = f["ret_24h"] - f["oi_change_24h"]
    return f


def main():
    store = KlineFileStore()
    oi_frame = load_oi_frame()
    print(f"[OI] rows={len(oi_frame)} bases={oi_frame['base'].nunique()}", flush=True)

    frames = []
    for base in TOP39_BASES:
        symbol = f"{base}/USDT:USDT"
        og = oi_frame[oi_frame["base"] == base]
        fr = build_symbol_frame(store, symbol, og if len(og) else None)
        if fr is not None:
            frames.append(fr)
    panel = pd.concat(frames, ignore_index=True)

    panel["xsec_rank_ret24"] = panel.groupby("timestamp")["ret_24h"].rank(pct=True)
    panel["xsec_rank_sharpe168"] = panel.groupby("timestamp")["sharpe_168"].rank(pct=True)

    grp = panel.groupby("timestamp")["fwd_ret_24"]
    mu, sd = grp.transform("mean"), grp.transform("std").replace(0, np.nan)
    panel["label_z"] = (panel["fwd_ret_24"] - mu) / sd

    feature_cols = [c for c in panel.columns if c not in
                    ("symbol", "timestamp", "fwd_ret_24", "label_z")]
    panel = panel.dropna(subset=["label_z"])
    out = Path("/tmp/ml_research")
    out.mkdir(exist_ok=True)
    panel.to_parquet(out / "factor_panel_c.parquet", index=False)
    oi_cov = panel["oi_change_24h"].notna().mean() if "oi_change_24h" in panel else 0.0
    meta = {
        "symbols": sorted(panel["symbol"].unique().tolist()),
        "rows": int(len(panel)),
        "feature_cols": feature_cols,
        "label_horizon_bars": LABEL_HORIZON,
        "t_min": str(pd.to_datetime(panel["timestamp"].min(), unit="ms")),
        "t_max": str(pd.to_datetime(panel["timestamp"].max(), unit="ms")),
        "round": "C",
        "changes_vs_A": ["no list_age_days", "added 5 OI dynamics features (binanceusdm backfill 2022-01~)"],
        "oi_feature_coverage": round(float(oi_cov), 4),
    }
    (out / "panel_meta_c.json").write_text(json.dumps(meta, indent=2))
    print(f"PANEL_C rows={len(panel)} features={len(feature_cols)} oi_coverage={oi_cov:.1%}")
    print(meta["t_min"], "->", meta["t_max"])


if __name__ == "__main__":
    main()
