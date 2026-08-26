#!/usr/bin/env python3
"""融合多视域 OOS 分数：按时间戳内排名加权平均。

用法：
    python scripts/research_lgbm_sel_blend_scores.py \
        --inputs a.parquet:b.parquet --weights 0.6:0.4 \
        --out blend.parquet

输出保留第一个输入的全部列，score 列替换为融合排名分。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True, help="冒号分隔的分数 parquet 列表")
    ap.add_argument("--weights", default="", help="冒号分隔权重，缺省等权")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    paths = [Path(p) for p in args.inputs.split(":") if p]
    ws = ([float(x) for x in args.weights.split(":") if x]
          if args.weights else [1.0] * len(paths))
    if len(ws) != len(paths):
        raise SystemExit("weights 数量与 inputs 不一致")

    base = pd.read_parquet(paths[0])
    base = base.drop(columns=["score"])
    rank_sum = None
    for i, (p, w) in enumerate(zip(paths, ws)):
        df = pd.read_parquet(p, columns=["symbol", "timestamp", "score"])
        r = df.groupby("timestamp")["score"].rank(method="first", pct=True) * w
        part = df[["symbol", "timestamp"]].copy()
        part[f"r{i}"] = r.to_numpy()
        rank_sum = part if rank_sum is None else rank_sum.merge(
            part, on=["symbol", "timestamp"], how="outer"
        )

    rcols = [f"r{i}" for i in range(len(paths))]
    rank_sum["score"] = rank_sum[rcols].fillna(0).sum(axis=1) / sum(ws)
    out_df = base.merge(rank_sum[["symbol", "timestamp", "score"]],
                        on=["symbol", "timestamp"], how="left")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_parquet(out, index=False)
    print(f"blended {len(paths)} inputs -> {out} rows={len(out_df)}")


if __name__ == "__main__":
    main()
