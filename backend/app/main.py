"""
BitPro - 加密货币量化交易平台
主应用入口
"""
# 最先加载 .env，确保所有模块都能读到环境变量
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
import asyncio
import logging

from app.core.config import settings
from app.api import api_router_v2
from app.api.public import router as public_api_router
from app.core.auth_middleware import AuthMiddleware
from app.core.errors import register_exception_handlers
from app.db.local_db import db_instance as db
from app.mcp.server import mount_remote_mcp

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("Starting BitPro application...")
    
    # 初始化数据库
    db.init_db()
    logger.info("Database initialized")

    from app.services.factorlab_service import factorlab_service

    factorlab_service.bootstrap()
    logger.info("FactorLab catalog initialized")

    if settings.BITPRO_AUTH_ENABLED:
        from app.services.auth_service import auth_service

        auth_service.validate_admin_config(
            enabled=True,
            username=settings.BITPRO_ADMIN_USERNAME,
            password_hash=settings.BITPRO_ADMIN_PASSWORD_HASH,
        )
        logger.info("Authentication enabled")

    # 上次进程异常退出或部署重启时，运行中的回测任务无法继续，标记为中断并保留最后进度
    try:
        conn = db.get_connection()
        conn.execute(
            """
            UPDATE backtest_jobs
            SET status = 'interrupted',
                message = '服务重启，回测已中断（最后进度已保留）',
                updated_at = datetime('now')
            WHERE status IN ('pending', 'running', 'cancelling')
            """
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("backtest_jobs interrupt sweep skipped: %s", e)

    # 上次进程异常退出或部署重启时，AI Lab 后台研发任务无法继续在内存中运行；
    # 将它们标记为 interrupted，但保留已完成的 Planner/迭代/候选策略记录。
    interrupted_agent_at = datetime.now().isoformat()
    interrupted_agent_count = 0
    try:
        interrupted_agent_count = db.mark_interrupted_agent_tasks(interrupted_agent_at)
        count = interrupted_agent_count
        if count:
            logger.info("Marked %d AI Lab task(s) as interrupted after restart", count)
    except Exception as e:
        logger.warning("agent_tasks interrupt sweep skipped: %s", e)

    try:
        from app.services.strategy_optimizer_service import strategy_optimizer_service

        recovered_optimizer = strategy_optimizer_service.recover_interrupted_runs()
        failed_optimizer_runs = recovered_optimizer.get("failed_runs") or []
        if failed_optimizer_runs:
            logger.info(
                "Marked %d AI strategy optimizer run(s) as interrupted after restart",
                len(failed_optimizer_runs),
            )
    except Exception as e:
        logger.warning("strategy optimizer interrupt sweep skipped: %s", e)
    
    # 初始化交易所连接
    from app.exchange import exchange_manager
    exchange_manager.init_exchanges()
    logger.info("Exchange connections initialized")

    # 恢复服务重启前未完成的数据同步任务。同步进度和 checkpoint 已持久化到 SQLite。
    try:
        from app.services.data_sync_service import data_sync_service

        resumed_sync_jobs = data_sync_service.schedule_resume_incomplete_jobs()
        if resumed_sync_jobs:
            logger.info("Scheduled %d interrupted data sync job(s) for resume", resumed_sync_jobs)
    except Exception as e:
        logger.warning("data sync auto-resume scheduling skipped: %s", e)
    
    # 启动 WebSocket 实时数据服务
    from app.services.websocket_service import realtime_service
    await realtime_service.start()
    logger.info("WebSocket realtime service started")
    
    # 启动策略执行引擎
    from app.services.strategy_engine import strategy_engine
    await strategy_engine.start()
    logger.info("Strategy engine started")
    
    # 启动告警服务
    from app.services.alert_service import alert_service
    await alert_service.start()
    logger.info("Alert service started")
    
    # 启动定时调度服务（每日数据同步等）
    from app.services.scheduler_service import scheduler_service
    await scheduler_service.start()
    logger.info("Scheduler service started")

    if interrupted_agent_count:
        try:
            from app.api.v2.endpoints.agent import auto_resume_interrupted_agent_tasks

            asyncio.create_task(auto_resume_interrupted_agent_tasks(interrupted_agent_at))
        except Exception as e:
            logger.warning("AI Lab auto-resume scheduling skipped: %s", e)

    try:
        from app.api.v2.endpoints.agent import auto_resume_auto_agent_research_runs

        asyncio.create_task(auto_resume_auto_agent_research_runs())
    except Exception as e:
        logger.warning("Auto-agent research auto-resume scheduling skipped: %s", e)
    
    yield
    
    # 关闭时
    logger.info("Shutting down BitPro application...")
    
    # 停止定时调度服务
    await scheduler_service.stop()
    
    # 停止告警服务
    await alert_service.stop()
    
    # 停止策略引擎（不将策略标为 stopped，重启后可按 DB running 自动恢复）
    await strategy_engine.stop()
    
    # 停止实时数据服务
    await realtime_service.stop()


# ============================================
# 请求限流中间件
# 保护交易所 API 不被前端频繁请求打穿
# ============================================

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    简易令牌桶限流
    - 全局: 60 请求/秒
    - 交易接口: 10 请求/秒
    """
    
    def __init__(self, app, global_rate: int = 60, trade_rate: int = 10):
        super().__init__(app)
        self._global_tokens = global_rate
        self._global_max = global_rate
        self._trade_tokens = trade_rate
        self._trade_max = trade_rate
        self._last_refill = 0.0
    
    async def dispatch(self, request: Request, call_next):
        import time
        now = time.time()
        
        # 令牌补充 (每秒补满) — 单进程下无需加锁，asyncio 是单线程的
        elapsed = now - self._last_refill
        if elapsed >= 1.0:
            self._global_tokens = self._global_max
            self._trade_tokens = self._trade_max
            self._last_refill = now
        
        path = request.url.path
        
        # 交易/控制类接口限流。/live 的 GET 详情、事件、权益曲线只读且用于页面首屏，
        # 不应和 start/stop/configure 等写操作共用交易限流桶，否则多卡片并发加载会误报 429。
        is_write = request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
        is_trade_path = (
            '/trading/' in path
            or '/auto-trade/' in path
            or ('/live/' in path and is_write)
        )
        if is_trade_path:
            if self._trade_tokens <= 0:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "交易接口请求频率过高，请稍后再试"}
                )
            self._trade_tokens -= 1
        
        # 全局限流
        if path.startswith('/api/'):
            if self._global_tokens <= 0:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求频率过高，请稍后再试"}
                )
            self._global_tokens -= 1
        
        return await call_next(request)


# ============================================
# 应用注册
# ============================================

# 创建应用
app = FastAPI(
    title="BitPro API",
    description="加密货币量化交易平台 API",
    version="1.0.0",
    openapi_url="/api/v2/openapi.json",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求限流
app.add_middleware(RateLimitMiddleware, global_rate=60, trade_rate=10)
app.add_middleware(AuthMiddleware)

# 注册路由
app.include_router(api_router_v2, prefix="/api/v2")
app.include_router(public_api_router, prefix="/api/public/v1")
if mount_remote_mcp(app):
    logger.info("Remote MCP streamable-http mounted at %s", settings.BITPRO_REMOTE_MCP_PATH)

# 注册全局异常处理
register_exception_handlers(app)


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "欢迎使用 BitPro API",
        "docs": "/docs",
        "version": "2.0.0",
        "v2": "/api/v2",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8889,
        reload=True
    )
