from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from app.core.config import Settings, settings
from app.db.postgres_db import PostgresDatabase
from app.repositories.postgres_repository import PostgresRepository
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
    return AppContext(
        settings=runtime_settings,
        repositories=Repositories(health=repository, auth=repository, market=repository),
        clock=clock,
    )
