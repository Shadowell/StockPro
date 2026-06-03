from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from app.core.config import settings
from app.core.operation_allowlist import compile_allowlist, is_operation_allowed
from app.api import api_router
from app.db.postgres_migrations import apply_migrations
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Stock Analysis App",
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Startup event is defined later in the file
_ALWAYS_ALLOWED_OPERATIONS = compile_allowlist(
    [
        "GET /",
        "GET /docs",
        "GET /redoc",
        "GET /openapi.json",
        f"GET {settings.API_V1_STR}/openapi.json",
    ]
)
_CONFIG_ALLOWED_OPERATIONS = compile_allowlist(settings.OPERATION_ALLOWLIST)


def _legacy_sqlite_modules_enabled() -> bool:
    return settings.DB_MODE != "postgres" or settings.ENABLE_LEGACY_SQLITE_MODULES


@app.middleware("http")
async def operation_allowlist_middleware(request: Request, call_next):
    if not settings.ENFORCE_OPERATION_ALLOWLIST:
        return await call_next(request)

    allowlist = [*_ALWAYS_ALLOWED_OPERATIONS, *_CONFIG_ALLOWED_OPERATIONS]
    if is_operation_allowed(allowlist=allowlist, method=request.method, path=request.url.path):
        return await call_next(request)

    return JSONResponse(status_code=403, content={"detail": "Operation not allowed"})


# Set CORS enabled origins
allow_origins = (
    [str(origin) for origin in settings.BACKEND_CORS_ORIGINS]
    if settings.BACKEND_CORS_ORIGINS
    else ["http://localhost:4444", "http://127.0.0.1:4444"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up application...")
    if settings.DB_MODE == "postgres":
        applied = apply_migrations(settings.DATABASE_URL)
        logger.info("Postgres migrations applied: %s", applied or "none")
    else:
        from app.db.local_db import db_instance as db

        # 初始化数据库（创建表）
        db.init_db()
        logger.info("Database initialized")
        # 初始化预置策略模板
        db.init_preset_strategies()
        logger.info("Preset strategies initialized")

    legacy_services_enabled = _legacy_sqlite_modules_enabled()

    if settings.ENABLE_SCHEDULER and legacy_services_enabled:
        from app.services.scheduler_service import init_scheduler

        # 初始化并启动调度器
        await init_scheduler()
        logger.info("Scheduler started successfully")
    elif settings.ENABLE_SCHEDULER:
        logger.info("Scheduler skipped because legacy SQLite modules are disabled")
    else:
        logger.info("Scheduler disabled by config")

    if settings.ENABLE_REALTIME_SYNC and legacy_services_enabled:
        from app.services.realtime_sync_service import realtime_sync_service

        # 启动实时数据同步服务
        realtime_sync_service.start()
        logger.info("Realtime sync service started successfully")
    elif settings.ENABLE_REALTIME_SYNC:
        logger.info("Realtime sync service skipped because legacy SQLite modules are disabled")
    else:
        logger.info("Realtime sync service disabled by config")

    if settings.ENABLE_STRATEGY_EXECUTION and legacy_services_enabled:
        from app.services.strategy_execution_service import strategy_execution_service

        # 启动策略执行服务
        strategy_execution_service.start()
        logger.info("Strategy execution service started successfully")
    elif settings.ENABLE_STRATEGY_EXECUTION:
        logger.info("Strategy execution service skipped because legacy SQLite modules are disabled")
    else:
        logger.info("Strategy execution service disabled by config")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down application...")
    legacy_services_enabled = _legacy_sqlite_modules_enabled()

    if settings.ENABLE_REALTIME_SYNC and legacy_services_enabled:
        from app.services.realtime_sync_service import realtime_sync_service

        # 停止实时数据同步服务
        realtime_sync_service.stop()
        logger.info("Realtime sync service stopped")

    if settings.ENABLE_STRATEGY_EXECUTION and legacy_services_enabled:
        from app.services.strategy_execution_service import strategy_execution_service

        # 停止策略执行服务
        strategy_execution_service.stop()
        logger.info("Strategy execution service stopped")

@app.get("/")
def root():
    return {"message": "Welcome to Stock Analysis API"}
