#!/usr/bin/env python3
"""Daily ML score inference for the cross-sectional momentum strategy.

Pipeline (run daily by the data-center scheduler via okx_native_sync_service
or manually):
1. Build the factor panel over the trailing `--panel-days` window using the
   exact feature engineering of research_ml_build_factor_panel_c.py (single
   source of truth, imported).
2. Train LGBMRegressor on all data up to (latest - embargo 48h).
3. Predict scores for the latest completed hourly bar of every symbol.
4. Append scores to a rolling live score table (parquet) that the paper
   strategy reads: /opt/bitpro/data/ml_scores/live_scores.parquet

The strategy-side lookup tolerates score age up to 72h, so a daily cadence is
sufficient. Scores are cross-sectionally z-scored per timestamp.

Run on the production host with the project venv:
    /opt/bitpro/backend/venv/bin/python scripts/ml_daily_inference.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from research_ml_build_factor_panel_c import (  # noqa: E402
    LABEL_HORIZON,
    TOP39_BASES,
    build_symbol_frame,
    load_oi_frame,
)

DEFAULT_OUT = Path("/opt/bitpro/data/ml_scores/live_scores.parquet")
EMBARGO_H = 48
SEED = 20260824


def build_recent_panel(store, panel_days: int) -> pd.DataFrame:
    oi_frame = load_oi_frame()
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

    # keep only the trailing window to bound training cost
    cutoff = panel["timestamp"].max() - panel_days * 86_400_000
    return panel[panel["timestamp"] >= cutoff].reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel-days", type=int, default=540)
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    parser.add_argument("--keep-rows", type=int, default=120 * 40, help="rolling rows kept (~120d x 40 syms)")
    args = parser.parse_args()

    from app.services.kline_file_store import KlineFileStore

    store = KlineFileStore()
    panel = build_recent_panel(store, args.panel_days)
    meta_features = [c for c in panel.columns if c not in
                     ("symbol", "timestamp", "fwd_ret_24", "label_z")]
    if panel.empty:
        print("[ml-inference] FAIL: empty panel")
        sys.exit(1)

    latest_ts = int(panel["timestamp"].max())
    embargo_cut = latest_ts - EMBARGO_H * 3_600_000
    train = panel[panel["timestamp"] <= embargo_cut].dropna(subset=["label_z"])
    # 每个标的取各自最新完成的 bar（数据进度不齐时仍覆盖全池）
    infer = panel.sort_values("timestamp").groupby("symbol", as_index=False).tail(1)

    if train.empty or infer.empty:
        print("[ml-inference] FAIL: train or inference set empty "
              f"(train={len(train)} infer={len(infer)})")
        sys.exit(1)

    model = lgb.LGBMRegressor(
        n_estimators=600,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=200,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_lambda=5.0,
        random_state=SEED,
        n_jobs=4,
        verbose=-1,
    )
    model.fit(train[meta_features], train["label_z"])

    scores = model.predict(infer[meta_features])
    out_frame = pd.DataFrame({
        "symbol": infer["symbol"].values,
        "timestamp": infer["timestamp"].values,
        "score": scores,
    })
    # cross-sectional standardization for filter/score comparability
    mean = out_frame["score"].mean()
    std = out_frame["score"].std()
    out_frame["score"] = (out_frame["score"] - mean) / (std if std and std > 0 else 1.0)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        try:
            old = pd.read_parquet(out_path)
            cutoff = latest_ts - args.keep_rows * 86_400_000 // 40
            old = old[old["timestamp"] >= cutoff]
            out_frame = pd.concat([old, out_frame]).drop_duplicates(
                ["symbol", "timestamp"], keep="last"
            )
        except Exception as exc:
            print(f"[ml-inference] WARN: could not merge with existing scores ({exc!r}); rewriting")
    out_frame.to_parquet(out_path, index=False)

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inference_timestamp": latest_ts,
        "inference_time": datetime.fromtimestamp(latest_ts / 1000, tz=timezone.utc).isoformat(),
        "symbols_scored": int(len(out_frame)),
        "train_rows": int(len(train)),
        "panel_rows": int(len(panel)),
        "score_range": [float(out_frame["score"].min()), float(out_frame["score"].max())],
    }
    out_path.with_suffix(".meta.json").write_text(json.dumps(report, indent=2))
    print("[ml-inference] OK:", json.dumps(report))


if __name__ == "__main__":
    main()
