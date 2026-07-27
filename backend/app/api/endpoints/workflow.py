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
                "status": "available",
                "write_access": False,
                "permissions": ["read", "backtest:run"],
                "reason": "访客可只读浏览，并在邀请码配额内运行回测",
            },
            {
                "id": "agent",
                "status": "available",
                "write_access": True,
                "permissions": ["R", "W"],
                "contract_version": "stockpro-mcp-v1",
                "real_broker_access": False,
            },
        ],
        "feature_gates": {
            "postgresql_read_model": {"status": "available"},
            "immutable_strategy_versions": {"status": "available"},
            "sealed_research_snapshots": {"status": "available"},
            "backtest_evidence": {"status": "available"},
            "guest_invite_access": {
                "status": "available",
                "storage": "postgresql",
                "plaintext_retention": False,
            },
            "guest_backtest_quota": {
                "status": "available",
                "dimensions": ["daily_runs", "concurrent_runs", "date_range_days"],
            },
            "async_backtest_jobs": {
                "status": "available",
                "storage": "postgresql",
                "controls": ["poll", "logs", "cancel", "retry"],
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
                "status": "available",
                "requires": ["strategy_version", "dataset_snapshot", "universe_snapshot", "cost_model"],
                "evidence": ["job_id", "run_id", "metrics", "orders", "trades", "logs"],
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
                "status": "available",
                "requires": ["paper_instance"],
                "evidence": ["signals", "orders", "trades", "positions", "risk_events", "alerts"],
            },
            {
                "id": "monitor",
                "label": "监控",
                "route": "/monitor",
                "status": "available",
                "requires": ["paper_instance", "service_health"],
                "evidence": ["instance_heartbeat", "latest_cycle", "equity", "drawdown", "risk_alerts", "notifications"],
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
