from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from app.core.config import Settings, settings
from app.db.postgres_db import PostgresDatabase
from app.repositories.postgres_repository import PostgresRepository
from app.repositories.pool_repository import PostgresPoolRepository
from app.repositories.factor_repository import PostgresFactorRepository
from app.repositories.strategy_repository import PostgresStrategyRepository
from app.repositories.backtest_repository import PostgresBacktestRepository
from app.repositories.protocols import Repositories


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    repositories: Repositories
    clock: Callable[[], datetime]


def build_app_context(
    app_settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> AppContext:
    runtime_settings = app_settings or settings
    database = PostgresDatabase(runtime_settings.DATABASE_URL)
    repository = PostgresRepository(database)
    pool_repository = PostgresPoolRepository(database)
    factor_repository = PostgresFactorRepository(database)
    strategy_repository = PostgresStrategyRepository(database)
    backtest_repository = PostgresBacktestRepository(database)
    return AppContext(
        settings=runtime_settings,
        repositories=Repositories(
            health=repository,
            auth=repository,
            market=repository,
            pools=pool_repository,
            factors=factor_repository,
            strategies=strategy_repository,
            backtests=backtest_repository,
        ),
        clock=clock,
    )
