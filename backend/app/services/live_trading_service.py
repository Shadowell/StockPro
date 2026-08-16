"""A 股实盘工作台服务：预检、晋级管线与审计。

诚实边界：本服务不发送真实委托。所有 enable 请求都会留痕；
只有在 LIVE_TRADING_ENABLED 打开且券商通道（如 miniQMT）可用时，
才会进入 pending_broker_binding 状态等待显式绑定。
"""
from __future__ import annotations

import hashlib
import importlib.util
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg2.extras

from app.core.config import settings
from app.services.backtest_workbench_service import PAPER_PROMOTION_CHECK_CODES

logger = logging.getLogger(__name__)

_CANDIDATE_METRIC_CODES = (
    "strategy_return", "sharpe", "maximum_drawdown", "win_rate",
    "profit_loss_ratio", "completed_trades", "excess_return",
)


class LiveTradingService:
    def __init__(self, database):
        self.database = database

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        adapters = [
            {
                "key": "miniqmt",
                "name": "QMT / miniQMT（迅投 xtquant）",
                "available": importlib.util.find_spec("xtquant") is not None,
                "configured": bool(getattr(settings, "LIVE_MINIQMT_ENABLED", False)),
                "note": "券商量化终端本地库；需在券商侧开通量化权限并安装 xtquant",
            },
            {
                "key": "ptrade",
                "name": "PTrade（恒生）",
                "available": importlib.util.find_spec("ptrade") is not None,
                "configured": bool(getattr(settings, "LIVE_PTRADE_ENABLED", False)),
                "note": "券商托管量化平台；需在券商侧开通并托管策略",
            },
        ]
        return {
            "trading_enabled": bool(getattr(settings, "LIVE_TRADING_ENABLED", False)),
            "boundary_note": (
                "实盘工作台当前只提供预检、晋级管线与审计留痕；真实委托需要券商量化通道"
                "（QMT/miniQMT 或 PTrade）配置并通过 LIVE_TRADING_ENABLED 显式开启。"
            ),
            "adapters": adapters,
            "risk_limits": {
                "max_single_order_value": getattr(settings, "LIVE_MAX_SINGLE_ORDER_VALUE", None),
                "max_position_weight": getattr(settings, "LIVE_MAX_POSITION_WEIGHT", None),
                "max_daily_loss_ratio": getattr(settings, "LIVE_MAX_DAILY_LOSS_RATIO", None),
            },
        }

    # ------------------------------------------------------------------
    # 晋级候选
    # ------------------------------------------------------------------
    def promotion_candidates(self) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        runs = self._rows(
            """
            SELECT r.id, r.name, r.strategy_version_id, r.promotion_status, r.metrics, r.run_mode,
                   r.status, v.name AS strategy_name, v.version AS strategy_version,
                   (SELECT COUNT(*) FROM backtest_promotion_checks pc
                    WHERE pc.backtest_run_id = r.id AND pc.status='passed'
                      AND pc.check_code = ANY(%s)) AS passed_gate_count
            FROM backtest_runs r
            LEFT JOIN strategy_versions v ON v.id = r.strategy_version_id
            WHERE r.run_mode='full' AND r.status='success' AND r.promotion_status='paper_eligible'
            ORDER BY r.created_at DESC LIMIT 20
            """,
            (list(PAPER_PROMOTION_CHECK_CODES),),
        )
        for run in runs:
            candidates.append({
                "kind": "backtest_run",
                "id": str(run["id"]),
                "name": str(run.get("name") or run.get("strategy_name") or "完整回测"),
                "strategy_version_id": str(run["strategy_version_id"]) if run.get("strategy_version_id") else None,
                "promotion_status": run.get("promotion_status"),
                "metrics": self._metric_subset(run.get("metrics") or {}),
                "detail": {
                    "strategy_name": run.get("strategy_name"),
                    "strategy_version": run.get("strategy_version"),
                    "passed_gate_count": int(run.get("passed_gate_count") or 0),
                    "gate_total": len(PAPER_PROMOTION_CHECK_CODES),
                },
            })
        instances = self._rows(
            """
            SELECT id, name, status, strategy_version_id,
                   parameters->>'initial_cash' AS initial_cash,
                   created_at, last_processed_trade_date
            FROM paper_instances
            WHERE status IN ('running', 'paused')
            ORDER BY created_at DESC LIMIT 20
            """
        )
        for instance in instances:
            candidates.append({
                "kind": "paper_instance",
                "id": str(instance["id"]),
                "name": str(instance.get("name") or "Paper 实例"),
                "strategy_version_id": str(instance["strategy_version_id"]) if instance.get("strategy_version_id") else None,
                "promotion_status": None,
                "metrics": {},
                "detail": {
                    "status": instance.get("status"),
                    "initial_cash": float(instance.get("initial_cash") or 0),
                    "created_at": str(instance.get("created_at") or ""),
                    "last_cycle_at": str(instance.get("last_processed_trade_date") or ""),
                },
            })
        return candidates

    # ------------------------------------------------------------------
    # 预检
    # ------------------------------------------------------------------
    def preflight(self, candidate_kind: str, candidate_id: str) -> Dict[str, Any]:
        if candidate_kind not in {"backtest_run", "paper_instance"}:
            raise ValueError("candidate_kind 只能为 backtest_run 或 paper_instance")
        candidate = self._candidate(candidate_kind, candidate_id)
        if not candidate:
            raise ValueError("晋级候选不存在")
        status = self.status()
        checks: List[Dict[str, Any]] = []

        adapter_ready = any(item["available"] and item["configured"] for item in status["adapters"])
        adapter_available = any(item["available"] for item in status["adapters"])
        checks.append({
            "check_code": "BROKER_ADAPTER",
            "title": "券商通道已安装并配置",
            "status": "passed" if adapter_ready else ("warning" if adapter_available else "failed"),
            "reason": None if adapter_ready else (
                "检测到本机已安装量化库但未配置开启" if adapter_available else "未检测到 QMT/miniQMT 或 PTrade 通道"
            ),
        })
        checks.append({
            "check_code": "LIVE_TRADING_ENABLED",
            "title": "实盘开关 LIVE_TRADING_ENABLED 已显式开启",
            "status": "passed" if status["trading_enabled"] else "failed",
            "reason": None if status["trading_enabled"] else "实盘总开关未开启，系统不会发出真实委托",
        })

        if candidate_kind == "backtest_run":
            gate_count = int((candidate.get("detail") or {}).get("passed_gate_count") or 0)
            gate_ok = gate_count >= len(PAPER_PROMOTION_CHECK_CODES)
            checks.append({
                "check_code": "PROMOTION_GATE",
                "title": f"研究晋级门控 11 项全部通过（{gate_count}/{len(PAPER_PROMOTION_CHECK_CODES)}）",
                "status": "passed" if gate_ok else "failed",
                "reason": None if gate_ok else "存在未通过的晋级检查，不能进入实盘",
            })
        else:
            checks.append({
                "check_code": "PAPER_INSTANCE_ACTIVE",
                "title": "Paper 实例处于运行或暂停状态",
                "status": "passed" if (candidate.get("detail") or {}).get("status") in {"running", "paused"} else "failed",
                "reason": None,
            })

        risk_limits = status["risk_limits"]
        limits_defined = all(value is not None for value in risk_limits.values())
        checks.append({
            "check_code": "RISK_LIMITS_DEFINED",
            "title": "实盘风控限额（单笔金额/仓位/日内亏损）已定义",
            "status": "passed" if limits_defined else "failed",
            "reason": None if limits_defined else "请在后端配置 LIVE_MAX_SINGLE_ORDER_VALUE 等风控限额",
        })

        weekday = datetime.now().isoweekday()
        checks.append({
            "check_code": "TRADING_SESSION",
            "title": "当前处于 A 股交易日委托时段（提示项）",
            "status": "passed" if weekday <= 5 else "warning",
            "reason": None if weekday <= 5 else "当前为周末；A 股仅交易日 09:30-15:00（午间休市）接受委托",
        })

        deployable = all(item["status"] != "failed" for item in checks)
        result = {
            "candidate": candidate,
            "checks": checks,
            "deployable": deployable,
            "confirm_token": self._confirm_token(candidate_kind, candidate_id) if deployable else None,
        }
        self._record_event(
            "preflight", candidate_kind, candidate_id,
            "passed" if deployable else "failed",
            {"checks": [{k: item[k] for k in ("check_code", "status")} for item in checks]},
        )
        return result

    # ------------------------------------------------------------------
    # 晋级请求（留痕；未配置通道时拒绝）
    # ------------------------------------------------------------------
    def request_enable(self, candidate_kind: str, candidate_id: str, confirm_token: str, confirmed: bool) -> Dict[str, Any]:
        if candidate_kind not in {"backtest_run", "paper_instance"}:
            raise ValueError("candidate_kind 只能为 backtest_run 或 paper_instance")
        if not confirmed:
            return self._reject(candidate_kind, candidate_id, "missing_double_confirm", "未完成双重确认")
        if not confirm_token or confirm_token != self._confirm_token(candidate_kind, candidate_id):
            return self._reject(candidate_kind, candidate_id, "invalid_confirm_token", "确认令牌无效，请重新执行预检")
        preflight_result = self.preflight(candidate_kind, candidate_id)
        if not preflight_result["deployable"]:
            return {
                "accepted": False,
                "status": "rejected",
                "reason": "预检未通过：" + "；".join(
                    item["title"] for item in preflight_result["checks"] if item["status"] == "failed"
                ),
                "event_id": None,
            }
        status = self.status()
        adapter_ready = any(item["available"] and item["configured"] for item in status["adapters"])
        if not status["trading_enabled"] or not adapter_ready:
            event_id = self._record_event(
                "enable_request", candidate_kind, candidate_id, "blocked",
                {"reason": "券商通道或实盘开关未就绪，请求已被安全拦截并留痕"},
            )
            return {
                "accepted": False,
                "status": "blocked",
                "reason": "券商通道或实盘开关未就绪：请求已记录，不会发出真实委托。请在配置 QMT/miniQMT 并开启 LIVE_TRADING_ENABLED 后重试。",
                "event_id": event_id,
            }
        event_id = self._record_event(
            "enable_request", candidate_kind, candidate_id, "pending_broker_binding",
            {"reason": "预检通过，等待券商通道绑定与人工复核"},
        )
        return {
            "accepted": True,
            "status": "pending_broker_binding",
            "reason": "预检通过，已进入券商通道绑定队列；绑定完成前不会发出任何委托。",
            "event_id": event_id,
        }

    def list_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._rows(
            "SELECT * FROM live_trading_events ORDER BY created_at DESC LIMIT %s",
            (max(1, min(int(limit), 200)),),
        )

    # ------------------------------------------------------------------
    def _candidate(self, candidate_kind: str, candidate_id: str) -> Optional[Dict[str, Any]]:
        for item in self.promotion_candidates():
            if item["kind"] == candidate_kind and item["id"] == str(candidate_id):
                return item
        return None

    def _reject(self, candidate_kind: str, candidate_id: str, code: str, reason: str) -> Dict[str, Any]:
        event_id = self._record_event("enable_request", candidate_kind, candidate_id, "rejected", {"code": code, "reason": reason})
        return {"accepted": False, "status": "rejected", "reason": reason, "event_id": event_id}

    @staticmethod
    def _confirm_token(candidate_kind: str, candidate_id: str) -> str:
        return hashlib.sha256(f"live-deploy:{candidate_kind}:{candidate_id}".encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _metric_subset(metrics: Dict[str, Any]) -> Dict[str, Any]:
        return {code: metrics.get(code) for code in _CANDIDATE_METRIC_CODES}

    def _record_event(self, event_type: str, candidate_kind: str, candidate_id: str, status: str, detail: Dict[str, Any]) -> str:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO live_trading_events (event_type, candidate_kind, candidate_id, status, detail)
                    VALUES (%s,%s,%s,%s,%s) RETURNING id
                    """,
                    (event_type, candidate_kind, str(candidate_id), status, psycopg2.extras.Json(detail)),
                )
                return str(cursor.fetchone()[0])

    def _rows(self, query: str, params: Any = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(item) for item in cursor.fetchall()]
