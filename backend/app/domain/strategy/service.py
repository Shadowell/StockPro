"""Original BitPro strategy page contract mapped to A-share StrategyVersion rows."""
from __future__ import annotations

import asyncio
import math
import re
from typing import Dict, Optional

from app.domain.strategy.naming import display_strategy_name, require_strategy_name
from app.domain.strategy.repository import StrategyRepository
from app.domain.strategy.validation import validate_strategy_python
from app.services.ashare_execution import instrument_key


class StrategyDomainService:
    A_SHARE_SYMBOL = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
    def __init__(self, repository: StrategyRepository | None = None) -> None:
        self.repository = repository or StrategyRepository()

    @staticmethod
    def _strategy_type(name: str) -> str:
        if "动量" in name or "趋势" in name:
            return "momentum"
        if "回归" in name or "反转" in name or "超跌" in name:
            return "mean_reversion"
        if "因子" in name:
            return "multi_factor"
        if "打板" in name or "涨停" in name:
            return "event"
        return "other"

    @classmethod
    def _view(cls, row: dict) -> dict:
        strategy_id = row.get("legacy_strategy_id") or str(row.get("id"))
        kind = cls._strategy_type(str(row.get("name") or ""))
        parameter_schema = dict(row.get("parameter_schema") or {})
        validation_report = dict(row.get("validation_report") or {})
        backtest_universe = dict(row.get("linked_backtest_universe") or {})
        backtest_metrics = dict(row.get("linked_backtest_metrics") or {})
        paper_parameters = dict(row.get("linked_paper_parameters") or {})
        capacity_limits = dict(row.get("linked_paper_capacity_limits") or {})
        raw_symbols = [
            *(parameter_schema.get("symbols") or []),
            *(backtest_universe.get("symbols") or []),
            *(row.get("linked_paper_symbols") or []),
            row.get("latest_trade_symbol"),
        ]
        symbols = list(dict.fromkeys(
            canonical for canonical in (instrument_key(item) for item in raw_symbols) if canonical
        ))
        is_sample = bool(
            backtest_metrics.get("sample_only")
            or paper_parameters.get("sample_chain")
            or "minimal" in str(row.get("name") or "").lower()
        )
        if is_sample:
            selection_logic = (
                f"固定使用最新 sealed 回测股票池（{len(symbols)} 只），读取真实日线收盘收益并按 daily_return 从高到低排序。"
            )
            entry_logic = "排序结果生成 candidate/buy 记录；最近样例成交为买入 920000.BJ，用于验证数据到 Paper 的审计链路。"
            exit_logic = "未实现。当前策略代码没有卖出、止损或退出信号，现有持仓不能作为完整交易策略证据。"
            rebalance_logic = "日线研究函数每次调用时重新排序候选；未声明定时调仓、目标权重再平衡或换仓条件。"
        else:
            selection_logic = str(parameter_schema.get("selection_logic") or validation_report.get("signal") or "未提供可审计的标的池规则。")
            entry_logic = str(parameter_schema.get("entry_logic") or "未提供可审计的入场说明。")
            exit_logic = str(parameter_schema.get("exit_logic") or "未提供可审计的退出说明。")
            rebalance_logic = str(parameter_schema.get("rebalance_logic") or "未提供可审计的调仓说明。")
        max_weight = capacity_limits.get("max_position_weight")
        risk_constraints = [
            f"Paper 单标的最大仓位 {float(max_weight) * 100:.0f}%" if max_weight is not None else "未记录策略级最大仓位",
            "平台撮合执行 A 股日线、T+1、100 股整手、涨跌停/停牌和交易成本约束",
            "策略代码未实现止损、退出或组合回撤控制" if is_sample else "策略风险以版本参数和平台风控共同约束",
        ]
        paper_status = str(row.get("linked_paper_status") or "")
        status = paper_status if paper_status in {"running", "paused"} else "not_started"
        equity_points = int(row.get("equity_point_count") or 0)
        closed_trades = int(backtest_metrics.get("completed_trades") or 0)
        fill_count = int(row.get("fill_count") or 0)
        backtest_metric_status = "eligible" if equity_points >= 2 and closed_trades > 0 else "insufficient_sample"
        latest_reason = str(row.get("latest_trade_reason") or "")
        if latest_reason == "Minimal sample fill priced from stock_history close.":
            latest_reason = "按 stock_history 真实收盘价生成的最小审计样例成交。"
        description = str(row.get("description") or "")
        if is_sample:
            description = "用于验证 A 股数据、回测、成交与 Paper 关联的最小审计样例，不构成投资建议，也不是正式候选策略。"
        return {
            "id": strategy_id,
            "name": display_strategy_name(str(row.get("name") or "")),
            "description": description,
            "script_content": str(row.get("script_content") or ""),
            "config": {
                **parameter_schema,
                "asset_class": "stock",
                "strategy_type": kind,
                "timeframe": "1d",
                "capital": "1000000CNY",
                "version": int(row.get("version") or 1),
                "validation_status": row.get("validation_status"),
                "symbols": symbols,
                "trade_symbols": symbols,
                "selection_logic": selection_logic,
                "trading_logic": f"入场：{entry_logic} 退出：{exit_logic} 调仓：{rebalance_logic}",
                "entry_logic": entry_logic,
                "exit_logic": exit_logic,
                "rebalance_logic": rebalance_logic,
                "risk_constraints": risk_constraints,
            },
            "status": status,
            "definition_status": row.get("status"),
            "exchange": "CN",
            "symbols": symbols,
            "version_id": str(row.get("id") or ""),
            "version": int(row.get("version") or 1),
            "version_parameters": parameter_schema,
            "content_hash": row.get("content_hash"),
            "strategy_api_version": row.get("strategy_api_version"),
            "validation_status": row.get("validation_status"),
            "validation_report": validation_report,
            "validated_at": row.get("validated_at"),
            "data_dependencies": list(row.get("data_dependencies") or []),
            "output_contract": dict(row.get("output_contract") or {}),
            "is_sample": is_sample,
            "disclaimer": "样例 / 非投资建议" if is_sample else None,
            "audit_summary": {
                "selection_logic": selection_logic,
                "entry_logic": entry_logic,
                "exit_logic": exit_logic,
                "rebalance_logic": rebalance_logic,
                "risk_constraints": risk_constraints,
                "universe_symbols": symbols,
                "latest_execution_reason": latest_reason or None,
            },
            "linked_backtest": ({
                "id": int(row.get("linked_backtest_id")),
                "uuid": str(row.get("linked_backtest_uuid")),
                "status": row.get("linked_backtest_status"),
                "start_date": row.get("linked_backtest_start_date"),
                "end_date": row.get("linked_backtest_end_date"),
                "fill_count": fill_count,
                "closed_trade_count": closed_trades,
                "order_count": int(row.get("order_count") or 0),
                "equity_point_count": equity_points,
                "metric_status": backtest_metric_status,
            } if row.get("linked_backtest_uuid") else None),
            "linked_paper": ({
                "id": int(row.get("linked_paper_id")),
                "uuid": str(row.get("linked_paper_uuid")),
                "status": paper_status,
                "runtime_version": row.get("linked_paper_runtime_version"),
                "symbols": [instrument_key(item) for item in (row.get("linked_paper_symbols") or []) if instrument_key(item)],
                "capacity_limits": capacity_limits,
                "feed_config": dict(row.get("linked_paper_feed_config") or {}),
                "console_path": f"/live?mode=paper&instance_id={int(row.get('linked_paper_id'))}",
            } if row.get("linked_paper_uuid") else None),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    async def list_page(self, *, page: int, per_page: int, search: str = "", status: str = "all", asset_class: str = "all", strategy_type: str = "all", timeframe: str = "all", capital: str = "all") -> Dict:
        rows = await asyncio.to_thread(self.repository.list_strategies)
        items = [self._view(row) for row in rows]
        needle = search.strip().lower()
        if needle:
            items = [item for item in items if needle in f"{item['name']} {item['description']}".lower()]
        if status != "all": items = [item for item in items if item["status"] == status]
        if asset_class != "all": items = [item for item in items if item["config"]["asset_class"] == asset_class]
        if strategy_type != "all": items = [item for item in items if item["config"]["strategy_type"] == strategy_type]
        if timeframe != "all": items = [item for item in items if item["config"]["timeframe"] == timeframe]
        if capital != "all": items = [item for item in items if item["config"]["capital"] == capital]
        total = len(items)
        start = (page - 1) * per_page
        kinds = ("momentum", "mean_reversion", "multi_factor", "event", "other")
        return {
            "items": items[start:start + per_page], "total": total, "page": page, "per_page": per_page,
            "pages": max(1, math.ceil(total / per_page)),
            "status_counts": {"all": total, "running": sum(item["status"] == "running" for item in items), "paused": sum(item["status"] == "paused" for item in items), "not_started": sum(item["status"] == "not_started" for item in items)},
            "asset_counts": {"all": total, "stock": total, "etf": 0},
            "type_counts": {"all": total, **{kind: sum(item["config"]["strategy_type"] == kind for item in items) for kind in kinds}},
            "timeframe_counts": {"all": total, "1d": total},
            "capital_counts": {"all": total, "1000000CNY": total},
        }

    async def get(self, strategy_id: int | str) -> Optional[dict]:
        row = await asyncio.to_thread(self.repository.get_strategy, strategy_id)
        return self._view(row) if row else None

    @staticmethod
    def _write_payload(payload: dict, *, current: dict | None = None) -> tuple[dict, dict]:
        name = require_strategy_name(str(payload.get("name") or (current or {}).get("name") or ""))
        code = str(payload.get("script_content") or (current or {}).get("script_content") or "")
        if not code.strip():
            raise ValueError("策略代码必填")
        validation = validate_strategy_python(code)
        if not validation["valid"]:
            first = validation["issues"][0]
            raise ValueError(f"策略代码未通过验证：{first['message']}")
        config = dict(payload.get("config") or payload.get("parameter_schema") or (current or {}).get("parameter_schema") or {})
        asset_class = str(config.get("asset_class") or "stock").lower()
        if asset_class not in {"stock", "etf"}:
            raise ValueError("asset_class 仅支持 stock 或 etf")
        symbols = [str(item).strip().upper() for item in (payload.get("symbols") or config.get("symbols") or []) if str(item).strip()]
        invalid_symbols = [symbol for symbol in symbols if not StrategyDomainService.A_SHARE_SYMBOL.fullmatch(symbol)]
        if invalid_symbols:
            raise ValueError(f"无效 A 股标的：{invalid_symbols[0]}")
        config.update(
            {
                "asset_class": asset_class,
                "timeframe": "1d",
                "capital": "1000000CNY",
                "symbols": symbols,
            }
        )
        return {
            "name": name,
            "description": str(payload.get("description", (current or {}).get("description") or "")),
            "script_content": code,
            "parameter_schema": config,
            "data_dependencies": ["daily_bars"],
        }, validation

    async def create(self, payload: dict) -> dict:
        normalized, validation = self._write_payload(payload)
        row = await asyncio.to_thread(self.repository.create_strategy, normalized, validation)
        return self._view(row)

    async def update(self, strategy_id: int | str, payload: dict) -> dict:
        current = await asyncio.to_thread(self.repository.get_strategy, strategy_id)
        if not current:
            raise ValueError("策略不存在")
        normalized, validation = self._write_payload(payload, current=current)
        row = await asyncio.to_thread(self.repository.create_version, strategy_id, normalized, validation)
        return self._view(row)

    async def archive(self, strategy_id: int | str) -> dict:
        archived = await asyncio.to_thread(self.repository.archive_strategy, strategy_id)
        if not archived:
            raise ValueError("策略不存在")
        return {"archived": True, "strategy_id": strategy_id}


strategy_domain_service = StrategyDomainService()
