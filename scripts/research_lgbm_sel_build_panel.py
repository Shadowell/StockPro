#!/usr/bin/env python3
"""LightGBM 日内选币研究：构建 15M 因子面板（合同 lightgbm-intraday-selection-research.md）。

只读生产 OKX 文件 K 线存储（真实 OHLCV），输出带点时（point-in-time）流动性过滤列的
因子面板 + 多视域前向标签。在服务器 venv 执行：

    /opt/bitpro/backend/venv/bin/python scripts/research_lgbm_sel_build_panel.py \
        --out /tmp/ml_research/sel/panel_v1.parquet

防前视约定：
- 特征只用 <= 当前 15M 已收盘 bar 的数据；
- 标签从决策 bar 的下一根开盘价起算（open[t+1] -> open[t+1+H]）；
- 流动性/覆盖过滤列用"上一个已完成交易日"及更早的滚动统计。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BARS_PER_DAY_15M = 96
MS_DAY = 86_400_000


def _ann_vol(close: pd.Series, window: int) -> pd.Series:
    ret = np.log(close).replace([np.inf, -np.inf], np.nan).diff()
    return ret.rolling(window, min_periods=window // 2).std() * np.sqrt(
        BARS_PER_DAY_15M * 365
    )


def _wilder_adx(h: pd.Series, l: pd.Series, c: pd.Series, window: int = 14) -> pd.Series:
    up = h.diff()
    dn = -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    pdi = 100 * plus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean() / atr
    mdi = 100 * minus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean() / atr
    denom = (pdi + mdi).replace(0, np.nan)
    dx = ((pdi - mdi).abs() / denom * 100).replace([np.inf, -np.inf], np.nan)
    return dx.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def _ema(s: pd.Series, w: int) -> pd.Series:
    return s.ewm(span=w, adjust=False, min_periods=w // 2).mean()


def load_symbol(kroot: Path, symbol_dir: str, timeframe: str) -> pd.DataFrame | None:
    d = kroot / symbol_dir / timeframe
    if not d.is_dir():
        return None
    frames = []
    for f in sorted(d.glob("*.parquet")):
        try:
            frames.append(pd.read_parquet(f))
        except Exception as e:  # noqa: BLE001
            print(f"  warn: read {f.name}: {e}", file=sys.stderr)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["timestamp"] = df["timestamp"].astype("int64")
    df = (
        df.drop_duplicates("timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    for col in ("open", "high", "low", "close", "volume", "quote_volume"):
        if col not in df.columns:
            return None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df["close"] > 0) & (df["high"] >= df["low"])]
    return df.reset_index(drop=True)


def build_symbol_frame(df: pd.DataFrame, symbol: str, horizons: list[int],
                       cost_rt: float, feat_version: str) -> pd.DataFrame | None:
    if len(df) < 2000:
        return None
    o, h, l, c, qv = df["open"], df["high"], df["low"], df["close"], df["quote_volume"]
    f = pd.DataFrame({"symbol": symbol, "timestamp": df["timestamp"].astype("int64")})

    # --- 收益族 ---
    for w in (4, 16, 48, 96, 480):
        f[f"ret_{w}"] = c.pct_change(w)

    # --- 波动率 ---
    f["vol_96"] = _ann_vol(c, 96)
    f["vol_480"] = _ann_vol(c, 480)
    f["vol_ratio"] = f["vol_96"] / f["vol_480"].replace(0, np.nan)

    # --- 风险调整动量 ---
    r1 = np.log(c).diff()
    for w in (96, 480):
        std = r1.rolling(w, min_periods=w // 2).std()
        base = c.shift(w)
        fwd = c / base.replace(0, np.nan) - 1.0
        f[f"sharpe_{w}"] = (fwd / std.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    # --- 趋势结构 ---
    f["ema_dist_192"] = c / _ema(c, 192) - 1.0
    f["ema_dist_960"] = c / _ema(c, 960) - 1.0
    f["ema_ratio_20_80"] = _ema(c, 20) / _ema(c, 80).replace(0, np.nan) - 1.0

    # --- ADX ---
    f["adx_14"] = _wilder_adx(h, l, c, 14)

    # --- 区间位置 ---
    for w in (192, 960):
        lo = l.rolling(w, min_periods=w // 2).min()
        hi = h.rolling(w, min_periods=w // 2).max()
        f[f"pos_{w}"] = (c - lo) / (hi - lo).replace(0, np.nan)
    f["dd_high_960"] = c / h.rolling(960, min_periods=480).max() - 1.0

    # --- 量能 ---
    f["qvol_z_96"] = (
        (qv - qv.rolling(96).mean()) / qv.rolling(96).std().replace(0, np.nan)
    ).clip(-10, 10)
    f["qvol_ratio_4_96"] = qv.rolling(4).mean() / qv.rolling(96).mean().replace(0, np.nan)

    # --- K 线形态 ---
    rng = (h - l).replace(0, np.nan)
    f["body_mean_16"] = ((c - o).abs() / rng).rolling(16).mean()
    f["upper_wick_mean_16"] = ((h - np.maximum(c, o)) / rng).rolling(16).mean()
    f["green_pct_16"] = (c > o).astype(np.float32).rolling(16).mean()

    # --- 微观反转 ---
    f["ret_1"] = c.pct_change(1)
    f["ret_2"] = c.pct_change(2)

    # --- 时间上下文 ---
    ts_dt = pd.to_datetime(f["timestamp"], unit="ms")
    f["hour"] = ts_dt.dt.hour.astype(np.int16)
    f["dow"] = ts_dt.dt.dayofweek.astype(np.int16)

    # --- ATR%（供回测止损用） ---
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    f["atr14_pct"] = (
        tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / c.replace(0, np.nan)
    )

    # --- 历史天数 ---
    f["hist_days"] = (f["timestamp"] - f["timestamp"].iloc[0]) / MS_DAY

    # --- 标签：下一根开盘 -> H 根后开盘 ---
    next_open = o.shift(-1)
    for hdz in horizons:
        fwd = o.shift(-(hdz + 1)) / next_open.replace(0, np.nan) - 1.0
        f[f"fwd_ret_raw_{hdz}"] = fwd
        f[f"fwd_ret_net_{hdz}"] = fwd - cost_rt

    # --- 点时流动性列（用上一已完成日及更早的滚动统计，防未来信息） ---
    day = (df["timestamp"].astype("int64") // MS_DAY).astype("int64")
    daily = pd.DataFrame({"day": day, "qv": qv})
    daily_sum = daily.groupby("day")["qv"].sum()
    liq_roll = daily_sum.rolling(30, min_periods=20).median().shift(1)  # 上一个已完成日起
    bar_cnt = daily.groupby("day").size()
    cov_roll = (bar_cnt / BARS_PER_DAY_15M).rolling(7, min_periods=5).mean().shift(1)
    f["liq30d_med_usdt"] = day.map(liq_roll)
    f["cov7d"] = day.map(cov_roll)

    # --- 手写基线分数（A/B 对照用，不进特征） ---
    f["hand_mom"] = 0.5 * f["sharpe_96"] + 0.5 * f["sharpe_480"]

    # 内存保护：特征与标签统一降为 float32（timestamp 保持 int64）
    for col in f.columns:
        if col != "symbol" and str(f[col].dtype) == "float64":
            f[col] = f[col].astype(np.float32)
    return f


def add_cross_section(panel: pd.DataFrame) -> pd.DataFrame:
    g = panel.groupby("timestamp", sort=False)
    panel["xsec_rank_ret_16"] = g["ret_16"].rank(pct=True)
    panel["xsec_rank_ret_96"] = g["ret_96"].rank(pct=True)
    panel["xsec_rank_hand"] = g["hand_mom"].rank(pct=True)
    panel["xsec_n"] = g["symbol"].transform("size").astype(np.int32)

    btc = panel[panel["symbol"] == "BTC-USDT_USDT"][["timestamp", "ret_16", "ret_96"]]
    btc = btc.rename(columns={"ret_16": "btc_ret_16", "ret_96": "btc_ret_96"})
    panel = panel.merge(btc, on="timestamp", how="left")
    panel["btc_rel_ret_16"] = panel["ret_16"] - panel["btc_ret_16"]
    panel["btc_rel_ret_96"] = panel["ret_96"] - panel["btc_ret_96"]
    return panel.drop(columns=["btc_ret_16", "btc_ret_96"])


def zscore_label(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    grp = panel.groupby("timestamp")[f"fwd_ret_raw_{horizon}"]
    mu = grp.transform("mean")
    sd = grp.transform("std").replace(0, np.nan)
    panel[f"label_z_{horizon}"] = ((panel[f"fwd_ret_raw_{horizon}"] - mu) / sd).clip(-5, 5)
    return panel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kline-root", default="/opt/bitpro/data/klines/okx")
    ap.add_argument("--timeframe", default="15m")
    ap.add_argument("--horizons", default="8,16,32")
    ap.add_argument("--cost-rt", type=float, default=0.0020,
                    help="往返成本估计（扣进 net 标签）")
    ap.add_argument("--feat-version", default="1")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    horizons = [int(x) for x in args.horizons.split(",")]
    kroot = Path(args.kline_root)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    perp_dirs = sorted(
        p.name for p in kroot.iterdir()
        if p.is_dir() and p.name.endswith("-USDT_USDT")
    )
    print(f"universe candidates: {len(perp_dirs)} perp symbols", flush=True)

    t0 = time.time()
    frames = []
    kept = skipped = 0
    for i, sd in enumerate(perp_dirs):
        try:
            raw = load_symbol(kroot, sd, args.timeframe)
        except Exception as e:  # noqa: BLE001
            print(f"skip {sd}: {e}", file=sys.stderr)
            skipped += 1
            continue
        if raw is None or len(raw) < 2000:
            skipped += 1
            continue
        fr = build_symbol_frame(raw, sd, horizons, args.cost_rt, args.feat_version)
        if fr is None:
            skipped += 1
            continue
        frames.append(fr)
        kept += 1
        if kept % 25 == 0:
            print(f"  built {kept} symbols ({time.time()-t0:.0f}s)", flush=True)

    if not frames:
        print("no usable symbols", file=sys.stderr)
        sys.exit(1)

    panel = pd.concat(frames, ignore_index=True)
    del frames
    print(f"raw panel rows={len(panel)} symbols={kept} skipped={skipped}", flush=True)

    panel = add_cross_section(panel)
    for hdz in horizons:
        panel = zscore_label(panel, hdz)
    meta_cols = {"symbol", "timestamp"}
    label_cols = {c for c in panel.columns if c.startswith(("fwd_", "label_z_"))}
    aux_cols = {"liq30d_med_usdt", "cov7d", "hist_days", "atr14_pct", "xsec_n",
                "hand_mom"}
    feature_cols = sorted(
        c for c in panel.columns
        if c not in meta_cols | label_cols | aux_cols
    )

    # float32 压缩特征列
    for col in feature_cols:
        if panel[col].dtype == np.float64:
            panel[col] = panel[col].astype(np.float32)

    panel.to_parquet(out_path, index=False)
    tmin = pd.to_datetime(panel["timestamp"].min(), unit="ms")
    tmax = pd.to_datetime(panel["timestamp"].max(), unit="ms")
    meta = {
        "rows": int(len(panel)),
        "symbols": sorted(panel["symbol"].unique().tolist()),
        "n_symbols": int(panel["symbol"].nunique()),
        "feature_cols": feature_cols,
        "aux_cols": sorted(aux_cols),
        "label_cols": sorted(label_cols),
        "horizons": horizons,
        "cost_rt": args.cost_rt,
        "feat_version": args.feat_version,
        "t_min": str(tmin),
        "t_max": str(tmax),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    out_path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: v for k, v in meta.items() if k != "symbols"}, indent=2))
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
