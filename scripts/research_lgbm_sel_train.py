#!/usr/bin/env python3
"""LightGBM 日内选币研究：walk-forward 训练与 OOS 分数产出。

协议（合同 lightgbm-intraday-selection-research.md）：
- expanding 训练窗，最少 150 天，步长 30 天；embargo 48 根 15M（12h）；
- 目标为截面 z-score 回归（A 轮已证 LambdaRank 更差，不再重测）；
- 早停用训练窗内部最后 15% 时间戳；
- 点时流动性过滤后再进训练/预测，防止不可交易标的污染分数。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--horizon", type=int, default=16)
    ap.add_argument("--target", default="z", choices=["z", "net", "raw"])
    ap.add_argument("--test-start", default="2025-11-15")
    ap.add_argument("--dev-end", default="2026-06-30")
    ap.add_argument("--step-days", type=int, default=30)
    ap.add_argument("--min-train-days", type=int, default=150)
    ap.add_argument("--embargo-bars", type=int, default=48)
    ap.add_argument("--min-liq-usdt", type=float, default=3_000_000.0)
    ap.add_argument("--min-cov7d", type=float, default=0.90)
    ap.add_argument("--min-hist-days", type=float, default=60.0)
    ap.add_argument("--min-xsec", type=int, default=10)
    # 模型参数（轮次可调）
    ap.add_argument("--n-estimators", type=int, default=900)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    ap.add_argument("--num-leaves", type=int, default=31)
    ap.add_argument("--min-child-samples", type=int, default=300)
    ap.add_argument("--colsample", type=float, default=0.7)
    ap.add_argument("--reg-lambda", dest="reg_lambda", type=float, default=5.0)
    ap.add_argument("--feature-frac-extra", default="")
    ap.add_argument("--exclude-features", default="",
                    help="逗号分隔，从特征集中剔除")
    ap.add_argument("--ranker", default="lgbm", choices=["lgbm", "hand"],
                    help="hand=直接输出手写动量分数，不训练模型（A/B 对照）")
    ap.add_argument("--tail-weight-q", type=float, default=0.0,
                    help=">0 时对 |z 标签| 分位 >= 该值的样本加权 w-tail-mult")
    ap.add_argument("--tail-weight-mult", type=float, default=2.0)
    ap.add_argument("--time-decay-half-life-days", type=float, default=0.0,
                    help=">0 时按训练窗内时间做指数衰减权重")
    ap.add_argument("--seed", type=int, default=20260825)
    ap.add_argument("--tag", default="r1")
    return ap.parse_args()


def rankic(score: pd.Series, label: pd.Series) -> float:
    df = pd.DataFrame({"s": score, "l": label}).dropna()
    if len(df) < 30:
        return np.nan
    return df["s"].rank().corr(df["l"].rank())


def decile_spread(g: pd.DataFrame, target_net: str, q: float = 0.1) -> tuple[float, float]:
    """返回 (top-q 均值净收益, bottom-q 均值净收益)，按时间戳平均。"""
    n = len(g)
    k = max(1, int(round(n * q)))
    gs = g.sort_values("score", ascending=False)
    top = float(gs.head(k)[target_net].mean())
    bot = float(gs.tail(k)[target_net].mean())
    return top, bot


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = json.loads(Path(args.meta).read_text())
    features = list(meta["feature_cols"])
    for col in [x for x in args.exclude_features.split(",") if x]:
        if col in features:
            features.remove(col)
    horizon = args.horizon

    panel = pd.read_parquet(
        args.panel,
        columns=["symbol", "timestamp", f"label_z_{horizon}",
                 f"fwd_ret_raw_{horizon}", f"fwd_ret_net_{horizon}",
                 "liq30d_med_usdt", "cov7d", "hist_days", "xsec_n", "hand_mom"]
        + features,
    )
    n_full = len(panel)

    # ---- 点时可交易过滤 ----
    mask = (
        (panel["liq30d_med_usdt"] >= args.min_liq_usdt)
        & (panel["cov7d"] >= args.min_cov7d)
        & (panel["hist_days"] >= args.min_hist_days)
        & (panel["xsec_n"] >= args.min_xsec)
    )
    panel = panel[mask].reset_index(drop=True)
    print(f"panel {n_full} -> tradable {len(panel)} rows "
          f"({panel['symbol'].nunique()} symbols)", flush=True)

    target_col = {
        "z": f"label_z_{horizon}",
        "net": f"fwd_ret_net_{horizon}",
        "raw": f"fwd_ret_raw_{horizon}",
    }[args.target]
    panel = panel.dropna(subset=[target_col]).sort_values(
        ["timestamp", "symbol"]).reset_index(drop=True)

    ts_unique = np.sort(panel["timestamp"].unique())
    ts_index = pd.Series(np.arange(len(ts_unique)), index=ts_unique)
    panel["ts_ord"] = panel["timestamp"].map(ts_index).astype(np.int64)

    test_start_ms = int(pd.Timestamp(args.test_start).value // 10**6)
    dev_end_ms = int(pd.Timestamp(args.dev_end).value // 10**6)
    step_ms = args.step_days * 86_400_000
    embargo_bars = args.embargo_bars

    oos_frames = []
    fold_stats = []
    fold_id = 0
    cur = test_start_ms
    t0 = time.time()
    while cur < dev_end_ms:  # 严格小于：fold_end 被硬性截到 dev_end 后自然终止
        fold_end = min(cur + step_ms, dev_end_ms)
        tr_mask = panel["timestamp"] < cur - embargo_bars * 900_000
        te_mask = (panel["timestamp"] >= cur) & (panel["timestamp"] < fold_end)
        tr = panel[tr_mask]
        te = panel[te_mask]
        if len(tr) and len(te):
            span_days = (tr["timestamp"].max() - tr["timestamp"].min()) / 86_400_000
            if span_days >= args.min_train_days:
                if args.ranker == "hand":
                    te = te.assign(score=te["hand_mom"])
                else:
                    tr_sorted_ts = np.sort(tr["timestamp"].unique())
                    es_cut = tr_sorted_ts[int(len(tr_sorted_ts) * 0.85)]
                    fit = tr[tr["timestamp"] <= es_cut]
                    es = tr[tr["timestamp"] > es_cut]

                    fit_w = None
                    if args.tail_weight_q > 0 or args.time_decay_half_life_days > 0:
                        fit_w = np.ones(len(fit), dtype=np.float64)
                        if args.tail_weight_q > 0:
                            thr = float(
                                fit[target_col].abs().quantile(args.tail_weight_q)
                            )
                            fit_w[np.abs(fit[target_col].to_numpy()) >= thr] *= (
                                args.tail_weight_mult
                            )
                        if args.time_decay_half_life_days > 0:
                            t_min_fit = int(fit["timestamp"].min())
                            age_days = (
                                fit["timestamp"].to_numpy(np.float64) - t_min_fit
                            ) / 86_400_000.0
                            fit_w *= 0.5 ** (
                                age_days / args.time_decay_half_life_days
                            )

                    model = lgb.LGBMRegressor(
                        n_estimators=args.n_estimators,
                        learning_rate=args.learning_rate,
                        num_leaves=args.num_leaves,
                        min_child_samples=args.min_child_samples,
                        subsample=0.8,
                        subsample_freq=1,
                        colsample_bytree=args.colsample,
                        reg_lambda=args.reg_lambda,
                        random_state=args.seed,
                        n_jobs=4,
                        verbose=-1,
                    )
                    model.fit(
                        fit[features], fit[target_col],
                        sample_weight=fit_w,
                        eval_set=[(es[features], es[target_col])],
                        eval_metric="l2",
                        callbacks=[lgb.early_stopping(60, verbose=False)],
                    )
                    pred = model.predict(te[features])
                    te = te.assign(score=pred)

                ic = (
                    te.groupby("timestamp")
                    .apply(lambda g: rankic(g["score"], g[target_col]),
                           include_groups=False)
                    .dropna()
                )
                spreads = (
                    te.groupby("timestamp")
                    .apply(lambda g: decile_spread(g, f"fwd_ret_net_{horizon}"),
                           include_groups=False)
                )
                top_mean = float(np.mean([s[0] for s in spreads if s])) if len(spreads) else np.nan
                bot_mean = float(np.mean([s[1] for s in spreads if s])) if len(spreads) else np.nan
                stat = {
                    "fold": fold_id,
                    "test_start": str(pd.Timestamp(cur, unit="ms").date()),
                    "test_end": str(pd.Timestamp(min(fold_end, dev_end_ms + 1), unit="ms").date()),
                    "train_rows": int(len(tr)),
                    "train_span_days": round(float(span_days), 1),
                    "rankic_mean": float(ic.mean()) if len(ic) else None,
                    "rankic_ir": float(ic.mean() / ic.std()) if len(ic) > 1 and ic.std() > 0 else None,
                    "top_decile_net_mean": top_mean,
                    "bottom_decile_net_mean": bot_mean,
                }
                if args.ranker != "hand":
                    stat["best_iter"] = int(model.best_iteration_ or args.n_estimators)
                    gains = sorted(zip(features, model.feature_importances_),
                                   key=lambda x: -x[1])
                    stat["top_features"] = [
                        {"f": f, "gain": int(g)} for f, g in gains[:12]
                    ]
                fold_stats.append(stat)
                s = stat
                print(f"fold {fold_id:>2} {s['test_start']}~{s['test_end']} "
                      f"rows={s['train_rows']:>8} IC={s['rankic_mean']:+.4f} "
                      f"IR={s['rankic_ir'] if s['rankic_ir'] is None else round(s['rankic_ir'],3)} "
                      f"top={s['top_decile_net_mean']*1e4:+.1f}bp bot={s['bottom_decile_net_mean']*1e4:+.1f}bp",
                      flush=True)
                oos_frames.append(te[["symbol", "timestamp", "score",
                                      f"fwd_ret_raw_{horizon}", f"fwd_ret_net_{horizon}"]]
                                  .assign(fold=fold_id))
        cur = fold_end
        fold_id += 1

    if not oos_frames:
        print("no folds produced", file=sys.stderr)
        sys.exit(1)
    oos = pd.concat(oos_frames, ignore_index=True)
    scores_path = out_dir / f"scores_{args.tag}.parquet"
    oos.to_parquet(scores_path, index=False)

    valid = [f for f in fold_stats if f["rankic_mean"] is not None]
    summary = {
        "tag": args.tag,
        "args": vars(args),
        "protocol": {
            "min_train_days": args.min_train_days,
            "step_days": args.step_days,
            "embargo_bars_15m": args.embargo_bars,
            "universe_filter": {
                "min_liq_usdt": args.min_liq_usdt,
                "min_cov7d": args.min_cov7d,
                "min_hist_days": args.min_hist_days,
                "min_xsec": args.min_xsec,
            },
        },
        "features": features,
        "target": target_col,
        "n_folds": len(fold_stats),
        "overall_rankic_mean": float(np.nanmean([f["rankic_mean"] for f in valid])) if valid else None,
        "overall_rankic_ir": float(np.nanmean([f["rankic_ir"] for f in valid])) if valid else None,
        "positive_ic_folds": int(sum(1 for f in valid if (f["rankic_mean"] or 0) > 0)),
        "oos_rows": int(len(oos)),
        "oos_span": [str(pd.Timestamp(oos['timestamp'].min(), unit='ms').date()),
                     str(pd.Timestamp(oos['timestamp'].max(), unit='ms').date())],
        "folds": fold_stats,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    (out_dir / f"train_summary_{args.tag}.json").write_text(json.dumps(summary, indent=2))
    print(f"\nOVERALL IC={summary['overall_rankic_mean']:+.4f} "
          f"ICIR={summary['overall_rankic_ir']} "
          f"pos_folds={summary['positive_ic_folds']}/{summary['n_folds']}")
    print(f"scores -> {scores_path}")


if __name__ == "__main__":
    main()
