"""Original BitPro strategy page contract mapped to A-share StrategyVersion rows."""
from __future__ import annotations

import asyncio
import math
import re
from typing import Dict, Optional

from app.domain.strategy.repository import StrategyRepository
from app.domain.strategy.validation import validate_strategy_python


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
        status = "not_started" if row.get("status") in {None, "draft", "archived"} else str(row.get("status"))
        return {
            "id": strategy_id,
            "name": str(row.get("name") or ""),
            "description": str(row.get("description") or ""),
            "script_content": str(row.get("script_content") or ""),
            "config": {
                **dict(row.get("parameter_schema") or {}),
                "asset_class": "stock",
                "strategy_type": kind,
                "timeframe": "1d",
                "capital": "1000000CNY",
                "version": int(row.get("version") or 1),
                "validation_status": row.get("validation_status"),
            },
            "status": status,
            "exchange": "CN",
            "symbols": list((row.get("parameter_schema") or {}).get("symbols") or []),
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
        name = str(payload.get("name") or (current or {}).get("name") or "").strip()
        code = str(payload.get("script_content") or (current or {}).get("script_content") or "")
        if not name:
            raise ValueError("策略名称必填")
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
