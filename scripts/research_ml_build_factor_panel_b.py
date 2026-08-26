#!/usr/bin/env python3
"""Round B: rebuild factor panel (drop list_age_days, add real funding features).

Funding history is fetched from the OKX public API into production
funding_rate_history via the existing backtest-engine cache path (same source
the official Backtrader funding cashflows use), then joined as features.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.kline_file_store import KlineFileStore  # noqa: E402

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


def ensure_funding_history() -> dict:
    """Fetch full OKX funding history for the pool via the engine cache path."""
    from app.services.backtrader_engine import BacktestEngine

    start_ms = int(datetime(2023, 12, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    fetched_map = {}
    for sym in TOP39:
        try:
            n = BacktestEngine._fetch_and_cache_okx_funding_history(sym, start_ms, end_ms)
            fetched_map[sym] = n
        except Exception as exc:
            print(f"funding fetch fail {sym}: {exc!r}")
            fetched_map[sym] = 0
    total = sum(fetched_map.values())
    print(f"[FUNDING] fetched rows total={total}, per-symbol min={min(fetched_map.values())}", flush=True)
    return fetched_map


def load_funding_frame():
    import sqlite3

    conn = sqlite3.connect("/opt/bitpro/data/crypto_data.db")
    rows = conn.execute(
        """
        SELECT symbol, timestamp, funding_rate FROM funding_rate_history
        WHERE exchange='okx' AND timestamp > 1701388800000
        ORDER BY symbol, timestamp
        """
    ).fetchall()
    conn.close()
    fr = pd.DataFrame(rows, columns=["symbol_raw", "timestamp", "funding_rate"])
    # normalize alias forms to BitPro symbol format
    def norm(s):
        s = str(s)
        if s.endswith("-SWAP"):
            base = s[: -len("-SWAP")]
            return f"{base}/USDT:USDT"
        return s
    fr["symbol"] = fr["symbol_raw"].map(norm)
    return fr[["symbol", "timestamp", "funding_rate"]]


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
    return f


def attach_funding(panel: pd.DataFrame, fr: pd.DataFrame) -> pd.DataFrame:
    fr = fr.sort_values(["symbol", "timestamp"])
    # forward-fill funding onto hourly grid per symbol
    pieces = []
    for sym, g in panel.groupby("symbol", sort=False):
        fg = fr[fr["symbol"] == sym]
        if fg.empty:
            g = g.copy()
            g["funding_rate"] = np.nan
            pieces.append(g)
            continue
        merged = pd.merge_asof(
            g.sort_values("timestamp"), fg.sort_values("timestamp"),
            on="timestamp", by="symbol", direction="backward", tolerance=9 * 3_600_000,
        )
        pieces.append(merged)
    panel = pd.concat(pieces, ignore_index=True)

    # funding features: level, rolling means, delta; cross-sectional rank of level
    panel = panel.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    g = panel.groupby("symbol")["funding_rate"]
    panel["funding_ma24"] = g.transform(lambda s: s.rolling(24 // 8 * 24, min_periods=3).mean())  # 8h cadence -> ~3 samples/day
    panel["funding_ma72"] = g.transform(lambda s: s.rolling(27, min_periods=6).mean())
    panel["funding_delta"] = panel["funding_rate"] - g.transform(lambda s: s.shift(3))
    panel["funding_xsec_rank"] = panel.groupby("timestamp")["funding_rate"].rank(pct=True)
    return panel


def main():
    store = KlineFileStore()
    ensure_funding_history()
    fr = load_funding_frame()
    print("[FUNDING] cached rows:", len(fr))

    frames = []
    for sym in TOP39:
        f = build_symbol_frame(store, sym)
        if f is not None:
            frames.append(f)
    panel = pd.concat(frames, ignore_index=True)

    panel["xsec_rank_ret24"] = panel.groupby("timestamp")["ret_24h"].rank(pct=True)
    panel["xsec_rank_sharpe168"] = panel.groupby("timestamp")["sharpe_168"].rank(pct=True)

    panel = attach_funding(panel, fr)

    grp = panel.groupby("timestamp")["fwd_ret_24"]
    mu, sd = grp.transform("mean"), grp.transform("std").replace(0, np.nan)
    panel["label_z"] = (panel["fwd_ret_24"] - mu) / sd

    feature_cols = [c for c in panel.columns if c not in
                    ("symbol", "timestamp", "fwd_ret_24", "label_z")]
    panel = panel.dropna(subset=["label_z"])
    out = Path("/tmp/ml_research")
    out.mkdir(exist_ok=True)
    panel.to_parquet(out / "factor_panel_b.parquet", index=False)
    meta = {
        "symbols": sorted(panel["symbol"].unique().tolist()),
        "rows": int(len(panel)),
        "feature_cols": feature_cols,
        "label_horizon_bars": LABEL_HORIZON,
        "t_min": str(pd.to_datetime(panel["timestamp"].min(), unit="ms")),
        "t_max": str(pd.to_datetime(panel["timestamp"].max(), unit="ms")),
        "changes_vs_round_a": ["removed list_age_days", "added funding_rate/ma24/ma72/delta/xsec_rank"],
    }
    (out / "panel_meta_b.json").write_text(json.dumps(meta, indent=2))
    cov = panel["funding_rate"].notna().mean()
    print(f"PANEL_B rows={len(panel)} features={len(feature_cols)} funding_coverage={cov:.1%}")


if __name__ == "__main__":
    main()
