#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol


SCHEMA_VERSION = "stockpro-rebuild-baseline"
COUNT_TABLES = (
    "schema_migrations",
    "strategy_versions",
    "backtest_runs",
    "paper_instances",
    "portfolios",
    "orders",
    "trades",
    "positions",
    "paper_equity_snapshots",
    "paper_instance_events",
    "daily_reviews",
)


class BaselineRepository(Protocol):
    def fetch_all(self, query: str) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class RebuildBaseline:
    schema_version: str
    captured_at: str
    repository: dict[str, str]
    counts: dict[str, int]
    schema_migrations: list[str]
    paper: dict[str, object]
    manifest_hash: str


class PostgresBaselineRepository:
    """Minimal PostgreSQL reader forced into a read-only transaction."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        import psycopg

        self._connection = psycopg.connect(
            database_url,
            options="-c default_transaction_read_only=on",
        )

    def fetch_all(self, query: str) -> list[dict[str, object]]:
        if not query.lstrip().lower().startswith("select"):
            raise ValueError("baseline repository accepts SELECT statements only")
        from psycopg.rows import dict_row

        with self._connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        self._connection.rollback()
        self._connection.close()


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def canonical_hash(payload: dict[str, object]) -> str:
    hashable = {
        key: value
        for key, value in payload.items()
        if key not in {"captured_at", "manifest_hash"}
    }
    encoded = json.dumps(
        _json_value(hashable),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return result.stdout.strip() or "unavailable"


def _single_count(repository: BaselineRepository, query: str) -> int:
    rows = repository.fetch_all(query)
    if len(rows) != 1 or "count" not in rows[0]:
        raise RuntimeError(f"count query returned an unexpected shape: {query}")
    return int(rows[0]["count"])


def read_continuity_manifest(
    repository: BaselineRepository,
    repo_root: Path,
    *,
    captured_at: str,
) -> dict[str, object]:
    counts = {
        table: _single_count(repository, f"SELECT COUNT(*)::integer AS count FROM {table}")
        for table in COUNT_TABLES
    }
    migration_rows = repository.fetch_all(
        "SELECT version FROM schema_migrations ORDER BY version"
    )
    instances = repository.fetch_all(
        """
        SELECT
            i.id::text AS instance_id,
            i.name,
            i.status,
            i.strategy_version_id::text AS strategy_version_id,
            i.qualifying_backtest_run_id::text AS qualifying_backtest_run_id,
            i.portfolio_id::text AS portfolio_id,
            p.initial_cash,
            p.cash_balance,
            i.started_at,
            i.created_at,
            (SELECT COUNT(*) FROM orders o WHERE o.paper_instance_id=i.id)::integer AS order_count,
            (SELECT COUNT(*) FROM trades t WHERE t.paper_instance_id=i.id)::integer AS trade_count,
            (SELECT COUNT(*) FROM positions pos WHERE pos.portfolio_id=i.portfolio_id)::integer AS position_count,
            (SELECT COUNT(*) FROM paper_equity_snapshots pe WHERE pe.paper_instance_id=i.id)::integer AS equity_sample_count,
            (SELECT COUNT(*) FROM paper_instance_events ev WHERE ev.paper_instance_id=i.id)::integer AS event_count,
            (SELECT pe.equity FROM paper_equity_snapshots pe WHERE pe.paper_instance_id=i.id ORDER BY pe.trade_date,pe.id LIMIT 1) AS first_equity,
            (SELECT pe.equity FROM paper_equity_snapshots pe WHERE pe.paper_instance_id=i.id ORDER BY pe.trade_date DESC,pe.id DESC LIMIT 1) AS last_equity,
            (SELECT pe.trade_date FROM paper_equity_snapshots pe WHERE pe.paper_instance_id=i.id ORDER BY pe.trade_date,pe.id LIMIT 1) AS first_equity_at,
            (SELECT pe.trade_date FROM paper_equity_snapshots pe WHERE pe.paper_instance_id=i.id ORDER BY pe.trade_date DESC,pe.id DESC LIMIT 1) AS last_equity_at
        FROM paper_instances i
        JOIN portfolios p ON p.id=i.portfolio_id
        ORDER BY i.created_at,i.id
        """
    )
    paper = {
        "instance_count": counts["paper_instances"],
        "order_count": _single_count(
            repository,
            "SELECT COUNT(*)::integer AS count FROM orders WHERE paper_instance_id IS NOT NULL",
        ),
        "trade_count": _single_count(
            repository,
            "SELECT COUNT(*)::integer AS count FROM trades WHERE paper_instance_id IS NOT NULL",
        ),
        "position_count": _single_count(
            repository,
            "SELECT COUNT(*)::integer AS count FROM positions WHERE portfolio_id IN (SELECT portfolio_id FROM paper_instances)",
        ),
        "equity_sample_count": counts["paper_equity_snapshots"],
        "event_count": counts["paper_instance_events"],
        "instances": instances,
    }
    return _json_value(
        {
            "schema_version": SCHEMA_VERSION,
            "captured_at": captured_at,
            "repository": {
                "root": str(repo_root.resolve()),
                "head": _git(repo_root, "rev-parse", "HEAD"),
                "branch": _git(repo_root, "branch", "--show-current"),
            },
            "counts": counts,
            "schema_migrations": [str(row["version"]) for row in migration_rows],
            "paper": paper,
        }
    )


def capture_baseline(
    database_url: str,
    repo_root: Path,
    repository: BaselineRepository | None = None,
    *,
    captured_at: str | None = None,
) -> dict[str, object]:
    source = repository or PostgresBaselineRepository(database_url)
    owns_source = repository is None
    try:
        payload = read_continuity_manifest(
            source,
            Path(repo_root),
            captured_at=captured_at or datetime.now(timezone.utc).isoformat(),
        )
    finally:
        if owns_source:
            source.close()  # type: ignore[attr-defined]
    payload["manifest_hash"] = canonical_hash(payload)
    return asdict(RebuildBaseline(**payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture the StockPro rebuild continuity baseline")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import os

    baseline = capture_baseline(args.database_url or os.environ.get("DATABASE_URL", ""), args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"captured {baseline['manifest_hash']} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
