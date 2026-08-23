"""
Realtime feature builder for SuperPnL model inference.

The builder keeps an in-memory rolling window of confirmed 1m bars and creates
the same causal feature schema used by the SuperPnL training package. It does
not fetch data, read files, or fabricate missing bars.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.core.execution.base_strategy import BarData


@dataclass(frozen=True)
class SuperPnLFeatureBatch:
    timestamp_ms: int
    symbols: List[str]
    bar: np.ndarray
    features: np.ndarray


def normalize_superpnl_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace("/", "-").replace(":USDT", "")


def normalize_bitpro_symbol(symbol: str) -> str:
    text = normalize_superpnl_symbol(symbol)
    if "-" in text:
        base, quote = text.split("-", 1)
        return f"{base}/{quote}"
    return text


def canonical_bar_timestamp_ms(timestamp_ms: int) -> int:
    """Bucket realtime 1m bar events to the canonical minute timestamp."""
    ts = int(timestamp_ms)
    return ts - (ts % 60_000)


class SuperPnLFeatureBuilder:
    def __init__(
        self,
        *,
        symbols: Iterable[str],
        lookback: int,
        feature_windows: Iterable[int],
        bar_feature_names: Iterable[str],
        feature_names: Iterable[str],
    ) -> None:
        self.symbols = [normalize_bitpro_symbol(s) for s in symbols]
        self._super_symbols = [normalize_superpnl_symbol(s) for s in self.symbols]
        self.lookback = int(lookback)
        self.feature_windows = tuple(int(w) for w in feature_windows)
        self.max_window = max(self.feature_windows or (30,))
        self.history_bars = self.lookback + self.max_window + 1
        self.bar_feature_names = list(bar_feature_names)
        self.feature_names = list(feature_names)
        self._buffers: Dict[str, OrderedDict[int, BarData]] = {
            symbol: OrderedDict() for symbol in self.symbols
        }
        self._lock = threading.RLock()

    def update_bar(self, bar: BarData) -> None:
        symbol = normalize_bitpro_symbol(bar.symbol)
        ts = canonical_bar_timestamp_ms(int(bar.timestamp))
        stored_bar = bar
        if int(bar.timestamp) != ts:
            stored_bar = BarData(
                exchange=bar.exchange,
                symbol=bar.symbol,
                timeframe=bar.timeframe,
                timestamp=ts,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
        with self._lock:
            if symbol not in self._buffers:
                return
            buf = self._buffers[symbol]
            if ts in buf:
                del buf[ts]
            buf[ts] = stored_bar
            while len(buf) > self.history_bars + 16:
                buf.popitem(last=False)

    def build(self, timestamp_ms: int) -> Optional[SuperPnLFeatureBatch]:
        with self._lock:
            ts = canonical_bar_timestamp_ms(int(timestamp_ms))
            if not self.symbols:
                return None

            reference = self._window_timestamps(self.symbols[0], ts)
            if reference is None:
                return None
            for symbol in self.symbols[1:]:
                if not self._has_timestamps(symbol, reference):
                    return None

            frames = {
                symbol: self._frame_for(symbol, reference)
                for symbol in self.symbols
            }
        bar_blocks: Dict[str, pd.DataFrame] = {}
        feature_blocks: Dict[str, pd.DataFrame] = {}
        for symbol, frame in frames.items():
            bar_blocks[symbol] = self._bar_inputs(frame)
            feature_blocks[symbol] = self._symbol_features(frame)

        btc_symbol = "BTC/USDT" if "BTC/USDT" in feature_blocks else self.symbols[0]
        btc_features = feature_blocks[btc_symbol]
        market = pd.DataFrame(index=btc_features.index)
        for w in self.feature_windows:
            market[f"market_ret_{w}m"] = btc_features[f"ret_{w}m"]
            market[f"market_vol_{w}m"] = btc_features[f"vol_std_{w}m"]

        for w in self.feature_windows:
            ret_matrix = pd.DataFrame(
                {symbol: feature_blocks[symbol][f"ret_{w}m"] for symbol in self.symbols}
            )
            vol_matrix = pd.DataFrame(
                {symbol: feature_blocks[symbol][f"vol_std_{w}m"] for symbol in self.symbols}
            )
            ret_rank = ret_matrix.rank(axis=1, pct=True) - 0.5
            vol_rank = vol_matrix.rank(axis=1, pct=True) - 0.5
            for symbol in self.symbols:
                feature_blocks[symbol][f"cross_section_ret_rank_{w}m"] = ret_rank[symbol]
                feature_blocks[symbol][f"cross_section_vol_rank_{w}m"] = vol_rank[symbol]

        time_frame = self._time_features(np.array(reference, dtype="int64"))
        bar_arrays = []
        feature_arrays = []
        for symbol in self.symbols:
            features = feature_blocks[symbol].copy()
            for col in market.columns:
                features[col] = market[col].to_numpy()
            for col in time_frame.columns:
                features[col] = time_frame[col].to_numpy()

            bars = bar_blocks[symbol][self.bar_feature_names].tail(self.lookback)
            feats = features[self.feature_names].tail(self.lookback)
            if len(bars) != self.lookback or len(feats) != self.lookback:
                return None
            bar_arrays.append(bars.to_numpy(dtype="float32"))
            feature_arrays.append(feats.to_numpy(dtype="float32"))

        bar_np = np.nan_to_num(np.stack(bar_arrays, axis=0), nan=0.0, posinf=0.0, neginf=0.0)
        feat_np = np.nan_to_num(np.stack(feature_arrays, axis=0), nan=0.0, posinf=0.0, neginf=0.0)
        return SuperPnLFeatureBatch(
            timestamp_ms=ts,
            symbols=list(self.symbols),
            bar=bar_np.astype("float32", copy=False),
            features=feat_np.astype("float32", copy=False),
        )

    def latest_complete_timestamp(self, timestamp_ms: int) -> Optional[int]:
        """Return the latest timestamp <= input that has a complete universe window."""
        with self._lock:
            ts = canonical_bar_timestamp_ms(int(timestamp_ms))
            if not self.symbols:
                return None
            ref_buf = self._buffers.get(self.symbols[0])
            if not ref_buf:
                return None
            candidates = [item_ts for item_ts in list(ref_buf.keys()) if item_ts <= ts]
            for candidate_ts in reversed(candidates):
                reference = self._window_timestamps(self.symbols[0], candidate_ts)
                if reference is None:
                    continue
                if all(self._has_timestamps(symbol, reference) for symbol in self.symbols[1:]):
                    return candidate_ts
        return None

    def build_status(self, timestamp_ms: int) -> Dict[str, Any]:
        """Expose alignment status without fabricating missing bars."""
        with self._lock:
            ts = canonical_bar_timestamp_ms(int(timestamp_ms))
            symbols = list(self.symbols)
            expected = len(symbols)
            seen_symbols = [
                symbol
                for symbol in symbols
                if ts in (self._buffers.get(symbol) or {})
            ]
            seen = set(seen_symbols)
            current_missing = [symbol for symbol in symbols if symbol not in seen]
            latest_complete = self.latest_complete_timestamp(ts)
            reference_symbol = symbols[0] if symbols else None
            reference_window = (
                self._window_timestamps(reference_symbol, ts)
                if reference_symbol is not None
                else None
            )
            history_missing: List[str] = []
            if reference_window is not None:
                history_missing = [
                    symbol
                    for symbol in symbols
                    if not self._has_timestamps(symbol, reference_window)
                ]
            per_symbol_buffers = self._per_symbol_buffer_status(ts, reference_window)
        reason = "ready"
        if latest_complete is None:
            reason = "history_window_incomplete"
        elif latest_complete != ts:
            reason = "current_universe_incomplete"
        return {
            "timestamp_ms": ts,
            "expected_count": expected,
            "current_seen_count": len(seen_symbols),
            "current_missing_count": len(current_missing),
            "current_seen_symbols": seen_symbols,
            "current_missing_symbols": current_missing,
            "history_missing_symbols": history_missing,
            "latest_complete_timestamp_ms": latest_complete,
            "latest_complete_lag_bars": (
                int((ts - latest_complete) // 60_000)
                if latest_complete is not None
                else None
            ),
            "reference_symbol": reference_symbol,
            "required_history_bars": self.history_bars,
            "per_symbol_buffers": per_symbol_buffers,
            "reason": reason,
        }

    def _per_symbol_buffer_status(
        self,
        timestamp_ms: int,
        reference_window: Optional[List[int]],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for symbol in self.symbols:
            buf = self._buffers.get(symbol) or OrderedDict()
            timestamps = list(buf.keys())
            latest_ts = timestamps[-1] if timestamps else None
            oldest_ts = timestamps[0] if timestamps else None
            missing_reference_count = None
            if reference_window is not None:
                missing_reference_count = sum(1 for ts in reference_window if ts not in buf)
            out.append(
                {
                    "symbol": symbol,
                    "buffer_count": len(timestamps),
                    "oldest_timestamp_ms": oldest_ts,
                    "latest_timestamp_ms": latest_ts,
                    "latest_lag_bars": (
                        int((int(timestamp_ms) - latest_ts) // 60_000)
                        if latest_ts is not None
                        else None
                    ),
                    "has_current_bar": int(timestamp_ms) in buf,
                    "has_reference_window": (
                        None
                        if reference_window is None
                        else missing_reference_count == 0
                    ),
                    "missing_reference_count": missing_reference_count,
                }
            )
        return out

    def _window_timestamps(self, symbol: str, timestamp_ms: int) -> Optional[List[int]]:
        buf = self._buffers.get(symbol)
        if not buf or int(timestamp_ms) not in buf:
            return None
        timestamps = [ts for ts in list(buf.keys()) if ts <= int(timestamp_ms)]
        if len(timestamps) < self.history_bars:
            return None
        return timestamps[-self.history_bars :]

    def _has_timestamps(self, symbol: str, timestamps: List[int]) -> bool:
        buf = self._buffers.get(symbol)
        if not buf:
            return False
        return all(ts in buf for ts in timestamps)

    def _frame_for(self, symbol: str, timestamps: List[int]) -> pd.DataFrame:
        buf = self._buffers[symbol]
        rows = []
        for ts in timestamps:
            bar = buf[ts]
            volume = float(bar.volume or 0.0)
            close = float(bar.close or 0.0)
            rows.append(
                {
                    "timestamp": int(bar.timestamp),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": close,
                    "volume": volume,
                    "amount": close * volume,
                }
            )
        return pd.DataFrame(rows)

    def _symbol_features(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        log_close = np.log(close.replace(0, np.nan))
        log_ret_1m = log_close.diff()
        out = pd.DataFrame(index=df.index)
        for w in self.feature_windows:
            out[f"ret_{w}m"] = log_close - log_close.shift(w)
        for w in self.feature_windows:
            out[f"rsi_{w}m"] = self._rsi(close, w)
        for w in self.feature_windows:
            out[f"vol_std_{w}m"] = log_ret_1m.rolling(w, min_periods=w).std(ddof=0)
        for w in self.feature_windows:
            ma = close.rolling(w, min_periods=w).mean()
            out[f"ma_dev_{w}m"] = close / ma.replace(0, np.nan) - 1
        for w in self.feature_windows:
            ma = close.rolling(w, min_periods=w).mean()
            std = close.rolling(w, min_periods=w).std(ddof=0)
            out[f"boll_z_{w}m"] = (close - ma) / (2 * std.replace(0, np.nan))
        if 5 in self.feature_windows and 15 in self.feature_windows:
            out["macd_5m_15m"] = (
                close.ewm(span=5, adjust=False).mean() - close.ewm(span=15, adjust=False).mean()
            ) / close.replace(0, np.nan)
        if 15 in self.feature_windows and 30 in self.feature_windows:
            out["macd_15m_30m"] = (
                close.ewm(span=15, adjust=False).mean() - close.ewm(span=30, adjust=False).mean()
            ) / close.replace(0, np.nan)
        return out

    @staticmethod
    def _bar_inputs(df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        prev_close = close.shift(1).fillna(close)
        out = pd.DataFrame(index=df.index)
        out["open_rel"] = np.log(df["open"] / prev_close.replace(0, np.nan))
        out["high_rel"] = np.log(df["high"] / prev_close.replace(0, np.nan))
        out["low_rel"] = np.log(df["low"] / prev_close.replace(0, np.nan))
        out["close_rel"] = np.log(close / prev_close.replace(0, np.nan))
        out["volume_z_30m"] = SuperPnLFeatureBuilder._zscore(np.log1p(df["volume"]), 30)
        out["amount_z_30m"] = SuperPnLFeatureBuilder._zscore(np.log1p(df["amount"]), 30)
        return out

    @staticmethod
    def _rsi(close: pd.Series, window: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window, min_periods=window).mean()
        loss = (-delta.clip(upper=0)).rolling(window, min_periods=window).mean()
        denom = gain + loss
        rsi = gain / denom.replace(0, np.nan)
        return (rsi.fillna(0.5) - 0.5).astype("float32")

    @staticmethod
    def _zscore(series: pd.Series, window: int) -> pd.Series:
        mean = series.rolling(window, min_periods=window).mean()
        std = series.rolling(window, min_periods=window).std(ddof=0)
        return ((series - mean) / std.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    @staticmethod
    def _time_features(timestamps: np.ndarray) -> pd.DataFrame:
        dt_index = pd.to_datetime(timestamps, unit="ms", utc=True)
        hour = dt_index.hour + dt_index.minute / 60.0
        day = dt_index.dayofweek.to_numpy(dtype="float64")
        return pd.DataFrame(
            {
                "hour_sin": np.sin(2 * np.pi * hour / 24.0),
                "hour_cos": np.cos(2 * np.pi * hour / 24.0),
                "dayofweek_sin": np.sin(2 * np.pi * day / 7.0),
                "dayofweek_cos": np.cos(2 * np.pi * day / 7.0),
            }
        )
