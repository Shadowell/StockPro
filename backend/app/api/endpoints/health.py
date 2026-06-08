"""
健康检查和诊断端点。
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.db.postgres_migrations import load_migrations, psycopg
from app.utils.dashscope_utils import DashScopeConfig
from app.utils.dns_check import DNSChecker

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", tags=["Health"])
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "message": "Application is running"}


@router.get("/storage", tags=["Health"])
async def storage_health_check() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": "healthy",
        "database": "postgres",
        "migration_files": len(load_migrations()),
    }

    if not settings.DATABASE_URL:
        return {**result, "status": "error", "message": "DATABASE_URL is required"}

    try:
        with psycopg.connect(settings.DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM schema_migrations")
                row = cursor.fetchone()
        return {**result, "applied_migrations": int(row[0]) if row else 0}
    except Exception as e:
        logger.error("Storage health check failed: %s", e)
        return {**result, "status": "error", "message": str(e)}


@router.get("/dns-diagnostic", tags=["Health"])
async def dns_diagnostic() -> Dict[str, Any]:
    try:
        results = DNSChecker.check_dashscope_connectivity()
        return {
            "status": "success" if results["summary"]["all_passed"] else "warning",
            "summary": results["summary"],
            "checks": {
                "dns": results["dns_checks"],
                "socket": results["socket_checks"],
                "http": results["http_checks"],
            },
        }
    except Exception as e:
        logger.error("诊断失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashscope-endpoint", tags=["Health"])
async def check_dashscope_endpoint() -> Dict[str, Any]:
    try:
        from app.utils.dashscope_utils import get_connection_manager

        manager = get_connection_manager()
        working_endpoint = manager.get_working_endpoint(force_refresh=True)

        if working_endpoint:
            return {
                "status": "success",
                "working_endpoint": working_endpoint,
                "message": f"使用端点: {working_endpoint}",
            }
        return {
            "status": "error",
            "working_endpoint": None,
            "message": "没有可用的 DashScope 端点",
            "tested_endpoints": DashScopeConfig.API_ENDPOINTS,
        }
    except Exception as e:
        logger.error("端点检查失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report", tags=["Health"])
async def diagnostic_report() -> Dict[str, str]:
    return {
        "status": "success",
        "message": "Diagnostics are available at /health/dns-diagnostic and /health/dashscope-endpoint",
    }
