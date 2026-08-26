"""Resolve BitPro backtest requests into sealed A-share evidence bundles."""
from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from app.services.ashare_execution import explicit_instrument_key


REQUIRED_DATASETS = {
    "daily_bars",
    "trade_calendar",
    "benchmark_bars",
    "price_limits",
    "suspensions",
    "corporate_actions",
}


class BacktestInputGateway(Protocol):
    def get_strategy(self, strategy_id: int | str) -> dict | None: ...
    def resolve_snapshot(self, *, start_date: str, end_date: str, snapshot_id: int | None, required_datasets: set[str]) -> dict: ...
    def resolve_pool(self, *, snapshot_id: int, pool_snapshot_id: int | None) -> dict: ...
    def load_dataset(self, snapshot_id: int, dataset_code: str, *, symbols: list[str], start_date: str, end_date: str) -> list[dict]: ...


class BacktestInputResolver:
    def __init__(self, gateway: BacktestInputGateway) -> None:
        self.gateway = gateway

    @staticmethod
    def _date(value: Any, label: str) -> str:
        try:
            return date.fromisoformat(str(value or "")[:10]).isoformat()
        except ValueError as exc:
            raise ValueError(f"{label}格式无效") from exc

    @staticmethod
    def _symbols(values: Any) -> list[str]:
        symbols: list[str] = []
        for raw in values or []:
            symbol = explicit_instrument_key(raw)
            if not symbol:
                raise ValueError(f"无效 A 股标的：{raw}")
            if symbol not in symbols:
                symbols.append(symbol)
        return symbols

    @staticmethod
    def _normalize_rows(dataset_code: str, rows: list[dict], selected: set[str]) -> list[dict]:
        normalized: list[dict] = []
        symbol_datasets = {"daily_bars", "benchmark_bars", "price_limits", "suspensions", "corporate_actions"}
        for raw in rows:
            row = dict(raw)
            if dataset_code in symbol_datasets:
                source_symbol = row.get("symbol") or row.get("ts_code")
                symbol = explicit_instrument_key(source_symbol)
                if not symbol:
                    raise ValueError(f"封存数据包含无效证券代码：{dataset_code}:{source_symbol}")
                row["symbol"] = symbol
                if dataset_code == "daily_bars" and symbol not in selected:
                    continue
            normalized.append(row)
        return normalized

    def resolve(self, request: dict[str, Any]) -> dict[str, Any]:
        exchange = str(request.get("exchange") or "CN").upper()
        if exchange not in {"CN", "A_SHARE", "ASHARE", "SSE", "SZSE"}:
            raise ValueError("回测仅支持 A 股市场")
        timeframe = str(request.get("timeframe") or "1d").lower()
        timeframes = [str(item).lower() for item in (request.get("timeframes") or [timeframe])]
        if timeframe != "1d" or any(item != "1d" for item in timeframes):
            raise ValueError("A 股当前仅支持 1d 回测")
        start_date = self._date(request.get("start_date"), "开始日期")
        end_date = self._date(request.get("end_date"), "结束日期")
        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        initial_cash = float(request.get("initial_capital") or 0)
        if not 0 < initial_cash <= 1_000_000_000:
            raise ValueError("初始资金必须在 0 到 10 亿元之间")

        strategy = self.gateway.get_strategy(request.get("strategy_id"))
        if not strategy:
            raise ValueError("策略版本不存在")
        if strategy.get("validation_status") != "valid":
            raise ValueError("策略版本未通过 stockpro.v1 验证")

        snapshot = self.gateway.resolve_snapshot(
            start_date=start_date,
            end_date=end_date,
            snapshot_id=int(request["dataset_snapshot_id"]) if request.get("dataset_snapshot_id") is not None else None,
            required_datasets=set(REQUIRED_DATASETS),
        )
        if snapshot.get("status") != "sealed":
            raise ValueError("回测只能读取 sealed 数据快照")
        pool = self.gateway.resolve_pool(
            snapshot_id=int(snapshot["id"]),
            pool_snapshot_id=int(request["pool_snapshot_id"]) if request.get("pool_snapshot_id") is not None else None,
        )
        if int(pool.get("dataset_snapshot_id") or 0) != int(snapshot["id"]):
            raise ValueError("股票池与数据快照不属于同一证据版本")

        pool_symbols = self._symbols(pool.get("symbols") or [])
        config = dict(strategy.get("parameter_schema") or {})
        symbols = self._symbols(request.get("symbols") or config.get("symbols") or pool_symbols)
        if not symbols:
            raise ValueError("回测股票池为空")
        outside = sorted(set(symbols) - set(pool_symbols))
        if outside:
            raise ValueError(f"标的不在 sealed 股票池：{outside[0]}")

        datasets: dict[str, list[dict]] = {}
        for dataset_code in sorted(REQUIRED_DATASETS):
            rows = self.gateway.load_dataset(
                int(snapshot["id"]),
                dataset_code,
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
            )
            datasets[dataset_code] = self._normalize_rows(dataset_code, rows, set(symbols))
        if not datasets["daily_bars"]:
            raise ValueError("所选区间与股票池没有 sealed 日线")
        if not datasets["trade_calendar"]:
            raise ValueError("sealed 快照缺少交易日历")
        if not datasets["benchmark_bars"]:
            raise ValueError("sealed 快照缺少沪深 300 基准")
        if not datasets["price_limits"]:
            raise ValueError("sealed 快照缺少涨跌停证据")

        slippage_bps = float(request.get("slippage_bps") if request.get("slippage_bps") is not None else 10)
        if not 0 <= slippage_bps <= 100:
            raise ValueError("滑点必须在 0 到 100 bps 之间")
        return {
            "strategy_version": strategy,
            "dataset_snapshot": snapshot,
            "pool_snapshot": pool,
            "symbols": symbols,
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": initial_cash,
            "frequency": "1d",
            "cost_model": {
                "commission_rate": 0.0003,
                "minimum_commission": 5.0,
                "stamp_duty_rate": 0.0005,
                "transfer_fee_rate": 0.00001,
                "slippage_rate": slippage_bps / 10_000,
                "max_participation_rate": 0.10,
            },
            "datasets": datasets,
        }
