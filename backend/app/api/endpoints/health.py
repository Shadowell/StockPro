"""
健康检查和诊断端点
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from app.utils.dns_check import DNSChecker
from app.utils.dashscope_utils import DashScopeConfig, DashScopeConnectionManager
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", tags=["Health"])
async def health_check() -> Dict[str, str]:
    """
    基础健康检查
    """
    return {
        "status": "healthy",
        "message": "Application is running"
    }


@router.get("/health/dns-diagnostic", tags=["Health"])
async def dns_diagnostic() -> Dict[str, Any]:
    """
    DNS 诊断 - 检查 DashScope API 连接
    """
    try:
        results = DNSChecker.check_dashscope_connectivity()
        return {
            "status": "success" if results["summary"]["all_passed"] else "warning",
            "summary": results["summary"],
            "checks": {
                "dns": results["dns_checks"],
                "socket": results["socket_checks"],
                "http": results["http_checks"]
            }
        }
    except Exception as e:
        logger.error(f"诊断失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/dashscope-endpoint", tags=["Health"])
async def check_dashscope_endpoint() -> Dict[str, Any]:
    """
    检查可用的 DashScope 端点
    """
    try:
        # 获取或创建连接管理器
        from app.utils.dashscope_utils import get_connection_manager
        manager = get_connection_manager()
        
        # 获取可用端点
        working_endpoint = manager.get_working_endpoint(force_refresh=True)
        
        if working_endpoint:
            return {
                "status": "success",
                "working_endpoint": working_endpoint,
                "message": f"使用端点: {working_endpoint}"
            }
        else:
            return {
                "status": "error",
                "working_endpoint": None,
                "message": "没有可用的 DashScope 端点",
                "tested_endpoints": DashScopeConfig.API_ENDPOINTS
            }
    except Exception as e:
        logger.error(f"端点检查失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/report", tags=["Health"])
async def diagnostic_report() -> Dict[str, str]:
    """
    获取完整诊断报告（文本格式）
    """
    try:
        report = DNSChecker.get_diagnostic_report()
        return {
            "status": "success",
            "report": report
        }
    except Exception as e:
        logger.error(f"报告生成失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
