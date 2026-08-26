"""[合约][1H][CTA] Top39 · 截面动量ML门禁组合 · 100U

部署版策略：生产 446 的手写动量排序完全保留，LightGBM 每日样本外分数
仅作为入场门禁——多头候选需 ml_score > 截面中位（标准化后 > 0），
空头候选需 < 中位；被 ML 否决的候选沉到排序序列中部，
截面失效退出随新序列一致生效。

与回测证据的对应关系见 docs/contracts/lightgbm-cross-sectional-ranking-ab.md：
filterC 变体主窗 +20.39%/PF1.151（同期基线 +23.06%/PF1.159），未跑赢基线；
上盘定位是 paper 观察验证，不替代 446。分数表由数据中心调度每日运行
scripts/ml_daily_inference.py 生成（严格时序切分、embargo 48h 的样本外推理），
禁止用全量重训分数伪装绩效。

分数查表容忍龄期（config.ml_max_score_age_hours，默认 72h）：优先精确
时间戳匹配，否则回退到该标的最新可用分数；无分数时默认放行，
不因数据缺失改变基线行为。
"""

from __future__ import annotations

import pandas as pd

from app.strategies.xs_momentum_vol_target_base import (
    CrossSectionalMomentumVolTargetStrategy,
)


class XSMomentumMLGateStrategy(CrossSectionalMomentumVolTargetStrategy):
    """手写动量排序 + LightGBM 样本外分数入场门禁的组合策略。"""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config
        path = str(cfg.get("ml_scores_path", "") or "")
        if not path:
            raise ValueError("XSMomentumMLGateStrategy 需要 config.ml_scores_path")
        frame = pd.read_parquet(path)
        # 分数按时间戳做池内标准化，保证多空两侧门禁阈值可比
        def _xsec_zscore(s: pd.Series) -> pd.Series:
            sd = s.std()
            if pd.isna(sd) or sd == 0:
                sd = 1.0
            return (s - s.mean()) / sd

        frame["score"] = frame.groupby("timestamp")["score"].transform(_xsec_zscore)
        self._ml_score_map = {
            (str(sym), int(ts)): float(s)
            for sym, ts, s in zip(frame["symbol"], frame["timestamp"], frame["score"])
        }
        self._ml_min_timestamp = int(frame["timestamp"].min())
        self._ml_max_timestamp = int(frame["timestamp"].max())
        # 每日推理节奏下，查表容忍分数龄期（默认 72h）
        self._ml_max_age_ms = int(float(cfg.get("ml_max_score_age_hours", 72)) * 3_600_000)
        self._ml_latest_ts_by_symbol: dict = {}
        for (sym, ts) in self._ml_score_map.keys():
            prev = self._ml_latest_ts_by_symbol.get(sym)
            if prev is None or ts > prev:
                self._ml_latest_ts_by_symbol[sym] = ts

    def _lookup_score(self, symbol, aligned_ts):
        aligned_ts = int(aligned_ts)
        # 不设全局上界：每日推理节奏下 aligned_ts 常领先最新分数数小时，
        # 未来越界由下方龄期检查兜住；早于表起点则视为无分数。
        if aligned_ts < self._ml_min_timestamp:
            return None
        exact = self._ml_score_map.get((symbol, aligned_ts))
        if exact is not None:
            return exact
        # 回退：该标的 <= aligned_ts 的最新可用分数（超龄视为无分数）
        latest = self._ml_latest_ts_by_symbol.get(symbol)
        if latest is None or latest > aligned_ts or aligned_ts - latest > self._ml_max_age_ms:
            return None
        return self._ml_score_map.get((symbol, latest))

    def _compute_cross_section(self, aligned_ts):
        """446 原始截面排序 + LightGBM 门禁重组。

        与回测 filterC 实现一致：通过门禁者占据两端候选区，
        被否决者沉到中部保持相对顺序；无分数默认放行。
        """
        scored = super()._compute_cross_section(aligned_ts)
        n = len(scored)
        if n < 3:
            return scored
        k = max(1, int(round(n * self.rank_pct_long)))
        ks = max(1, int(round(n * self.rank_pct_short)))

        long_zone = scored[:k]
        middle = scored[k:n - ks] if n - ks > k else []
        short_zone = scored[n - ks:]

        passed_long, rejected_long = [], []
        for item in long_zone:
            s = self._lookup_score(item["symbol"], aligned_ts)
            if s is not None and s <= 0:
                rejected_long.append(item)
            else:
                passed_long.append(item)
        passed_short, rejected_short = [], []
        for item in short_zone:
            s = self._lookup_score(item["symbol"], aligned_ts)
            if s is not None and s >= 0:
                rejected_short.append(item)
            else:
                passed_short.append(item)

        return passed_long + rejected_long + middle + rejected_short + passed_short
