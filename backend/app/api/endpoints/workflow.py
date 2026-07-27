from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

from app.core.config import settings


router = APIRouter()


@router.get("/capabilities")
async def workflow_capabilities() -> Dict[str, Any]:
    """Describe the supported StockPro operator lifecycle without implying runtime data availability."""
    return {
        "contract_version": "stockpro-workflow-v1",
        "behavioral_baseline": "bitpro",
        "execution_scope": "paper_only",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "auth_modes": [
            {"id": "admin", "status": "available", "write_access": True},
            {
                "id": "guest",
                "status": "not_implemented",
                "write_access": False,
                "reason": "访客邀请码与回测配额尚未实现",
            },
            {
                "id": "agent",
                "status": "not_implemented",
                "write_access": False,
                "reason": "stockpro-mcp-v1 尚未实现",
            },
        ],
        "feature_gates": {
            "postgresql_read_model": {"status": "available"},
            "immutable_strategy_versions": {"status": "available"},
            "sealed_research_snapshots": {"status": "available"},
            "backtest_evidence": {"status": "available"},
            "async_backtest_jobs": {
                "status": "not_implemented",
                "reason": "当前完整回测仍是同步请求",
            },
            "paper_runtime": {"status": "available"},
            "real_broker": {
                "status": "not_implemented",
                "enabled": False,
                "reason": "真实券商接入需要独立安全合同与明确授权",
            },
            "scheduler_runtime": {
                "status": "available" if settings.ENABLE_SCHEDULER else "disabled",
                "enabled": settings.ENABLE_SCHEDULER,
            },
            "external_market_fetch": {
                "status": "available" if settings.ENABLE_EXTERNAL_MARKET_FETCH else "disabled",
                "enabled": settings.ENABLE_EXTERNAL_MARKET_FETCH,
            },
        },
        "domain_guardrails": [
            "A股交易日历与交易时段",
            "默认只做多",
            "T+1 可卖约束",
            "100 股整数手",
            "涨跌停、停牌与 ST 约束",
            "公司行动与复权口径",
            "佣金、印花税、过户费与滑点",
        ],
        "stages": [
            {
                "id": "strategy",
                "label": "策略",
                "route": "/strategy",
                "status": "available",
                "requires": ["sealed_dataset_snapshot", "strategy_version"],
                "evidence": ["content_hash", "api_version", "validation"],
            },
            {
                "id": "backtest",
                "label": "回测",
                "route": "/backtest",
                "status": "partial",
                "requires": ["strategy_version", "dataset_snapshot", "universe_snapshot", "cost_model"],
                "evidence": ["run_id", "metrics", "orders", "trades", "logs"],
                "reason": "结果证据可用，异步任务控制尚未实现",
            },
            {
                "id": "paper",
                "label": "模拟",
                "route": "/paper",
                "status": "available",
                "requires": ["accepted_backtest", "promotion_decision", "paper_configuration"],
                "evidence": ["instance_id", "events", "orders", "positions"],
            },
            {
                "id": "watch",
                "label": "观察",
                "route": "/watch",
                "status": "partial",
                "requires": ["paper_instance"],
                "evidence": ["runtime_context", "alerts"],
                "reason": "尚未形成完整订单与成交观察模型",
            },
            {
                "id": "monitor",
                "label": "监控",
                "route": "/monitor",
                "status": "partial",
                "requires": ["paper_instance", "service_health"],
                "evidence": ["health", "risk_alerts", "notifications"],
                "reason": "运行健康可见，策略级风险控制仍需补齐",
            },
            {
                "id": "review",
                "label": "复盘",
                "route": "/review",
                "status": "available",
                "requires": ["trade_date", "runtime_evidence"],
                "evidence": ["review_snapshot", "object_lineage", "seal_status"],
            },
        ],
    }
