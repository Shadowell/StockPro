"""
File-system based K-line store.

Motivation:
- SQLite will lock heavily with millions of OHLCV rows.
- For solo quant "sleep-after" stability, keep the DB for light state only and
  move large time-series data to append-friendly files.

Storage layout (preferred Parquet, fallback CSV):
data/klines/{exchange}/{symbol}/{timeframe}/YYYYMM.(parquet|csv)

Where symbol is sanitized for filesystem safety.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import logging

import pandas as pd

logger = logging.getLogger(__name__)

TIMEFRAME_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}

KLINE_SCALE_RATIO_THRESHOLD = 3.0
KLINE_DISCONTINUITY_MIN_COUNT = 5
KLINE_DISCONTINUITY_MIN_DIRECTION_FLIPS = 3


def _sanitize_symbol(symbol: str) -> str:
    # BTC/USDT -> BTC-USDT, BTC/USDT:USDT -> BTC-USDT_USDT
    return symbol.replace("/", "-").replace(":", "_")


@dataclass(frozen=True)
class KlineStoreConfig:
    root_dir: Path
    fmt: str = "parquet"  # "parquet" | "csv"


class KlineDataQualityError(ValueError):
    def __init__(self, message: str, *, quarantine_path: Optional[Path] = None):
        super().__init__(message)
        self.quarantine_path = quarantine_path


def _format_ts(ts_ms: int) -> str:
    try:
        return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts_ms)


def find_kline_quality_issues(
    df: pd.DataFrame,
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    detect_missing_intervals: bool = False,
) -> List[Dict]:
    required = ["timestamp", "open", "high", "low", "close"]
    if df.empty or any(col not in df.columns for col in required):
        return []

    work = df[required].copy()
    for col in required:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.replace([float("inf"), float("-inf")], pd.NA)
    invalid_numeric = work[required].isna().any(axis=1)
    valid_work = work[~invalid_numeric].copy()
    if valid_work.empty and not invalid_numeric.any():
        return []

    prices = valid_work[["open", "high", "low", "close"]]
    invalid_price = (prices <= 0).any(axis=1)
    invalid_ohlc = (
        (valid_work["high"] < valid_work[["open", "close", "low"]].max(axis=1)) |
        (valid_work["low"] > valid_work[["open", "close", "high"]].min(axis=1))
    )
    invalid_rows = pd.concat([work[invalid_numeric], valid_work[invalid_price | invalid_ohlc]])
    issues: List[Dict] = []
    if not invalid_rows.empty:
        invalid_rows = invalid_rows.sort_values("timestamp")
        first = invalid_rows.iloc[0]
        last = invalid_rows.iloc[-1]
        first_ts = int(first["timestamp"]) if pd.notna(first.get("timestamp")) else 0
        last_ts = int(last["timestamp"]) if pd.notna(last.get("timestamp")) else first_ts
        issues.append({
            "type": "invalid_ohlc",
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": timeframe,
            "count": int(len(invalid_rows)),
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
            "message": (
                f"真实 K 线字段异常: {exchange} {symbol} {timeframe} "
                f"{_format_ts(first_ts)} 的 OHLC 价格不合法。"
            ),
        })

    work = valid_work.dropna(subset=required)
    if work.empty:
        return issues

    work["timestamp"] = work["timestamp"].astype("int64")
    work = work.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

    interval_ms = TIMEFRAME_MS.get(str(timeframe).lower(), 3_600_000)
    work["prev_close"] = work["close"].shift(1)
    work["delta_ms"] = work["timestamp"].diff()
    if detect_missing_intervals:
        long_gap_threshold_ms = max(interval_ms * 2, 7 * 24 * 60 * 60 * 1000)
        long_gaps = work[work["delta_ms"].gt(long_gap_threshold_ms)]
        if not long_gaps.empty:
            missing_count = int(sum(
                max(0, round(float(delta_ms) / interval_ms) - 1)
                for delta_ms in long_gaps["delta_ms"].tolist()
            ))
            first_idx = long_gaps.index[0]
            first_position = work.index.get_loc(first_idx)
            before_ts = int(work.iloc[first_position - 1]["timestamp"])
            after_ts = int(work.loc[first_idx]["timestamp"])
            issues.append({
                "type": "missing_interval",
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": timeframe,
                "count": missing_count,
                "first_timestamp": before_ts,
                "last_timestamp": after_ts,
                "message": (
                    f"真实 K 线时间戳断档: {exchange} {symbol} {timeframe} "
                    f"在 {_format_ts(before_ts)} 至 {_format_ts(after_ts)} 之间约缺 {missing_count} 根。"
                ),
            })
    consecutive = (
        work["prev_close"].gt(0) &
        work["delta_ms"].ge(interval_ms * 0.5) &
        work["delta_ms"].le(interval_ms * 1.5)
    )
    open_gap_pct = (work["open"] - work["prev_close"]) / work["prev_close"]
    scale_ratio = work[["open", "prev_close"]].max(axis=1) / work[["open", "prev_close"]].min(axis=1)
    discontinuity_mask = (
        consecutive &
        scale_ratio.ge(KLINE_SCALE_RATIO_THRESHOLD)
    )
    discontinuities = work[discontinuity_mask].copy()
    if not discontinuities.empty:
        signs = open_gap_pct[discontinuity_mask].dropna().map(lambda value: 1 if value > 0 else -1).tolist()
        direction_flips = sum(1 for prev, cur in zip(signs, signs[1:]) if prev != cur)
        if (
            len(discontinuities) >= KLINE_DISCONTINUITY_MIN_COUNT and
            direction_flips >= KLINE_DISCONTINUITY_MIN_DIRECTION_FLIPS
        ):
            examples = []
            for idx in discontinuities.index[:3]:
                ts = int(work.loc[idx, "timestamp"])
                jump_pct = float(open_gap_pct.loc[idx] * 100)
                examples.append(f"{_format_ts(ts)} {jump_pct:+.2f}%")
            issues.append({
                "type": "repeated_discontinuity",
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": timeframe,
                "count": int(len(discontinuities)),
                "direction_flips": int(direction_flips),
                "first_timestamp": int(discontinuities.iloc[0]["timestamp"]),
                "last_timestamp": int(discontinuities.iloc[-1]["timestamp"]),
                "message": (
                    f"真实 K 线连续性异常: {exchange} {symbol} {timeframe} "
                    f"出现 {len(discontinuities)} 个相邻 bar 开盘价相对上一根收盘价发生至少 "
                    f"{KLINE_SCALE_RATIO_THRESHOLD:.0f} 倍价格尺度切换且方向反复，"
                    f"示例: {', '.join(examples)}。"
                ),
            })
    return issues


def kline_quality_error_message(issues: List[Dict]) -> str:
    if not issues:
        return ""
    return "；".join(str(issue.get("message") or issue.get("type")) for issue in issues[:3])


class KlineFileStore:
    def __init__(self, config: Optional[KlineStoreConfig] = None):
        project_root = Path(__file__).resolve().parents[3]
        default_root = project_root / "data" / "klines"
        self.config = config or KlineStoreConfig(root_dir=default_root, fmt=os.getenv("KLINE_STORE_FMT", "parquet"))

    def _dir(self, exchange: str, symbol: str, timeframe: str) -> Path:
        return self.config.root_dir / exchange / _sanitize_symbol(symbol) / timeframe

    def _partition_key(self, ts_ms: int) -> str:
        dt = datetime.fromtimestamp(ts_ms / 1000)
        return f"{dt.year}{dt.month:02d}"

    def _filter_partition_files_by_range(
        self,
        files: List[Path],
        *,
        start_ms: Optional[int],
        end_ms: Optional[int],
    ) -> List[Path]:
        if start_ms is None and end_ms is None:
            return files

        start_part = self._partition_key(int(start_ms)) if start_ms is not None else None
        end_part = self._partition_key(int(end_ms)) if end_ms is not None else None
        return [
            fp
            for fp in files
            if (start_part is None or fp.stem >= start_part)
            and (end_part is None or fp.stem <= end_part)
        ]

    def _file_path(self, exchange: str, symbol: str, timeframe: str, part: str) -> Path:
        ext = "parquet" if self.config.fmt == "parquet" else "csv"
        return self._dir(exchange, symbol, timeframe) / f"{part}.{ext}"

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def append_klines(self, exchange: str, symbol: str, timeframe: str, klines: List[Dict]) -> int:
        if not klines:
            return 0

        df = pd.DataFrame(klines)
        required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing kline columns: {missing}")

        # Ensure types before a row can enter a normal readable partition.
        df["timestamp"] = df["timestamp"].astype("int64")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

        self._ensure_dir(self._dir(exchange, symbol, timeframe))
        self._raise_for_quality_issues(exchange, symbol, timeframe, df, quarantine_source=df)

        inserted_total = 0
        for part, part_df in df.groupby(df["timestamp"].map(self._partition_key)):
            file_path = self._file_path(exchange, symbol, timeframe, str(part))
            inserted_total += self._append_partition(file_path, part_df, exchange, symbol, timeframe)

        return inserted_total

    def _append_partition(self, file_path: Path, df: pd.DataFrame, exchange: str, symbol: str, timeframe: str) -> int:
        if df.empty:
            return 0

        if self.config.fmt == "parquet":
            return self._append_parquet(file_path, df, exchange, symbol, timeframe)
        return self._append_csv(file_path, df, exchange, symbol, timeframe)

    def _append_parquet(self, file_path: Path, df: pd.DataFrame, exchange: str, symbol: str, timeframe: str) -> int:
        try:
            import pyarrow  # noqa: F401
        except Exception as exc:
            logger.warning(f"pyarrow unavailable, falling back to csv: {exc}")
            self.config = KlineStoreConfig(root_dir=self.config.root_dir, fmt="csv")
            csv_path = file_path.with_suffix(".csv")
            return self._append_csv(csv_path, df, exchange, symbol, timeframe)

        if file_path.exists():
            try:
                old = pd.read_parquet(file_path)
            except Exception as exc:
                corrupt_path = self._quarantine_file(file_path, "corrupt")
                logger.error(
                    "Corrupt parquet partition quarantined: %s -> %s: %s",
                    file_path,
                    corrupt_path,
                    exc,
                )
                old = pd.DataFrame()
            merged = pd.concat([old, df], ignore_index=True)
            merged = merged.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
            issues = find_kline_quality_issues(merged, exchange=exchange, symbol=symbol, timeframe=timeframe)
            if issues:
                quarantine_path = self._quarantine_file(file_path, "quality")
                logger.error(
                    "K-line partition quarantined after quality check: %s -> %s: %s",
                    file_path,
                    quarantine_path,
                    kline_quality_error_message(issues),
                )
                self._write_parquet_atomic(file_path, df)
                return len(df)
            before = len(old)
            self._write_parquet_atomic(file_path, merged)
            return max(0, len(merged) - before)

        self._write_parquet_atomic(file_path, df)
        return len(df)

    def _write_parquet_atomic(self, file_path: Path, df: pd.DataFrame) -> None:
        self._ensure_dir(file_path.parent)
        tmp_path = file_path.with_name(f".{file_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            df.to_parquet(tmp_path, index=False)
            tmp_path.replace(file_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _quarantine_file(self, file_path: Path, reason: str) -> Path:
        suffix = f"{reason}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        quarantine_dir = file_path.parent / "_quarantine"
        self._ensure_dir(quarantine_dir)
        quarantine_path = quarantine_dir / f"{file_path.name}.{suffix}"
        file_path.replace(quarantine_path)
        return quarantine_path

    def _append_csv(self, file_path: Path, df: pd.DataFrame, exchange: str, symbol: str, timeframe: str) -> int:
        if file_path.exists():
            old = pd.read_csv(file_path)
            merged = pd.concat([old, df], ignore_index=True)
            merged = merged.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
            issues = find_kline_quality_issues(merged, exchange=exchange, symbol=symbol, timeframe=timeframe)
            if issues:
                quarantine_path = self._quarantine_file(file_path, "quality")
                logger.error(
                    "K-line partition quarantined after quality check: %s -> %s: %s",
                    file_path,
                    quarantine_path,
                    kline_quality_error_message(issues),
                )
                df.to_csv(file_path, index=False)
                return len(df)
            before = len(old)
            merged.to_csv(file_path, index=False)
            return max(0, len(merged) - before)

        df.to_csv(file_path, index=False)
        return len(df)

    def _raise_for_quality_issues(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        *,
        quarantine_source: pd.DataFrame,
    ) -> None:
        issues = find_kline_quality_issues(df, exchange=exchange, symbol=symbol, timeframe=timeframe)
        if not issues:
            return
        message = kline_quality_error_message(issues)
        quarantine_path = self._quarantine_rejected_batch(exchange, symbol, timeframe, quarantine_source, issues)
        raise KlineDataQualityError(message, quarantine_path=quarantine_path)

    def _quarantine_rejected_batch(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        issues: List[Dict],
    ) -> Path:
        base = self._dir(exchange, symbol, timeframe) / "_quarantine"
        self._ensure_dir(base)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = base / f"rejected-{ts}-{uuid.uuid4().hex[:8]}.json"
        payload = {
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": timeframe,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "issues": issues,
            "rows": df.to_dict(orient="records"),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
        logger.error("Rejected K-line batch quarantined: %s: %s", path, kline_quality_error_message(issues))
        return path

    def read_klines(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        *,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        if start_ms is None and end_ms is None and limit is not None:
            df = self._read_recent_dataframe(exchange, symbol, timeframe, int(limit))
            if df.empty:
                return []
            return df.to_dict(orient="records")

        df = self.read_dataframe(exchange, symbol, timeframe, start_ms=start_ms, end_ms=end_ms)
        if df.empty:
            return []

        if limit is not None:
            df = df.tail(int(limit))

        return df.to_dict(orient="records")

    def _read_file(self, fp: Path) -> pd.DataFrame:
        if fp.suffix == ".parquet":
            return pd.read_parquet(fp)
        return pd.read_csv(fp)

    def _normalize_dataframe(self, frames: List[pd.DataFrame]) -> pd.DataFrame:
        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        if "timestamp" not in df.columns:
            return pd.DataFrame()

        df["timestamp"] = df["timestamp"].astype("int64")
        return df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

    def _read_recent_dataframe(self, exchange: str, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        base = self._dir(exchange, symbol, timeframe)
        if not base.exists():
            return pd.DataFrame()

        files = sorted(
            [*base.glob("*.parquet"), *base.glob("*.csv")],
            key=lambda fp: fp.stem,
            reverse=True,
        )
        if not files:
            return pd.DataFrame()

        frames: List[pd.DataFrame] = []
        for fp in files:
            try:
                frames.append(self._read_file(fp))
            except Exception as exc:
                logger.warning(f"Failed to read {fp}: {exc}")
                continue

            df = self._normalize_dataframe(frames)
            if len(df) >= limit:
                return df.tail(limit)

        df = self._normalize_dataframe(frames)
        if df.empty:
            return df
        return df.tail(limit)

    def read_dataframe(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        *,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> pd.DataFrame:
        base = self._dir(exchange, symbol, timeframe)
        if not base.exists():
            return pd.DataFrame()

        files = sorted(base.glob("*.parquet")) + sorted(base.glob("*.csv"))
        files = self._filter_partition_files_by_range(files, start_ms=start_ms, end_ms=end_ms)
        if not files:
            return pd.DataFrame()

        frames: List[pd.DataFrame] = []
        for fp in files:
            try:
                frames.append(self._read_file(fp))
            except Exception as exc:
                logger.warning(f"Failed to read {fp}: {exc}")

        df = self._normalize_dataframe(frames)
        if df.empty:
            return df

        if start_ms is not None:
            df = df[df["timestamp"] >= int(start_ms)]
        if end_ms is not None:
            df = df[df["timestamp"] <= int(end_ms)]

        return df

    def get_stats(self, exchange: str, symbol: str, timeframe: str) -> Dict:
        df = self.read_dataframe(exchange, symbol, timeframe)
        if df.empty:
            return {"record_count": 0, "first_timestamp": None, "last_timestamp": None}
        return {
            "record_count": int(len(df)),
            "first_timestamp": int(df["timestamp"].min()),
            "last_timestamp": int(df["timestamp"].max()),
        }

    def delete(self, exchange: str, symbol: str, timeframe: Optional[str] = None) -> int:
        """
        Delete stored files. Returns number of deleted files.
        """
        deleted = 0
        base = self.config.root_dir / exchange / _sanitize_symbol(symbol)
        if timeframe:
            base = base / timeframe
        if not base.exists():
            return 0

        for fp in base.rglob("*.parquet"):
            fp.unlink(missing_ok=True)
            deleted += 1
        for fp in base.rglob("*.csv"):
            fp.unlink(missing_ok=True)
            deleted += 1

        return deleted


kline_store = KlineFileStore()
