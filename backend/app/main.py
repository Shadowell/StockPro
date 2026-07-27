import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.operation_allowlist import compile_allowlist, is_operation_allowed
from app.db import db_instance
from app.db.postgres_migrations import apply_migrations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
)

_ALWAYS_ALLOWED_OPERATIONS = compile_allowlist(
    [
        "GET /",
        "GET /docs",
        "GET /redoc",
        "GET /openapi.json",
        f"GET {settings.API_PREFIX}/openapi.json",
        f"GET {settings.API_PREFIX}/health/health",
        f"GET {settings.API_PREFIX}/health/storage",
        f"POST {settings.API_PREFIX}/auth/admin/login",
    ]
)
_CONFIG_ALLOWED_OPERATIONS = compile_allowlist(settings.OPERATION_ALLOWLIST)


@app.middleware("http")
async def operation_allowlist_middleware(request: Request, call_next):
    if not settings.ENFORCE_OPERATION_ALLOWLIST:
        return await call_next(request)

    allowlist = [*_ALWAYS_ALLOWED_OPERATIONS, *_CONFIG_ALLOWED_OPERATIONS]
    if is_operation_allowed(allowlist=allowlist, method=request.method, path=request.url.path):
        return await call_next(request)

    return JSONResponse(status_code=403, content={"detail": "Operation not allowed"})


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

app.include_router(api_router, prefix=settings.API_PREFIX)


@app.on_event("startup")
async def startup_event():
    logger.info("Starting up application...")
    if settings.RUN_MIGRATIONS_ON_STARTUP:
        applied = apply_migrations(settings.DATABASE_URL)
        logger.info("Postgres migrations applied: %s", applied or "none")
    else:
        logger.info("Postgres migrations skipped; run backend/apply_migration.py explicitly")

    if settings.RUN_BOOTSTRAP_ON_STARTUP:
        from app.services.tushare_catalog_service import TushareCatalogService
        from app.services.dataset_snapshot_service import DatasetSnapshotService

        catalog_count = TushareCatalogService(db_instance).install_catalog()
        dataset_count = DatasetSnapshotService(db_instance).install_registry()
        db_instance.init_preset_strategies()
        logger.info("Runtime bootstrap completed: %s endpoints, %s datasets", catalog_count, dataset_count)
    else:
        logger.info("Runtime bootstrap skipped; run backend/bootstrap_runtime.py explicitly")

    if settings.RUN_PAPER_RECOVERY_ON_STARTUP:
        from app.services.paper_runtime_service import PaperRuntimeService

        recovered = PaperRuntimeService(db_instance).recover_instances()
        logger.info(
            "Paper runtime recovery completed: %s instance(s), %s interrupted cycle(s)",
            recovered["restored"],
            recovered["interrupted_cycles"],
        )
    else:
        logger.info("Paper runtime recovery skipped by config")

    if settings.ENABLE_SCHEDULER:
        from app.services.scheduler_service import init_scheduler

        await init_scheduler()
        logger.info("Scheduler started successfully")
    else:
        logger.info("Scheduler disabled by config")

    if settings.ENABLE_REALTIME_SYNC:
        from app.services.realtime_sync_service import realtime_sync_service

        realtime_sync_service.start()
        logger.info("Realtime sync service started successfully")
    else:
        logger.info("Realtime sync service disabled by config")

    if settings.ENABLE_STRATEGY_EXECUTION:
        from app.services.strategy_execution_service import strategy_execution_service

        strategy_execution_service.start()
        logger.info("Strategy execution service started successfully")
    else:
        logger.info("Strategy execution service disabled by config")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down application...")

    if settings.ENABLE_REALTIME_SYNC:
        from app.services.realtime_sync_service import realtime_sync_service

        realtime_sync_service.stop()
        logger.info("Realtime sync service stopped")

    if settings.ENABLE_STRATEGY_EXECUTION:
        from app.services.strategy_execution_service import strategy_execution_service

        strategy_execution_service.stop()
        logger.info("Strategy execution service stopped")


@app.get("/")
def root():
    return {"message": "Welcome to Stock Analysis API"}
