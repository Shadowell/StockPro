#!/usr/bin/env python3
"""Walk-forward LightGBM cross-sectional ranking training.

Protocol (contract lightgbm-cross-sectional-ranking-ab.md):
- expanding train window, min 365d history, step 30d
- embargo 48h (> label horizon 24h) between train tail and test head
- target: cross-sectionally z-scored forward 24h return
- output: out-of-sample scores parquet + per-fold RankIC stats

Run on the production host with the project venv.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

OUT = Path("/tmp/ml_research")
SEED = 20260824
MIN_TRAIN_DAYS = 365
STEP_DAYS = 30
EMBARGO_H = 48


def rankic(score: pd.Series, label: pd.Series) -> float:
    df = pd.DataFrame({"s": score, "l": label}).dropna()
    if len(df) < 30:
        return np.nan
    return df["s"].rank().corr(df["l"].rank())


def main():
    panel = pd.read_parquet(OUT / "factor_panel.parquet")
    meta = json.loads((OUT / "panel_meta.json").read_text())
    features = meta["feature_cols"]
    panel = panel.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    ts_unique = np.sort(panel["timestamp"].unique())

    t_min = pd.Timestamp(panel["timestamp"].min(), unit="ms")
    test_start = pd.Timestamp("2025-07-01 00:00:00")
    t_max = pd.Timestamp(panel["timestamp"].max(), unit="ms")
    print(f"panel {t_min:%Y-%m-%d} -> {t_max:%Y-%m-%d}, folds start {test_start:%Y-%m-%d}")

    oos_frames = []
    fold_stats = []
    fold_id = 0
    cur = test_start
    while cur <= t_max:
        cur_end = cur + pd.Timedelta(days=STEP_DAYS)
        train_cut = cur - pd.Timedelta(hours=EMBARGO_H)  # embargo gap before test window
        cut_ms_train = int(train_cut.timestamp() * 1000)
        cut_ms_test_end = int(min(cur_end, t_max + pd.Timedelta(hours=1)).timestamp() * 1000)
        cut_ms_test_start = int(cur.timestamp() * 1000)

        tr = panel[panel["timestamp"] < cut_ms_train]
        te = panel[(panel["timestamp"] >= cut_ms_test_start) & (panel["timestamp"] < cut_ms_test_end)]
        if len(tr) == 0 or len(te) == 0:
            cur = cur_end
            continue
        # enforce min train history span
        span_days = (tr["timestamp"].max() - tr["timestamp"].min()) / 86_400_000.0
        if span_days < MIN_TRAIN_DAYS:
            print(f"fold {fold_id}: train span {span_days:.0f}d < {MIN_TRAIN_DAYS}d, skip")
            cur = cur_end
            fold_id += 1
            continue

        # internal time-based early-stop split (last 15% of train timestamps)
        tr_ts_sorted = np.sort(tr["timestamp"].unique())
        es_cut = tr_ts_sorted[int(len(tr_ts_sorted) * 0.85)]
        tr_fit = tr[tr["timestamp"] <= es_cut]
        tr_es = tr[tr["timestamp"] > es_cut]

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
        model.fit(
            tr_fit[features], tr_fit["label"],
            eval_set=[(tr_es[features], tr_es["label"])],
            eval_metric="l2",
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )
        pred = model.predict(te[features])
        te = te.assign(score=pred)
        oos_frames.append(te[["symbol", "timestamp", "score", "label"]])

        ic_mean = (
            te.groupby("timestamp").apply(lambda g: rankic(g["score"], g["label"]), include_groups=False)
            .dropna()
        )
        fold_stats.append({
            "fold": fold_id,
            "test_start": str(cur.date()),
            "test_end": str(pd.Timestamp(cut_ms_test_end, unit="ms").date()),
            "train_rows": int(len(tr)),
            "best_iter": int(model.best_iteration_ or model.n_estimators),
            "rankic_mean": float(ic_mean.mean()) if len(ic_mean) else None,
            "rankic_ir": float(ic_mean.mean() / ic_mean.std()) if len(ic_mean) > 1 and ic_mean.std() > 0 else None,
        })
        s = fold_stats[-1]
        print(f"fold {fold_id:>2} {s['test_start']}~{s['test_end']} rows={s['train_rows']:>7} "
              f"iter={s['best_iter']:>3} rankIC={s['rankic_mean']:+.4f} ICIR={s['rankic_ir']}",
              flush=True)
        cur = cur_end
        fold_id += 1

    oos = pd.concat(oos_frames, ignore_index=True)
    oos.to_parquet(OUT / "oos_scores.parquet", index=False)
    valid = [f for f in fold_stats if f["rankic_mean"] is not None]
    summary = {
        "seed": SEED,
        "protocol": {"min_train_days": MIN_TRAIN_DAYS, "step_days": STEP_DAYS, "embargo_h": EMBARGO_H},
        "folds": fold_stats,
        "overall_rankic_mean": float(np.mean([f["rankic_mean"] for f in valid])),
        "overall_rankic_ir": float(np.mean([f["rankic_ir"] for f in valid])),
        "oos_rows": int(len(oos)),
        "oos_span": [str(pd.Timestamp(oos['timestamp'].min(), unit='ms').date()),
                      str(pd.Timestamp(oos['timestamp'].max(), unit='ms').date())],
        "top_features": [
            {"f": f, "gain": float(g)} for f, g in sorted(
                zip(features, model.feature_importances_), key=lambda x: -x[1])[:12]
        ],
    }
    (OUT / "train_summary.json").write_text(json.dumps(summary, indent=2))
    print("\nOVERALL rankIC=%.4f ICIR=%.3f oos_rows=%d span=%s"
          % (summary["overall_rankic_mean"], summary["overall_rankic_ir"],
             summary["oos_rows"], summary["oos_span"]))
    print("top features:", [(x["f"], round(x["gain"])) for x in summary["top_features"][:8]])


if __name__ == "__main__":
    main()
