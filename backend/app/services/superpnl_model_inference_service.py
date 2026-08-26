"""
Realtime SuperPnL model inference service.

This service owns Hugging Face model resolution, PyTorch model loading, rolling
feature construction and timestamp-level signal caching. Strategies must use
this service instead of reading model files or historical predictions directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from app.core.execution.base_strategy import BarData
from app.services.superpnl_feature_builder import (
    SuperPnLFeatureBuilder,
    canonical_bar_timestamp_ms,
    normalize_bitpro_symbol,
    normalize_superpnl_symbol,
)

logger = logging.getLogger(__name__)

SUPERPNL_INFERENCE_ENABLED = False
SUPERPNL_INFERENCE_DISABLED_MESSAGE = "SuperPnL inference is disabled"

REQUIRED_SUPERPNL_FILES = [
    "model.pt",
    "model_config.json",
    "feature_schema.json",
    "normalization_stats.npz",
    "universe.json",
    "data_contract.json",
    "metrics_summary.json",
    "manifest.json",
]


@dataclass(frozen=True)
class SuperPnLSignal:
    symbol: str
    timestamp_ms: int
    horizon: str
    pred_ret: float
    score_bps: float
    pos_score: float
    source: str


class CausalConv1d(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, kernel_size: int, dilation: int) -> None:
        super().__init__()
        self.left_padding = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(in_channels, out_channels, kernel_size=kernel_size, dilation=dilation)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv(F.pad(x, (self.left_padding, 0)))


class TCNBlock(nn.Module):
    def __init__(self, channels: int, kernel_size: int, dilation: int, dropout: float) -> None:
        super().__init__()
        self.net = nn.Sequential(
            CausalConv1d(channels, channels, kernel_size, dilation),
            nn.GELU(),
            nn.Dropout(dropout),
            CausalConv1d(channels, channels, kernel_size, dilation),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.norm = nn.GroupNorm(1, channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.norm(x + self.net(x))


class TCNEncoder(nn.Module):
    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        dilations: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64),
        kernel_size: int = 3,
        dropout: float = 0.05,
    ) -> None:
        super().__init__()
        self.proj = nn.Conv1d(input_dim, hidden_dim, kernel_size=1)
        self.blocks = nn.ModuleList(
            [TCNBlock(hidden_dim, kernel_size, dilation, dropout) for dilation in dilations]
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.proj(x.transpose(1, 2))
        for block in self.blocks:
            x = block(x)
        return x.transpose(1, 2)


class SuperPnLModel(nn.Module):
    def __init__(
        self,
        bar_dim: int,
        feature_dim: int,
        num_horizons: int,
        hidden_dim: int = 64,
        dropout: float = 0.05,
        use_features: bool = True,
    ) -> None:
        super().__init__()
        self.use_features = use_features and feature_dim > 0
        self.bar_encoder = TCNEncoder(bar_dim, hidden_dim, dropout=dropout)
        if self.use_features:
            self.feature_encoder = TCNEncoder(
                feature_dim,
                hidden_dim,
                dilations=(1, 2, 4, 8, 16, 32),
                dropout=dropout,
            )
            self.film = nn.Sequential(nn.LayerNorm(hidden_dim), nn.Linear(hidden_dim, hidden_dim * 3))
        else:
            self.feature_encoder = None
            self.film = None
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, num_horizons * 2),
        )
        self.num_horizons = num_horizons

    def forward(self, bar: torch.Tensor, features: torch.Tensor | None = None) -> tuple[torch.Tensor, torch.Tensor]:
        bar_hidden = self.bar_encoder(bar)[:, -1, :]
        fused = bar_hidden
        if self.use_features:
            if features is None:
                raise ValueError("features required when use_features=True")
            feature_hidden = self.feature_encoder(features)[:, -1, :]
            gamma, beta, gate = self.film(feature_hidden).chunk(3, dim=-1)
            mod = bar_hidden * (1.0 + torch.tanh(gamma)) + beta
            fused = bar_hidden + torch.sigmoid(gate) * mod
        out = self.head(fused).view(-1, self.num_horizons, 2)
        return out[:, :, 0], out[:, :, 1]


def resolve_superpnl_model_dir(
    repo_id: str,
    revision: str,
    cache_dir: str | None,
    allow_download: bool,
) -> Path:
    local_dir = Path(cache_dir).expanduser() if cache_dir else None
    if local_dir and all((local_dir / name).exists() for name in REQUIRED_SUPERPNL_FILES):
        return local_dir
    if not allow_download:
        raise FileNotFoundError(f"SuperPnL model files missing under {local_dir}")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required to download SuperPnL model package") from exc
    downloaded = snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=str(local_dir) if local_dir else None,
        ignore_patterns=["*.tar.gz"],
    )
    model_dir = Path(downloaded)
    missing = [name for name in REQUIRED_SUPERPNL_FILES if not (model_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"SuperPnL model repo missing files: {missing}")
    return model_dir


class SuperPnLModelInferenceService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._initialized = False
        self._ready = False
        self._error: Optional[str] = None
        self._model_dir: Optional[Path] = None
        self._model_repo_id = "Shadowell/SuperPnL"
        self._model_revision = "main"
        self._model: Optional[SuperPnLModel] = None
        self._builder: Optional[SuperPnLFeatureBuilder] = None
        self._bar_mean: Optional[np.ndarray] = None
        self._bar_std: Optional[np.ndarray] = None
        self._feature_mean: Optional[np.ndarray] = None
        self._feature_std: Optional[np.ndarray] = None
        self._horizon_index: Dict[str, int] = {}
        self._signals: Dict[tuple[int, str, str], SuperPnLSignal] = {}
        self._predicted_timestamps: set[int] = set()
        self._history_backfill_lock = asyncio.Lock()
        self._history_backfill_last_attempt: Dict[tuple[str, str], float] = {}

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def last_error(self) -> Optional[str]:
        return self._error

    @property
    def model_dir(self) -> Optional[str]:
        return str(self._model_dir) if self._model_dir else None

    @property
    def model_repo_id(self) -> str:
        return self._model_repo_id

    @property
    def model_revision(self) -> str:
        return self._model_revision

    @property
    def universe_symbols(self) -> list[str]:
        if self._builder is None:
            return []
        return list(self._builder.symbols)

    def latest_complete_timestamp(self, timestamp_ms: int) -> Optional[int]:
        if self._builder is None:
            return None
        return self._builder.latest_complete_timestamp(timestamp_ms)

    def get_build_status(self, timestamp_ms: int) -> Dict[str, Any]:
        if self._builder is None:
            ts = canonical_bar_timestamp_ms(int(timestamp_ms))
            return {
                "timestamp_ms": ts,
                "expected_count": 0,
                "current_seen_count": 0,
                "current_missing_count": 0,
                "current_seen_symbols": [],
                "current_missing_symbols": [],
                "history_missing_symbols": [],
                "latest_complete_timestamp_ms": None,
                "latest_complete_lag_bars": None,
                "reference_symbol": None,
                "required_history_bars": None,
                "per_symbol_buffers": [],
                "reason": "builder_unavailable",
            }
        return self._builder.build_status(timestamp_ms)

    async def backfill_history_from_exchange(
        self,
        *,
        exchange_name: str,
        timeframe: str = "1m",
        limit: Optional[int] = None,
        cooldown_sec: float = 300.0,
        min_interval_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Hydrate the builder with real closed OHLCV bars from the configured exchange."""
        if self._builder is None:
            return {"attempted": False, "reason": "builder_unavailable"}
        if not self._ready:
            return {"attempted": False, "reason": "model_not_ready", "error": self._error}

        normalized_exchange = str(exchange_name or "okx").strip().lower() or "okx"
        normalized_timeframe = str(timeframe or "1m").strip() or "1m"
        key = (normalized_exchange, normalized_timeframe)
        required = int(self._builder.history_bars)
        fetch_limit = max(required + 1, int(limit or 0))
        throttle = (
            float(min_interval_sec)
            if min_interval_sec is not None
            else float(os.environ.get("BITPRO_OHLCV_MIN_INTERVAL_SEC", "0.20"))
        )

        async with self._history_backfill_lock:
            now = time.monotonic()
            last_attempt = self._history_backfill_last_attempt.get(key)
            if last_attempt is not None and now - last_attempt < max(float(cooldown_sec), 0.0):
                return {
                    "attempted": False,
                    "reason": "cooldown",
                    "cooldown_remaining_sec": round(max(float(cooldown_sec) - (now - last_attempt), 0.0), 3),
                    "required_history_bars": required,
                }
            self._history_backfill_last_attempt[key] = now

            from app.exchange import exchange_manager

            exchange = exchange_manager.get_exchange(normalized_exchange)
            if exchange is None:
                return {
                    "attempted": True,
                    "reason": "exchange_unavailable",
                    "exchange": normalized_exchange,
                    "required_history_bars": required,
                }

            per_symbol: list[Dict[str, Any]] = []
            total_loaded = 0
            for symbol in list(self._builder.symbols):
                try:
                    rows = await asyncio.to_thread(
                        exchange.fetch_ohlcv,
                        symbol,
                        normalized_timeframe,
                        fetch_limit,
                    )
                except Exception as exc:
                    self._error = str(exc)
                    logger.warning(
                        "SuperPnL real OHLCV backfill failed: exchange=%s symbol=%s timeframe=%s error=%s",
                        normalized_exchange,
                        symbol,
                        normalized_timeframe,
                        exc,
                    )
                    per_symbol.append(
                        {
                            "symbol": symbol,
                            "loaded_count": 0,
                            "error": str(exc),
                        }
                    )
                    continue

                closed_rows = list(rows or [])
                if len(closed_rows) > required:
                    closed_rows = closed_rows[:-1]
                closed_rows = closed_rows[-required:]
                loaded = 0
                latest_ts = None
                for row in closed_rows:
                    backfill_bar = self._bar_from_ohlcv_row(
                        row,
                        exchange=normalized_exchange,
                        symbol=symbol,
                        timeframe=normalized_timeframe,
                    )
                    if backfill_bar is None:
                        continue
                    self._builder.update_bar(backfill_bar)
                    loaded += 1
                    latest_ts = canonical_bar_timestamp_ms(int(backfill_bar.timestamp))
                total_loaded += loaded
                per_symbol.append(
                    {
                        "symbol": symbol,
                        "loaded_count": loaded,
                        "latest_timestamp_ms": latest_ts,
                    }
                )
                if throttle > 0:
                    await asyncio.sleep(throttle)

            return {
                "attempted": True,
                "reason": "completed",
                "exchange": normalized_exchange,
                "timeframe": normalized_timeframe,
                "required_history_bars": required,
                "fetch_limit": fetch_limit,
                "total_loaded_count": total_loaded,
                "per_symbol": per_symbol,
            }

    async def initialize(
        self,
        model_repo_id: str = "Shadowell/SuperPnL",
        model_revision: str = "main",
        model_cache_dir: str | None = None,
        allow_model_download: bool = True,
    ) -> None:
        if not SUPERPNL_INFERENCE_ENABLED:
            self._initialized = True
            self._ready = False
            self._error = SUPERPNL_INFERENCE_DISABLED_MESSAGE
            logger.info(SUPERPNL_INFERENCE_DISABLED_MESSAGE)
            return
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            self._initialized = True
            self._model_repo_id = model_repo_id or os.environ.get("SUPERPNL_MODEL_REPO_ID", "Shadowell/SuperPnL")
            self._model_revision = model_revision or os.environ.get("SUPERPNL_MODEL_REVISION", "main")
            cache_dir = self._resolve_cache_dir(model_cache_dir)
            try:
                await asyncio.to_thread(
                    self._load_model_package,
                    self._model_repo_id,
                    self._model_revision,
                    cache_dir,
                    allow_model_download,
                )
                self._ready = True
                self._error = None
                logger.info("SuperPnL model inference ready: %s", self._model_dir)
            except Exception as exc:
                self._ready = False
                self._error = str(exc)
                logger.exception("SuperPnL model inference initialization failed")

    async def update_bar(self, bar: BarData) -> None:
        if not SUPERPNL_INFERENCE_ENABLED:
            return
        if self._builder is not None:
            self._builder.update_bar(bar)

    async def predict_timestamp(self, timestamp_ms: int, horizon: str = "15m") -> Dict[str, SuperPnLSignal]:
        if not SUPERPNL_INFERENCE_ENABLED:
            self._error = SUPERPNL_INFERENCE_DISABLED_MESSAGE
            return {}
        if not self._ready or self._builder is None or self._model is None:
            return {}
        ts = canonical_bar_timestamp_ms(int(timestamp_ms))
        horizon_key = self._normalize_horizon(horizon)
        if ts in self._predicted_timestamps:
            return {
                symbol: signal
                for (sig_ts, sig_horizon, symbol), signal in self._signals.items()
                if sig_ts == ts and sig_horizon == horizon_key
            }
        batch = self._builder.build(ts)
        if batch is None:
            return {}

        try:
            bar_np = self._standardize(batch.bar, self._bar_mean, self._bar_std)
            feature_np = self._standardize(batch.features, self._feature_mean, self._feature_std)
            idx = self._horizon_index.get(horizon_key)
            if idx is None:
                return {}
            with torch.inference_mode():
                bar_tensor = torch.from_numpy(bar_np).float()
                feature_tensor = torch.from_numpy(feature_np).float()
                pred_ret, pos_logit = self._model(bar_tensor, feature_tensor)
                pred = pred_ret[:, idx].detach().cpu().numpy()
                pos = torch.sigmoid(pos_logit[:, idx]).detach().cpu().numpy()
            out: Dict[str, SuperPnLSignal] = {}
            for i, symbol in enumerate(batch.symbols):
                signal = SuperPnLSignal(
                    symbol=symbol,
                    timestamp_ms=ts,
                    horizon=horizon_key,
                    pred_ret=float(pred[i]),
                    score_bps=float(pred[i]) * 10_000.0,
                    pos_score=float(pos[i]),
                    source=f"hf:{self._model_repo_id}@{self._model_revision}",
                )
                self._signals[(ts, horizon_key, normalize_superpnl_symbol(symbol))] = signal
                out[symbol] = signal
            self._predicted_timestamps.add(ts)
            return out
        except Exception as exc:
            self._error = str(exc)
            logger.exception("SuperPnL prediction failed for timestamp=%s", ts)
            return {}

    async def get_signal(self, symbol: str, timestamp_ms: int, horizon: str = "15m") -> SuperPnLSignal | None:
        horizon_key = self._normalize_horizon(horizon)
        ts = canonical_bar_timestamp_ms(int(timestamp_ms))
        key = (ts, horizon_key, normalize_superpnl_symbol(symbol))
        signal = self._signals.get(key)
        if signal is not None:
            return signal
        signals = await self.predict_timestamp(ts, horizon_key)
        return signals.get(normalize_bitpro_symbol(symbol))

    def _load_model_package(
        self,
        repo_id: str,
        revision: str,
        cache_dir: str | None,
        allow_download: bool,
    ) -> None:
        model_dir = resolve_superpnl_model_dir(repo_id, revision, cache_dir, allow_download)
        model_config = self._read_json(model_dir / "model_config.json")
        feature_schema = self._read_json(model_dir / "feature_schema.json")
        universe = self._read_json(model_dir / "universe.json")
        stats = np.load(model_dir / "normalization_stats.npz")

        model = SuperPnLModel(
            bar_dim=int(model_config["bar_dim"]),
            feature_dim=int(model_config["feature_dim"]),
            num_horizons=int(model_config["num_horizons"]),
            hidden_dim=int(model_config.get("hidden_dim", 64)),
            dropout=float(model_config.get("dropout", 0.05)),
            use_features=bool(model_config.get("use_features", True)),
        )
        checkpoint = torch.load(model_dir / "model.pt", map_location="cpu")
        state_dict = checkpoint.get("model") if isinstance(checkpoint, dict) else checkpoint
        model.load_state_dict(state_dict)
        model.eval()

        symbols = universe.get("symbols_bitpro") or [
            normalize_bitpro_symbol(s) for s in universe.get("symbols_superpnl", [])
        ]
        self._builder = SuperPnLFeatureBuilder(
            symbols=symbols,
            lookback=int(model_config["lookback"]),
            feature_windows=feature_schema.get("feature_windows_minutes") or [5, 15, 30],
            bar_feature_names=feature_schema["bar_feature_names"],
            feature_names=feature_schema["feature_names"],
        )
        self._model = model
        self._model_dir = model_dir
        self._bar_mean = stats["bar_mean"].astype("float32")
        self._bar_std = stats["bar_std"].astype("float32")
        self._feature_mean = stats["feature_mean"].astype("float32")
        self._feature_std = stats["feature_std"].astype("float32")
        self._horizon_index = {
            self._normalize_horizon(k): int(v)
            for k, v in (model_config.get("horizon_index") or {}).items()
        }
        if not self._horizon_index:
            self._horizon_index = {
                self._normalize_horizon(h): idx
                for idx, h in enumerate(model_config.get("horizons") or [])
            }

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _resolve_cache_dir(config_value: str | None) -> str | None:
        value = config_value or os.environ.get("SUPERPNL_MODEL_CACHE_DIR") or "/opt/bitpro/artifacts/superpnl"
        value = value.strip()
        if value in {"", "${SUPERPNL_MODEL_CACHE_DIR}"}:
            return os.environ.get("SUPERPNL_MODEL_CACHE_DIR") or "/opt/bitpro/artifacts/superpnl"
        return value

    @staticmethod
    def _normalize_horizon(value: Any) -> str:
        text = str(value).strip().lower()
        return text if text.endswith("m") else f"{text}m"

    @staticmethod
    def _bar_from_ohlcv_row(
        row: Any,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
    ) -> Optional[BarData]:
        try:
            if isinstance(row, dict):
                timestamp = int(row.get("timestamp"))
                open_price = float(row.get("open"))
                high_price = float(row.get("high"))
                low_price = float(row.get("low"))
                close_price = float(row.get("close"))
                volume = float(row.get("volume") or 0.0)
            else:
                timestamp = int(row[0])
                open_price = float(row[1])
                high_price = float(row[2])
                low_price = float(row[3])
                close_price = float(row[4])
                volume = float(row[5] if len(row) > 5 else 0.0)
        except (TypeError, ValueError, IndexError):
            return None
        return BarData(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            timestamp=canonical_bar_timestamp_ms(timestamp),
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
        )

    @staticmethod
    def _standardize(data: np.ndarray, mean: Optional[np.ndarray], std: Optional[np.ndarray]) -> np.ndarray:
        if mean is None or std is None:
            return data.astype("float32", copy=False)
        denom = np.where(std < 1e-8, 1.0, std)
        out = (data - mean.reshape(1, 1, -1)) / denom.reshape(1, 1, -1)
        return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0).astype("float32")


superpnl_model_inference_service = SuperPnLModelInferenceService()
