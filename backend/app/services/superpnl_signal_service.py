"""
SuperPnL prediction signal provider.

This module is the only place that reads SuperPnL artifacts. Strategies must
depend on this service interface instead of reading files, databases, networks,
or exchange APIs directly.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SuperPnLSignal:
    symbol: str
    timestamp: int
    horizon: str
    pred_ret: float
    score_bps: float
    source: str


def normalize_superpnl_symbol(symbol: str) -> str:
    """Normalize BitPro/OKX style symbols to SuperPnL's hyphen style."""
    return str(symbol or "").strip().upper().replace("/", "-").replace(":USDT", "")


def normalize_bitpro_symbol(symbol: str) -> str:
    text = normalize_superpnl_symbol(symbol)
    if "-" in text:
        base, quote = text.split("-", 1)
        return f"{base}/{quote}"
    return text


class SuperPnLSignalService:
    """
    Local artifact backed signal service.

    Supported artifact layouts are intentionally permissive:
    - JSON list of rows: {"symbol", "timestamp_ms"|"timestamp"|"ts", "horizon", "pred_ret"}
    - JSON dict containing a "signals"/"rows"/"predictions" list
    - NPZ with arrays for symbol(s), timestamp(s), pred_ret(s), optional horizon(s)
    - NPY saved as a structured array, list/dict object, or plain ndarray with
      companion semantics if field names are present.

    If no artifact exists, or a row cannot be matched exactly by symbol,
    timestamp and horizon, get_signal() returns None. It never fabricates a
    signal.
    """

    DEFAULT_CANDIDATES = (
        "data/superpnl/full_feature_tcn_15m_predictions.npz",
        "data/superpnl/full_feature_tcn_15m_predictions.npy",
        "data/superpnl/full_feature_tcn_15m_predictions.json",
        "data/superpnl/full_feature_tcn_15m_signals.npz",
        "data/superpnl/full_feature_tcn_15m_signals.npy",
        "data/superpnl/full_feature_tcn_15m_signals.json",
        "data/superpnl/full_feature_tcn_test_predictions.npz",
    )

    def __init__(self, artifact_path: Optional[str] = None):
        self._artifact_path = artifact_path or os.environ.get("SUPERPNL_SIGNAL_PATH", "")
        self._loaded_path: Optional[Path] = None
        self._loaded = False
        self._signals: Dict[Tuple[str, int, str], SuperPnLSignal] = {}
        self._native_source = ""
        self._native_pred: Any = None
        self._native_symbols: Dict[str, int] = {}
        self._native_timestamps: Dict[int, int] = {}
        self._native_horizons: Dict[str, int] = {}

    async def get_signal(
        self,
        symbol: str,
        timestamp_ms: int,
        horizon: str = "15m",
    ) -> SuperPnLSignal | None:
        if not self._loaded:
            self._load_once()
        key = (normalize_superpnl_symbol(symbol), int(timestamp_ms), str(horizon))
        signal = self._signals.get(key)
        if signal is not None:
            return signal
        return self._get_native_signal(symbol, int(timestamp_ms), str(horizon))

    def _resolve_artifact_path(self) -> Optional[Path]:
        candidates = []
        if self._artifact_path:
            candidates.append(Path(self._artifact_path))
        candidates.extend(Path(p) for p in self.DEFAULT_CANDIDATES)

        root = Path(__file__).resolve().parents[3]
        for candidate in candidates:
            path = candidate if candidate.is_absolute() else root / candidate
            if path.exists() and path.is_file():
                return path
        return None

    def _load_once(self) -> None:
        self._loaded = True
        path = self._resolve_artifact_path()
        if path is None:
            logger.warning(
                "SuperPnL signal artifact not found. Set SUPERPNL_SIGNAL_PATH or place an artifact under data/superpnl/."
            )
            return

        try:
            suffix = path.suffix.lower()
            if suffix == ".json":
                rows = self._read_json(path)
            elif suffix == ".npz":
                rows = self._read_npz(path)
                if rows is None:
                    self._loaded_path = path
                    return
            elif suffix == ".npy":
                rows = self._read_npy(path)
            else:
                logger.warning("Unsupported SuperPnL signal artifact suffix: %s", path)
                return
            self._signals = self._rows_to_signals(rows, source=str(path))
            self._loaded_path = path
            logger.info("Loaded %d SuperPnL signals from %s", len(self._signals), path)
        except Exception:
            logger.exception("Failed to load SuperPnL signals from %s", path)
            self._signals = {}

    def _read_json(self, path: Path) -> Iterable[Dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("signals", "rows", "predictions", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            # Mapping of "SYMBOL|timestamp" -> pred_ret
            rows = []
            for key, value in data.items():
                if isinstance(value, dict):
                    rows.append(value)
                elif isinstance(value, (int, float)):
                    parts = str(key).replace(",", "|").split("|")
                    if len(parts) >= 2:
                        rows.append({"symbol": parts[0], "timestamp": parts[1], "pred_ret": value})
            return rows
        return []

    def _read_npz(self, path: Path) -> Iterable[Dict[str, Any]] | None:
        import numpy as np

        data = np.load(path, allow_pickle=True)
        keys = set(data.files)
        if "pred" in keys and not keys.intersection({"symbol", "symbols", "timestamp", "timestamps", "pred_ret"}):
            self._load_native_superpnl_npz(path, data)
            return None

        def pick(*names: str):
            for name in names:
                if name in keys:
                    return data[name]
            return None

        symbols = pick("symbol", "symbols", "pair", "pairs")
        timestamps = pick("timestamp_ms", "timestamps_ms", "timestamp", "timestamps", "ts")
        pred_rets = pick("pred_ret", "pred_rets", "prediction", "predictions", "y_pred")
        horizons = pick("horizon", "horizons")
        if symbols is None or timestamps is None or pred_rets is None:
            return []
        return self._array_rows(symbols, timestamps, pred_rets, horizons)

    def _load_native_superpnl_npz(self, path: Path, data: Any) -> None:
        """
        Load SuperPnL's native ``*_test_predictions.npz`` layout.

        Native files contain only dense arrays such as ``pred`` with shape
        [symbol, test_time, horizon]. Symbol names, test timestamps and horizon
        order live in the prepared cache metadata/timestamps. Missing companion
        metadata leaves the service empty rather than fabricating signals.
        """
        pred = data["pred"]
        if getattr(pred, "ndim", 0) != 3:
            logger.warning("SuperPnL native artifact pred must be 3D: %s", path)
            return

        companion = self._resolve_native_companion(path)
        if companion is None:
            logger.warning(
                "SuperPnL native artifact found but cache metadata/timestamps are missing. "
                "Set SUPERPNL_CACHE_DIR, SUPERPNL_METADATA_PATH and SUPERPNL_TIMESTAMPS_PATH."
            )
            return

        symbols, timestamps, horizons, test_range, source = companion
        start, end = test_range
        test_timestamps = timestamps[start:end]
        if pred.shape[0] != len(symbols) or pred.shape[1] != len(test_timestamps) or pred.shape[2] != len(horizons):
            logger.warning(
                "SuperPnL native artifact shape mismatch: pred=%s symbols=%d test_timestamps=%d horizons=%d",
                pred.shape,
                len(symbols),
                len(test_timestamps),
                len(horizons),
            )
            return

        self._native_pred = pred
        self._native_source = f"{path} | {source}"
        self._native_symbols = {normalize_superpnl_symbol(symbol): idx for idx, symbol in enumerate(symbols)}
        self._native_timestamps = {int(ts): idx for idx, ts in enumerate(test_timestamps)}
        self._native_horizons = {self._normalize_horizon(h): idx for idx, h in enumerate(horizons)}
        logger.info(
            "Loaded SuperPnL native artifact from %s: symbols=%d timestamps=%d horizons=%s",
            path,
            len(self._native_symbols),
            len(self._native_timestamps),
            sorted(self._native_horizons),
        )

    def _resolve_native_companion(self, artifact_path: Path) -> Optional[Tuple[list[str], Any, list[int], Tuple[int, int], str]]:
        metadata_path = self._resolve_optional_path("SUPERPNL_METADATA_PATH")
        timestamps_path = self._resolve_optional_path("SUPERPNL_TIMESTAMPS_PATH")
        cache_dir = self._resolve_optional_path("SUPERPNL_CACHE_DIR", want_dir=True)

        if cache_dir is None:
            cache_dir = self._cache_dir_from_run_config(artifact_path)
        if cache_dir is not None:
            metadata_path = metadata_path or cache_dir / "metadata.json"
            timestamps_path = timestamps_path or cache_dir / "timestamps.npy"

        if metadata_path is None or timestamps_path is None:
            return None
        if not metadata_path.exists() or not timestamps_path.exists():
            return None

        try:
            import numpy as np

            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            symbols = list(metadata.get("symbols") or [])
            horizons = [int(x) for x in metadata.get("horizons") or self._env_horizons()]
            test_range_raw = metadata.get("test_range")
            if not symbols or not horizons or not test_range_raw or len(test_range_raw) != 2:
                logger.warning("SuperPnL companion metadata missing symbols/horizons/test_range: %s", metadata_path)
                return None
            timestamps = np.load(timestamps_path, mmap_mode="r")
            test_range = (int(test_range_raw[0]), int(test_range_raw[1]))
            return symbols, timestamps, horizons, test_range, str(metadata_path)
        except Exception:
            logger.exception("Failed to load SuperPnL native companion metadata")
            return None

    def _cache_dir_from_run_config(self, artifact_path: Path) -> Optional[Path]:
        run_config_path = artifact_path.parent / "run_config.json"
        if not run_config_path.exists():
            return None
        try:
            data = json.loads(run_config_path.read_text(encoding="utf-8"))
            cache_dir = ((data.get("args") or {}).get("cache_dir") or "").strip()
            if not cache_dir:
                return None
            path = Path(cache_dir)
            if path.is_absolute():
                return path
            # SuperPnL run_config paths are usually repo-relative. If the
            # output directory is copied under BitPro data/superpnl, operators
            # should set SUPERPNL_CACHE_DIR explicitly.
            for parent in [artifact_path.parent, *artifact_path.parents]:
                candidate = parent / path
                if candidate.exists():
                    return candidate
            return path
        except Exception:
            logger.exception("Failed to parse SuperPnL run_config: %s", run_config_path)
            return None

    @staticmethod
    def _resolve_optional_path(env_name: str, *, want_dir: bool = False) -> Optional[Path]:
        value = os.environ.get(env_name, "").strip()
        if not value:
            return None
        path = Path(value)
        if want_dir:
            return path if path.exists() and path.is_dir() else path
        return path

    @staticmethod
    def _env_horizons() -> list[int]:
        raw = os.environ.get("SUPERPNL_HORIZONS", "5,15")
        out = []
        for part in raw.split(","):
            try:
                out.append(int(part.strip().removesuffix("m")))
            except ValueError:
                continue
        return out or [5, 15]

    @staticmethod
    def _normalize_horizon(value: Any) -> str:
        text = str(value).strip().lower()
        if text.endswith("m"):
            return text
        return f"{text}m"

    def _get_native_signal(self, symbol: str, timestamp_ms: int, horizon: str) -> SuperPnLSignal | None:
        if self._native_pred is None:
            return None
        sym_idx = self._native_symbols.get(normalize_superpnl_symbol(symbol))
        time_idx = self._native_timestamps.get(int(timestamp_ms))
        horizon_idx = self._native_horizons.get(self._normalize_horizon(horizon))
        if sym_idx is None or time_idx is None or horizon_idx is None:
            return None
        try:
            pred_ret = float(self._native_pred[sym_idx, time_idx, horizon_idx])
        except (TypeError, ValueError, IndexError):
            return None
        if pred_ret != pred_ret:
            return None
        return SuperPnLSignal(
            symbol=normalize_bitpro_symbol(symbol),
            timestamp=int(timestamp_ms),
            horizon=self._normalize_horizon(horizon),
            pred_ret=pred_ret,
            score_bps=pred_ret * 10_000.0,
            source=self._native_source,
        )

    def _read_npy(self, path: Path) -> Iterable[Dict[str, Any]]:
        import numpy as np

        obj = np.load(path, allow_pickle=True)
        if getattr(obj, "dtype", None) is not None and obj.dtype.names:
            return [{name: row[name].item() if hasattr(row[name], "item") else row[name] for name in obj.dtype.names} for row in obj]
        if obj.shape == ():
            item = obj.item()
            if isinstance(item, dict):
                if any(k in item for k in ("signals", "rows", "predictions", "data")):
                    for key in ("signals", "rows", "predictions", "data"):
                        if isinstance(item.get(key), list):
                            return item[key]
                if all(k in item for k in ("symbols", "timestamps", "pred_ret")):
                    return self._array_rows(item["symbols"], item["timestamps"], item["pred_ret"], item.get("horizons"))
            if isinstance(item, list):
                return item
        return []

    @staticmethod
    def _array_rows(symbols: Any, timestamps: Any, pred_rets: Any, horizons: Any = None) -> Iterable[Dict[str, Any]]:
        rows = []
        n = min(len(symbols), len(timestamps), len(pred_rets))
        for i in range(n):
            row = {
                "symbol": symbols[i].item() if hasattr(symbols[i], "item") else symbols[i],
                "timestamp": timestamps[i].item() if hasattr(timestamps[i], "item") else timestamps[i],
                "pred_ret": pred_rets[i].item() if hasattr(pred_rets[i], "item") else pred_rets[i],
            }
            if horizons is not None and len(horizons) > i:
                row["horizon"] = horizons[i].item() if hasattr(horizons[i], "item") else horizons[i]
            rows.append(row)
        return rows

    @staticmethod
    def _rows_to_signals(rows: Iterable[Dict[str, Any]], *, source: str) -> Dict[Tuple[str, int, str], SuperPnLSignal]:
        out: Dict[Tuple[str, int, str], SuperPnLSignal] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = normalize_superpnl_symbol(str(row.get("symbol") or row.get("pair") or ""))
            if not symbol:
                continue
            ts_raw = (
                row.get("timestamp_ms")
                or row.get("bar_ts_ms")
                or row.get("timestamp")
                or row.get("ts")
                or row.get("time")
            )
            pred_raw = row.get("pred_ret")
            if pred_raw is None:
                pred_raw = row.get("prediction", row.get("y_pred", row.get("score")))
            try:
                timestamp = int(float(ts_raw))
                pred_ret = float(pred_raw)
            except (TypeError, ValueError):
                continue
            if timestamp < 10_000_000_000:
                timestamp *= 1000
            horizon = str(row.get("horizon") or row.get("signal_horizon") or "15m")
            signal = SuperPnLSignal(
                symbol=normalize_bitpro_symbol(symbol),
                timestamp=timestamp,
                horizon=horizon,
                pred_ret=pred_ret,
                score_bps=pred_ret * 10_000.0,
                source=source,
            )
            out[(symbol, timestamp, horizon)] = signal
        return out


superpnl_signal_service = SuperPnLSignalService()
