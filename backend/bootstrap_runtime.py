"""Explicit, idempotent local database/bootstrap entrypoint."""
from __future__ import annotations

import argparse

from app.core.config import settings
from app.db import db_instance
from app.db.postgres_migrations import apply_migrations
from app.services.dataset_snapshot_service import DatasetSnapshotService
from app.services.paper_runtime_service import PaperRuntimeService
from app.services.tushare_catalog_service import TushareCatalogService


def bootstrap(*, recover_paper: bool = False) -> dict[str, int]:
    applied = apply_migrations(settings.DATABASE_URL)
    catalog_count = TushareCatalogService(db_instance).install_catalog()
    dataset_count = DatasetSnapshotService(db_instance).install_registry()
    db_instance.init_preset_strategies()
    recovery = PaperRuntimeService(db_instance).recover_instances() if recover_paper else {"restored": 0, "interrupted_cycles": 0}
    return {
        "migrations": len(applied),
        "catalogue_endpoints": catalog_count,
        "research_datasets": dataset_count,
        "paper_instances": int(recovery["restored"]),
        "interrupted_cycles": int(recovery["interrupted_cycles"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap StockPro local runtime state explicitly")
    parser.add_argument("--recover-paper", action="store_true", help="Fail interrupted Paper cycles and append recovery evidence")
    args = parser.parse_args()
    result = bootstrap(recover_paper=args.recover_paper)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
