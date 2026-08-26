"""
策略管理服务
"""
import asyncio
from datetime import datetime
import json
import logging
import math
import re
from typing import Any, List, Dict, Optional

from app.db.local_db import db_instance as db
from app.models.schemas import StrategyCreate, StrategyUpdate
from app.services.agent.code_sandbox import load_base_strategy_class
from app.services.paper_performance_metrics import equity_curve_risk_metrics
from app.services.strategy_engine import strategy_engine

logger = logging.getLogger(__name__)


_ACTIVE_DELETE_BLOCK = frozenset({"running", "paused"})
_DB_SCRIPT_SOURCE = "db_script"
_DB_SCRIPT_SOURCE_VALUES = frozenset({_DB_SCRIPT_SOURCE, "dynamic_db_script", "script_content"})


def _prepare_dynamic_script_strategy_config(
    *,
    script_content: str,
    config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate API-created dynamic strategy code and mark it as DB-backed."""
    try:
        strategy_cls = load_base_strategy_class(script_content)
    except Exception as exc:
        raise ValueError(f"动态策略代码未通过 BaseStrategy 校验: {exc}") from exc

    prepared = dict(config or {})
    prepared.setdefault("strategy_source", _DB_SCRIPT_SOURCE)
    prepared.setdefault("script_content_source", "db")
    prepared.setdefault("class_name", strategy_cls.__name__)
    return prepared


def _is_dynamic_script_config(config: Optional[Dict[str, Any]]) -> bool:
    values = config or {}
    strategy_source = str(values.get("strategy_source") or "").strip().lower()
    script_source = str(values.get("script_content_source") or "").strip().lower()
    return (
        strategy_source in _DB_SCRIPT_SOURCE_VALUES
        or script_source == "db"
        or values.get("ai_generated") is True
    )


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _contract_trade_meta(trade: Dict) -> Optional[Dict[str, Any]]:
    meta = trade.get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            return None
    if isinstance(meta, dict):
        return dict(meta)
    return None


def _store_trade_meta(trade: Dict, meta: Dict[str, Any]) -> None:
    if isinstance(trade.get("meta"), str):
        trade["meta"] = json.dumps(meta, ensure_ascii=False)
    else:
        trade["meta"] = meta


def normalize_contract_close_trade_leverage(trades: List[Dict]) -> List[Dict]:
    """Infer close-trade leverage from the open position for older persisted rows."""
    rows = [dict(row) for row in trades]
    open_positions: Dict[tuple[str, str], Dict[str, float]] = {}

    def sort_key(row: Dict) -> tuple[float, float]:
        return (_as_float(row.get("timestamp")), _as_float(row.get("id")))

    for trade in sorted(rows, key=sort_key):
        meta = _contract_trade_meta(trade)
        if not meta or str(meta.get("market_type") or "").lower() != "swap":
            continue
        action = str(meta.get("action") or "").lower()
        pos_side = str(meta.get("pos_side") or "").lower()
        symbol = str(trade.get("symbol") or meta.get("symbol") or "")
        if not symbol or pos_side not in {"long", "short"}:
            continue

        key = (symbol, pos_side)
        contracts = _as_float(meta.get("contracts") or trade.get("quantity"))
        if action == "open":
            leverage = _as_float(meta.get("leverage"))
            if leverage <= 0:
                continue
            current = open_positions.get(key)
            if current:
                current["contracts"] += contracts
                current["leverage"] = max(current["leverage"], leverage)
            else:
                open_positions[key] = {"contracts": contracts, "leverage": leverage}
        elif action in {"close", "liquidation"}:
            current = open_positions.get(key)
            if current and current["leverage"] > 0:
                meta["leverage"] = current["leverage"]
                _store_trade_meta(trade, meta)
                current["contracts"] -= contracts
                if current["contracts"] <= 1e-9:
                    open_positions.pop(key, None)

    return rows


class StrategyService:
    """策略管理服务"""
    
    async def get_strategies(self) -> List[Dict]:
        """获取所有策略"""
        strategies = db.get_strategies()
        return strategies

    @staticmethod
    def _strategy_asset_class(strategy: Dict) -> str:
        config = strategy.get("config") if isinstance(strategy.get("config"), dict) else {}
        configured = str(config.get("asset_class") or config.get("assetClass") or "").lower()
        if configured in {"spot", "contract"}:
            return configured
        market_type = str(config.get("market_type") or config.get("marketType") or "").lower()
        inst_type = str(config.get("inst_type") or config.get("instType") or "").upper()
        if market_type in {"swap", "future", "futures", "contract"} or inst_type == "SWAP":
            return "contract"
        if market_type == "spot" or inst_type == "SPOT":
            return "spot"
        name = str(strategy.get("name") or "")
        if name.startswith("[合约]") or name.startswith("[合约]["):
            return "contract"
        if name.startswith("[现货]") or name.startswith("[现货]["):
            return "spot"
        symbols = strategy.get("symbols") if isinstance(strategy.get("symbols"), list) else []
        if any(":USDT" in str(symbol).upper() or "-SWAP" in str(symbol).upper() for symbol in symbols):
            return "contract"
        return "spot"

    @staticmethod
    def _strategy_status_bucket(status: str | None) -> str:
        if status == "running":
            return "running"
        if status == "paused":
            return "paused"
        return "not_started"

    @staticmethod
    def _strategy_type_bucket(strategy: Dict) -> str:
        config = strategy.get("config") if isinstance(strategy.get("config"), dict) else {}
        name = str(strategy.get("name") or "").lower()
        configured_type = str(config.get("strategy_type") or config.get("strategyType") or config.get("type") or "").lower()
        strategy_key = str(config.get("strategy_key") or config.get("strategyKey") or "").lower()
        observation_mode = str(config.get("market_observation_mode") or config.get("marketObservationMode") or "").lower()
        text = " ".join([name, configured_type, strategy_key])
        if (
            configured_type in {"market_making", "market-making", "mm", "做市"}
            or "[做市]" in name
            or "做市" in name
            or "market_making" in text
            or "market-making" in text
        ):
            return "market_making"
        if "[ai]" in name or configured_type == "ai" or observation_mode.startswith("ai_") or "自主" in name:
            return "ai"
        if "[马丁]" in name or "马丁" in name or "martingale" in text:
            return "martingale"
        if "[cta]" in name or "cta" in text or "trend" in text:
            return "cta"
        return "other"

    @staticmethod
    def _normalize_strategy_timeframe(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        mapping = {
            "1min": "1m",
            "5min": "5m",
            "15min": "15m",
            "30min": "30m",
            "60m": "1h",
            "1hour": "1h",
            "4hour": "4h",
            "12hour": "12h",
            "1day": "1d",
            "day": "1d",
        }
        return mapping.get(raw, raw)

    def _strategy_timeframe_bucket(self, strategy: Dict) -> str:
        config = strategy.get("config") if isinstance(strategy.get("config"), dict) else {}
        configured = self._normalize_strategy_timeframe(
            config.get("timeframe") or config.get("kline_timeframe") or config.get("klineTimeframe")
        )
        if configured:
            return configured
        name = str(strategy.get("name") or "").upper()
        match = re.search(r"\[(1M|5M|15M|30M|1H|4H|12H|1D)\]", name)
        return match.group(1).lower() if match else ""

    @staticmethod
    def _strategy_capital_bucket(strategy: Dict) -> str:
        config = strategy.get("config") if isinstance(strategy.get("config"), dict) else {}
        for key in ("initial_capital", "initialCapital", "initial_equity", "initialEquity", "paper_capital", "paperCapital"):
            value = config.get(key)
            try:
                if value is not None and float(value) > 0:
                    amount = int(float(value))
                    return f"{amount}U"
            except (TypeError, ValueError):
                continue
        name = str(strategy.get("name") or "").upper()
        match = re.search(r"(\d+(?:\.\d+)?)U", name)
        if not match:
            return ""
        amount = float(match.group(1))
        return f"{int(amount)}U" if amount.is_integer() else f"{amount:g}U"

    @staticmethod
    def _normalize_strategy_search_text(value: Any) -> str:
        return re.sub(r"[\s\-_/：:·.,，。\[\]【】()（）]+", "", str(value or "").lower())

    def _strategy_search_document(self, strategy: Dict) -> str:
        config = strategy.get("config") if isinstance(strategy.get("config"), dict) else {}
        asset_class = self._strategy_asset_class(strategy)
        asset_label = "合约" if asset_class == "contract" else "现货"
        status_bucket = self._strategy_status_bucket(strategy.get("status"))
        status_label = {
            "running": "运行中",
            "paused": "暂停",
            "not_started": "未启动",
        }[status_bucket]
        haystack = " ".join(
            [
                str(strategy.get("id") or ""),
                str(strategy.get("name") or ""),
                str(strategy.get("description") or ""),
                " ".join(str(symbol) for symbol in strategy.get("symbols") or []),
                self._strategy_timeframe_bucket(strategy),
                self._strategy_capital_bucket(strategy),
                self._strategy_type_bucket(strategy),
                str(strategy.get("status") or ""),
                status_label,
                asset_class,
                asset_label,
                json.dumps(config, ensure_ascii=False, sort_keys=True),
            ]
        )
        return self._normalize_strategy_search_text(haystack)

    def _matches_strategy_search(self, strategy: Dict, query: str) -> bool:
        if not query:
            return True
        tokens = [
            self._normalize_strategy_search_text(token)
            for token in query.split()
            if self._normalize_strategy_search_text(token)
        ]
        if not tokens:
            return True
        haystack = self._strategy_search_document(strategy)
        return all(token in haystack for token in tokens)

    async def get_strategies_page(
        self,
        *,
        page: int,
        per_page: int,
        search: str = "",
        status: str = "all",
        asset_class: str = "all",
        strategy_type: str = "all",
        timeframe: str = "all",
        capital: str = "all",
    ) -> Dict:
        """获取策略分页，避免策略库首屏一次性传输全部策略源码和配置。"""
        normalized_page = max(1, int(page))
        normalized_per_page = max(1, min(int(per_page), 60))
        normalized_search = (search or "").strip()
        normalized_status = status if status in {"all", "running", "paused", "not_started"} else "all"
        normalized_asset = asset_class if asset_class in {"all", "spot", "contract"} else "all"
        normalized_type = str(strategy_type or "all").lower()
        if normalized_type not in {"all", "cta", "martingale", "ai", "market_making"}:
            normalized_type = "__invalid__"
        normalized_timeframe = self._normalize_strategy_timeframe(timeframe)
        if normalized_timeframe not in {"all", "1m", "5m", "15m", "30m", "1h", "4h", "12h", "1d"}:
            normalized_timeframe = "all"
        normalized_capital = str(capital or "all").upper()
        if normalized_capital not in {"ALL", "100U", "1000U"}:
            normalized_capital = "ALL"

        strategies = db.get_strategies()

        def match_search(item: Dict) -> bool:
            return self._matches_strategy_search(item, normalized_search)

        def match_status(item: Dict) -> bool:
            return normalized_status == "all" or self._strategy_status_bucket(item.get("status")) == normalized_status

        def match_asset(item: Dict) -> bool:
            return normalized_asset == "all" or self._strategy_asset_class(item) == normalized_asset

        def match_type(item: Dict) -> bool:
            return normalized_type == "all" or (
                normalized_type != "__invalid__" and self._strategy_type_bucket(item) == normalized_type
            )

        def match_timeframe(item: Dict) -> bool:
            return normalized_timeframe == "all" or self._strategy_timeframe_bucket(item) == normalized_timeframe

        def match_capital(item: Dict) -> bool:
            return normalized_capital == "ALL" or self._strategy_capital_bucket(item).upper() == normalized_capital

        count_source = strategies
        status_counts = {"all": 0, "running": 0, "paused": 0, "not_started": 0}
        for item in count_source:
            if match_asset(item) and match_type(item) and match_timeframe(item) and match_capital(item):
                status_counts["all"] += 1
                status_counts[self._strategy_status_bucket(item.get("status"))] += 1

        asset_counts = {"all": 0, "spot": 0, "contract": 0}
        for item in count_source:
            if match_status(item) and match_type(item) and match_timeframe(item) and match_capital(item):
                asset = self._strategy_asset_class(item)
                asset_counts["all"] += 1
                asset_counts[asset] += 1

        type_counts = {"all": 0, "cta": 0, "martingale": 0, "ai": 0, "market_making": 0}
        for item in count_source:
            if match_status(item) and match_asset(item) and match_timeframe(item) and match_capital(item):
                bucket = self._strategy_type_bucket(item)
                type_counts["all"] += 1
                if bucket in type_counts:
                    type_counts[bucket] += 1

        timeframe_counts = {
            "all": 0,
            "1m": 0,
            "5m": 0,
            "15m": 0,
            "30m": 0,
            "1h": 0,
            "4h": 0,
            "12h": 0,
            "1d": 0,
        }
        for item in count_source:
            if match_status(item) and match_asset(item) and match_type(item) and match_capital(item):
                bucket = self._strategy_timeframe_bucket(item)
                timeframe_counts["all"] += 1
                if bucket in timeframe_counts:
                    timeframe_counts[bucket] += 1

        capital_counts = {"all": 0, "100U": 0, "1000U": 0}
        for item in count_source:
            if match_status(item) and match_asset(item) and match_type(item) and match_timeframe(item):
                bucket = self._strategy_capital_bucket(item)
                capital_counts["all"] += 1
                if bucket in capital_counts:
                    capital_counts[bucket] += 1

        filtered = [
            item
            for item in strategies
            if match_status(item)
            and match_asset(item)
            and match_type(item)
            and match_timeframe(item)
            and match_capital(item)
            and match_search(item)
        ]
        total = len(filtered)
        pages = max(1, math.ceil(total / normalized_per_page)) if total else 1
        safe_page = min(normalized_page, pages)
        start = (safe_page - 1) * normalized_per_page
        end = start + normalized_per_page

        return {
            "items": filtered[start:end],
            "total": total,
            "page": safe_page,
            "per_page": normalized_per_page,
            "pages": pages,
            "status_counts": status_counts,
            "asset_counts": asset_counts,
            "type_counts": type_counts,
            "timeframe_counts": timeframe_counts,
            "capital_counts": capital_counts,
        }
    
    async def get_strategy(self, strategy_id: int) -> Optional[Dict]:
        """获取策略详情"""
        return db.get_strategy_by_id(strategy_id)
    
    async def create_strategy(self, strategy: StrategyCreate) -> Dict:
        """创建策略"""
        config = _prepare_dynamic_script_strategy_config(
            script_content=strategy.script_content,
            config=strategy.config,
        )
        strategy_id = db.save_strategy(
            name=strategy.name,
            script_content=strategy.script_content,
            description=strategy.description,
            config=config,
            exchange=strategy.exchange,
            symbols=strategy.symbols
        )
        
        return await self.get_strategy(strategy_id)
    
    async def update_strategy(self, strategy_id: int, strategy: StrategyUpdate) -> Optional[Dict]:
        """更新策略"""
        existing = db.get_strategy_by_id(strategy_id)
        if not existing:
            return None
        
        # 检查策略是否在运行
        status = strategy_engine.get_strategy_status(strategy_id)
        if status and status.get('status') == 'running':
            raise ValueError("Cannot update running strategy")
        
        script_content = (
            strategy.script_content
            if strategy.script_content is not None
            else existing['script_content']
        )
        config = strategy.config if strategy.config is not None else existing.get('config')
        if strategy.script_content is not None or _is_dynamic_script_config(existing.get('config')):
            config = _prepare_dynamic_script_strategy_config(
                script_content=script_content,
                config=config,
            )

        # 合并更新
        update_data = {
            'strategy_id': strategy_id,
            'name': strategy.name or existing['name'],
            'script_content': script_content,
            'description': strategy.description if strategy.description is not None else existing.get('description'),
            'config': config,
            'exchange': strategy.exchange if strategy.exchange is not None else existing.get('exchange'),
            'symbols': strategy.symbols if strategy.symbols is not None else existing.get('symbols'),
        }

        db.update_strategy(**update_data)
        
        return await self.get_strategy(strategy_id)
    
    async def delete_strategy(self, strategy_id: int) -> bool:
        """删除策略（运行中或已暂停时不允许删除，需用户先停止）。"""
        row = db.get_strategy_by_id(strategy_id)
        if not row:
            return False

        db_status = (row.get("status") or "").lower()
        if db_status in _ACTIVE_DELETE_BLOCK:
            raise ValueError(
                "策略正在运行或已暂停，请先在「模拟/实盘」页面停止策略后再删除。"
            )

        eng = strategy_engine.get_strategy_status(strategy_id)
        if eng:
            eng_status = (eng.get("status") or "").lower()
            if eng_status in _ACTIVE_DELETE_BLOCK:
                raise ValueError(
                    "策略正在运行或已暂停，请先在「模拟/实盘」页面停止策略后再删除。"
                )

        return db.delete_strategy(strategy_id)
    
    async def start_strategy(self, strategy_id: int) -> bool:
        """启动策略"""
        return await strategy_engine.start_strategy(strategy_id)
    
    async def stop_strategy(self, strategy_id: int) -> bool:
        """停止策略"""
        return await strategy_engine.stop_strategy(strategy_id)

    async def reset_circuit_breaker(self) -> Dict:
        """人工解除全局熔断"""
        await strategy_engine.reset_global_circuit_breaker()
        return strategy_engine.get_risk_status()

    async def get_risk_status(self) -> Dict:
        """获取全局风控状态"""
        return strategy_engine.get_risk_status()
    
    async def get_strategy_trades(self, strategy_id: int, limit: int = 50) -> List[Dict]:
        """获取策略交易记录"""
        return normalize_contract_close_trade_leverage(db.get_strategy_trades(strategy_id, limit))
    
    async def get_strategy_status(self, strategy_id: int) -> Optional[Dict]:
        """获取策略运行状态"""
        # 先从引擎获取实时状态
        engine_status = strategy_engine.get_strategy_status(strategy_id)
        if engine_status:
            return engine_status
        
        # 否则从数据库获取
        strategy = db.get_strategy_by_id(strategy_id)
        if not strategy:
            return None
        
        # 获取最近交易
        recent_trades = db.get_strategy_trades(strategy_id, 5)
        
        # 计算 PnL
        total_pnl = sum(t.get('pnl', 0) or 0 for t in recent_trades)
        
        return {
            'strategy_id': strategy_id,
            'name': strategy['name'],
            'status': strategy.get('status', 'stopped'),
            'exchange': strategy.get('exchange'),
            'symbols': strategy.get('symbols'),
            'pnl': total_pnl,
            'total_trades': len(recent_trades),
            'positions': {},
            'error_message': None,
            'started_at': None,
        }
    
    async def get_all_running(self, *, refresh_marks: bool = False) -> List[Dict]:
        """获取所有运行中的策略"""
        statuses = strategy_engine.get_all_running(refresh_marks=refresh_marks)
        strategy_ids = [
            int(status.get("strategy_id"))
            for status in statuses
            if status.get("strategy_id") is not None
        ]
        equity_samples: Dict[int, List[Dict[str, Any]]] = {}
        rolling_drawdowns: Dict[int, float] = {}
        if strategy_ids and hasattr(db, "get_strategy_equity_samples_bulk"):
            try:
                equity_samples = await asyncio.to_thread(
                    db.get_strategy_equity_samples_bulk,
                    strategy_ids,
                    400,
                )
            except Exception as exc:
                logger.debug("Load running strategy equity samples failed: %s", exc)
        if strategy_ids and hasattr(db, "get_strategy_rolling_max_drawdowns"):
            try:
                rolling_drawdowns = await asyncio.to_thread(
                    db.get_strategy_rolling_max_drawdowns,
                    strategy_ids,
                    30,
                )
            except Exception as exc:
                logger.debug("Load running strategy rolling drawdowns failed: %s", exc)

        for status in statuses:
            strategy_id = int(status.get("strategy_id") or 0)
            metrics = equity_curve_risk_metrics(equity_samples.get(strategy_id, []))
            status["sharpe_ratio"] = round(metrics["sharpe_ratio"], 6)
            max_drawdown = rolling_drawdowns.get(strategy_id, metrics["max_drawdown"])
            status["max_drawdown"] = round(max_drawdown, 6)
            status["max_drawdown_window_days"] = 30
        return statuses


# 全局服务实例
strategy_service = StrategyService()
