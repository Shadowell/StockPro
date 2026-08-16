"""Read-only research-desk snapshot for the quant operator shell."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence

import psycopg2.extras

logger = logging.getLogger(__name__)

PIPELINE: Sequence[Dict[str, str]] = (
    {"id": "data", "label": "数据", "route": "/data"},
    {"id": "market", "label": "行情", "route": "/market"},
    {"id": "factors", "label": "因子", "route": "/factors"},
    {"id": "pools", "label": "股票池", "route": "/pools"},
    {"id": "strategy", "label": "策略", "route": "/strategy"},
    {"id": "backtest", "label": "回测", "route": "/backtest"},
    {"id": "paper", "label": "模拟", "route": "/paper"},
    {"id": "watch", "label": "盯盘", "route": "/watch"},
    {"id": "monitor", "label": "监控", "route": "/monitor"},
    {"id": "review", "label": "复盘", "route": "/review"},
)

PIPELINE_FACTOR_CODES: Sequence[str] = (
    "momentum_20d",
    "reversal_3d",
    "volatility_20d",
    "amihud_5d",
)


def choose_next_action(
    stages: Sequence[Mapping[str, Any]],
    active_strategy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, str]:
    """Pick the first incomplete research-desk stage as the operator next action."""
    by_id = {str(item.get("id")): item for item in stages}
    checks = (
        ("data", "确认数据快照", "还没有已封存的研究数据快照，先在数据中心核对覆盖与封存状态。"),
        ("market", "查看市场证据", "市场证据未封存，先确认交易日、涨停生态与板块结构。"),
        ("factors", "计算因子快照", "尚无已发布因子值，多因子策略只能退回价格动量。"),
        ("pools", "封存股票池", "还没有股票池快照，回测和模拟缺少固定宇宙。"),
        ("strategy", "打开多因子策略", "还没有可运行的策略版本，先保存多因子风险预算策略。"),
        ("backtest", "提交回测", "策略已就绪，但还没有回测证据。"),
        ("paper", "创建模拟实例", "回测已有结果，可将固定版本晋级到 Paper。"),
        ("watch", "盯盘观察", "模拟实例已在跑，到盯盘核对信号、委托和成交。"),
        ("review", "写每日复盘", "链路已有运行证据，收盘后记录结论与次日计划。"),
    )
    for stage_id, label, reason in checks:
        stage = by_id.get(stage_id) or {}
        if stage.get("status") != "available":
            return {"label": label, "route": str(stage.get("route") or f"/{stage_id}"), "reason": reason}
    strategy_name = str((active_strategy or {}).get("name") or "当前策略")
    return {
        "label": "继续盯盘",
        "route": "/watch",
        "reason": f"{strategy_name} 的研究链路已齐，继续观察信号与风险。",
    }


_DESK_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_DESK_TTL_SECONDS = 60.0


class ResearchDeskService:
    def __init__(self, database):
        self.database = database

    def build(self) -> Dict[str, Any]:
        now = time.monotonic()
        cached = _DESK_CACHE.get("payload")
        if cached and now - float(_DESK_CACHE.get("at") or 0) < _DESK_TTL_SECONDS:
            return cached
        try:
            with self.database.get_connection() as connection:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    payload = self._build(cursor)
        except Exception as exc:
            logger.warning("research desk build failed: %s", exc)
            return cached or self._fallback()
        _DESK_CACHE["at"] = time.monotonic()
        _DESK_CACHE["payload"] = payload
        return payload

    def _build(self, cursor) -> Dict[str, Any]:
        dataset = self._one(
            cursor,
            """
            SELECT id, status, knowledge_cutoff_at
            FROM dataset_snapshots
            WHERE status = 'sealed'
            ORDER BY knowledge_cutoff_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
        )
        dataset_count = self._count(cursor, "SELECT COUNT(*) FROM dataset_snapshots WHERE status = 'sealed'")
        market = self._one(
            cursor,
            """
            SELECT id, trade_date, status
            FROM market_evidence_snapshots
            ORDER BY trade_date DESC NULLS LAST, id DESC
            LIMIT 1
            """,
        )
        factor_defs = self._count(cursor, "SELECT COUNT(*) FROM factor_definitions")
        factor_published = self._count(
            cursor, "SELECT COUNT(*) FROM factor_versions WHERE validation_status = 'valid'"
        )
        factor_runs = self._count(
            cursor,
            "SELECT COUNT(*) FROM factor_compute_runs WHERE status IN ('published', 'success', 'sealed')",
        )
        factor_ready = self._count(
            cursor,
            """
            SELECT COUNT(*) FROM factor_definitions
            WHERE factor_code IN ('momentum_20d', 'reversal_3d', 'volatility_20d', 'amihud_5d')
            """,
        )
        pools = self._count(cursor, "SELECT COUNT(*) FROM stock_pools")
        pool_snapshots = self._count(
            cursor, "SELECT COUNT(*) FROM stock_pool_snapshots WHERE status = 'sealed'"
        )
        latest_pool = self._one(
            cursor,
            """
            SELECT id, pool_id, trade_date
            FROM stock_pool_snapshots
            WHERE status = 'sealed'
            ORDER BY trade_date DESC NULLS LAST, id DESC
            LIMIT 1
            """,
        )
        strategies = self._count(cursor, "SELECT COUNT(*) FROM strategy_scripts")
        versions = self._count(cursor, "SELECT COUNT(*) FROM strategy_versions")
        backtests = self._count(cursor, "SELECT COUNT(*) FROM backtest_runs")
        backtest_success = self._count(cursor, "SELECT COUNT(*) FROM backtest_runs WHERE status = 'success'")
        papers = self._count(cursor, "SELECT COUNT(*) FROM paper_instances")
        running_papers = self._count(
            cursor, "SELECT COUNT(*) FROM paper_instances WHERE status IN ('running', 'paused')"
        )
        reviews = self._count(cursor, "SELECT COUNT(*) FROM daily_reviews")
        latest_review = self._one(
            cursor,
            "SELECT id, trade_date, status FROM daily_reviews ORDER BY trade_date DESC NULLS LAST LIMIT 1",
        )
        active_strategy = self._one(
            cursor,
            """
            SELECT id, name, description, updated_at
            FROM strategy_scripts
            ORDER BY
                CASE WHEN name LIKE '%%多因子%%' THEN 0 ELSE 1 END,
                updated_at DESC NULLS LAST,
                id DESC
            LIMIT 1
            """,
        )
        strategy_version = None
        if active_strategy:
            strategy_version = self._one(
                cursor,
                """
                SELECT id, name, version, validation_status
                FROM strategy_versions
                WHERE legacy_strategy_id = %s
                ORDER BY version DESC NULLS LAST
                LIMIT 1
                """,
                (int(active_strategy["id"]),),
            )
        version_id = str(strategy_version["id"]) if strategy_version and strategy_version.get("id") else ""
        latest_backtest = self._one(
            cursor,
            """
            SELECT r.id, r.name, r.status, r.run_mode, r.promotion_status,
                   v.name AS strategy_name, r.start_date, r.end_date, r.created_at
            FROM backtest_runs r
            LEFT JOIN strategy_versions v ON v.id = r.strategy_version_id
            ORDER BY
                CASE WHEN %s <> '' AND r.strategy_version_id::text = %s THEN 0 ELSE 1 END,
                CASE WHEN COALESCE(v.name, r.name, '') LIKE '%%多因子%%' THEN 0 ELSE 1 END,
                r.created_at DESC NULLS LAST,
                r.id DESC
            LIMIT 1
            """,
            (version_id, version_id),
        )
        latest_paper = self._one(
            cursor,
            """
            SELECT id, name, status, created_at
            FROM paper_instances
            ORDER BY
                CASE WHEN %s <> '' AND strategy_version_id::text = %s THEN 0 ELSE 1 END,
                CASE WHEN name LIKE '%%多因子%%' THEN 0 ELSE 1 END,
                created_at DESC NULLS LAST,
                id DESC
            LIMIT 1
            """,
            (version_id, version_id),
        )

        raw_trade_date = _text((market or {}).get("trade_date") or (dataset or {}).get("knowledge_cutoff_at"))
        trade_date = raw_trade_date[:10] if raw_trade_date else None
        stages = [
            _stage("data", dataset_count, dataset_count > 0, f"{dataset_count} 个已封存数据快照"),
            _stage("market", 1 if market else 0, bool(market), f"证据日 {trade_date or '未封存'}"),
            _stage(
                "factors",
                factor_runs or factor_published or factor_defs,
                factor_runs > 0 or factor_published > 0,
                f"{factor_runs} 次计算 · {factor_defs} 个定义 · 链路因子 {factor_ready}/4"
                if factor_defs
                else "尚无因子定义",
                partial=factor_defs > 0 and factor_runs == 0,
            ),
            _stage(
                "pools",
                pool_snapshots or pools,
                pool_snapshots > 0,
                f"{pool_snapshots} 个封存快照 / {pools} 个股票池" if pools or pool_snapshots else "尚无股票池",
                partial=pools > 0 and pool_snapshots == 0,
            ),
            _stage(
                "strategy",
                strategies,
                versions > 0 or strategies > 0,
                f"{strategies} 个策略 · {versions} 个版本",
                partial=strategies > 0 and versions == 0,
            ),
            _stage(
                "backtest",
                backtests,
                backtest_success > 0,
                f"{backtest_success} 次成功 / {backtests} 次任务" if backtests else "尚无回测",
                partial=backtests > 0 and backtest_success == 0,
            ),
            _stage(
                "paper",
                papers,
                papers > 0,
                f"{running_papers} 个运行中 / {papers} 个实例" if papers else "尚无模拟实例",
                partial=False,
            ),
            _stage("watch", papers, papers > 0, "有 Paper 实例即可观察" if papers else "等待模拟实例"),
            _stage("monitor", papers, papers > 0, "绑定实例心跳与风险" if papers else "等待模拟实例"),
            _stage(
                "review",
                reviews,
                reviews > 0,
                f"最近复盘 { _text((latest_review or {}).get('trade_date')) or '无' }",
            ),
        ]
        return {
            "contract_version": "stockpro-research-desk-v1",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "trade_date": trade_date,
            "pipeline": stages,
            "active_strategy": _strategy(active_strategy),
            "latest_backtest": _backtest(latest_backtest),
            "latest_paper": _paper(latest_paper),
            "next_action": choose_next_action(stages, active_strategy),
            "bindings": {
                "factor_codes": list(PIPELINE_FACTOR_CODES),
                "factor_ready": factor_ready,
                "dataset_snapshot_id": int(dataset["id"]) if dataset and dataset.get("id") is not None else None,
                "pool_snapshot_id": int(latest_pool["id"]) if latest_pool and latest_pool.get("id") is not None else None,
                "pool_trade_date": _text((latest_pool or {}).get("trade_date")),
                "strategy_version_id": str(strategy_version["id"]) if strategy_version and strategy_version.get("id") else None,
                "strategy_version_status": (strategy_version or {}).get("validation_status"),
            },
        }

    def _fallback(self) -> Dict[str, Any]:
        stages = [_stage(item["id"], 0, False, "研究台计数暂不可用") for item in PIPELINE]
        return {
            "contract_version": "stockpro-research-desk-v1",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "trade_date": None,
            "pipeline": stages,
            "active_strategy": None,
            "latest_backtest": None,
            "latest_paper": None,
            "next_action": choose_next_action(stages),
            "bindings": {
                "factor_codes": list(PIPELINE_FACTOR_CODES),
                "factor_ready": 0,
                "dataset_snapshot_id": None,
                "pool_snapshot_id": None,
                "pool_trade_date": None,
                "strategy_version_id": None,
                "strategy_version_status": None,
            },
        }

    def _one(self, cursor, sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        try:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as exc:
            logger.warning("research desk query failed: %s", exc)
            try:
                cursor.connection.rollback()
            except Exception:
                pass
            return None

    def _count(self, cursor, sql: str, params: Sequence[Any] = ()) -> int:
        row = self._one(cursor, sql, params)
        if not row:
            return 0
        return int(next(iter(row.values())) or 0)


def _text(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())[:32]
    return str(value)[:32]


def _stage(
    stage_id: str,
    count: int,
    available: bool,
    detail: str,
    partial: bool = False,
) -> Dict[str, Any]:
    meta = next(item for item in PIPELINE if item["id"] == stage_id)
    status = "available" if available else "partial" if partial or count > 0 else "empty"
    return {
        "id": meta["id"],
        "label": meta["label"],
        "route": meta["route"],
        "status": status,
        "count": count,
        "detail": detail,
    }


def _strategy(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "name": str(row.get("name") or ""),
        "description": str(row.get("description") or ""),
        "updated_at": _text(row.get("updated_at")),
    }


def _backtest(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "id": str(row.get("id") or ""),
        "name": row.get("name"),
        "status": str(row.get("status") or ""),
        "run_mode": row.get("run_mode"),
        "promotion_status": row.get("promotion_status"),
        "strategy_name": row.get("strategy_name"),
        "start_date": _text(row.get("start_date")),
        "end_date": _text(row.get("end_date")),
    }


def _paper(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "id": str(row.get("id") or ""),
        "name": row.get("name"),
        "status": str(row.get("status") or ""),
    }
