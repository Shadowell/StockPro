"""PostgreSQL repository for BitPro's A-share strategy workbench port."""
from __future__ import annotations

import hashlib
from typing import Callable

import psycopg2
import psycopg2.extras

from app.core.config import settings


BACKTEST_ID_SQL = "((('x'||substr(replace(r.id::text,'-',''),1,8))::bit(32)::bigint & 2147483647)::integer)"
PAPER_ID_SQL = "((('x'||substr(replace(i.id::text,'-',''),1,8))::bit(32)::bigint & 2147483647)::integer)"


class StrategyRepository:
    def __init__(self, database_url: str | None = None, *, connection_factory: Callable[..., object] = psycopg2.connect) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self, *, readonly: bool = True):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for the A-share strategy port")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=readonly, autocommit=False)
        return connection

    def list_strategies(self) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT DISTINCT ON (name)
                           s.id,s.legacy_strategy_id,s.name,s.version,s.description,s.script_content,
                           s.parameter_schema,s.data_dependencies,s.output_contract,s.status,
                           s.validation_status,s.validation_report,s.strategy_api_version,s.content_hash,
                           s.validated_at,s.created_at,s.updated_at,
                           r.id AS linked_backtest_uuid,{BACKTEST_ID_SQL} AS linked_backtest_id,
                           r.status AS linked_backtest_status,r.start_date AS linked_backtest_start_date,
                           r.end_date AS linked_backtest_end_date,r.universe AS linked_backtest_universe,
                           r.parameters AS linked_backtest_parameters,r.metrics AS linked_backtest_metrics,
                           r.equity_point_count,
                           r.fill_count,r.order_count,
                           i.id AS linked_paper_uuid,{PAPER_ID_SQL} AS linked_paper_id,
                           i.status AS linked_paper_status,i.parameters AS linked_paper_parameters,
                           i.capacity_limits AS linked_paper_capacity_limits,i.feed_config AS linked_paper_feed_config,
                           i.runtime_version AS linked_paper_runtime_version,
                           ARRAY(SELECT DISTINCT pos.symbol FROM positions pos WHERE pos.portfolio_id=i.portfolio_id ORDER BY pos.symbol) AS linked_paper_symbols,
                           t.symbol AS latest_trade_symbol,t.reason AS latest_trade_reason
                    FROM strategy_versions s
                    LEFT JOIN LATERAL (
                        SELECT br.*,
                               (SELECT COUNT(*) FROM backtest_daily_equity be WHERE be.backtest_run_id=br.id) AS equity_point_count,
                               (SELECT COUNT(*) FROM backtest_trades bt WHERE bt.backtest_run_id=br.id) AS fill_count,
                               (SELECT COUNT(*) FROM backtest_orders bo WHERE bo.backtest_run_id=br.id) AS order_count
                        FROM backtest_runs br WHERE br.strategy_version_id=s.id AND br.status='success' AND br.sealed_at IS NOT NULL
                        ORDER BY br.created_at DESC LIMIT 1
                    ) r ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT pi.* FROM paper_instances pi WHERE pi.strategy_version_id=s.id
                        ORDER BY pi.created_at DESC LIMIT 1
                    ) i ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT bt.symbol,bt.reason FROM backtest_trades bt WHERE bt.backtest_run_id=r.id
                        ORDER BY bt.trade_date DESC,bt.id DESC LIMIT 1
                    ) t ON TRUE
                    WHERE s.status <> 'archived'
                    ORDER BY s.name,s.version DESC,s.created_at DESC
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_strategy(self, strategy_id: int | str) -> dict | None:
        raw = str(strategy_id)
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT s.id,s.legacy_strategy_id,s.name,s.version,s.description,s.script_content,
                           s.parameter_schema,s.data_dependencies,s.output_contract,s.status,
                           s.validation_status,s.validation_report,s.strategy_api_version,s.content_hash,
                           s.validated_at,s.created_at,s.updated_at,
                           r.id AS linked_backtest_uuid,{BACKTEST_ID_SQL} AS linked_backtest_id,
                           r.status AS linked_backtest_status,r.start_date AS linked_backtest_start_date,
                           r.end_date AS linked_backtest_end_date,r.universe AS linked_backtest_universe,
                           r.parameters AS linked_backtest_parameters,r.metrics AS linked_backtest_metrics,
                           r.equity_point_count,
                           r.fill_count,r.order_count,
                           i.id AS linked_paper_uuid,{PAPER_ID_SQL} AS linked_paper_id,
                           i.status AS linked_paper_status,i.parameters AS linked_paper_parameters,
                           i.capacity_limits AS linked_paper_capacity_limits,i.feed_config AS linked_paper_feed_config,
                           i.runtime_version AS linked_paper_runtime_version,
                           ARRAY(SELECT DISTINCT pos.symbol FROM positions pos WHERE pos.portfolio_id=i.portfolio_id ORDER BY pos.symbol) AS linked_paper_symbols,
                           t.symbol AS latest_trade_symbol,t.reason AS latest_trade_reason
                    FROM strategy_versions s
                    LEFT JOIN LATERAL (
                        SELECT br.*,
                               (SELECT COUNT(*) FROM backtest_daily_equity be WHERE be.backtest_run_id=br.id) AS equity_point_count,
                               (SELECT COUNT(*) FROM backtest_trades bt WHERE bt.backtest_run_id=br.id) AS fill_count,
                               (SELECT COUNT(*) FROM backtest_orders bo WHERE bo.backtest_run_id=br.id) AS order_count
                        FROM backtest_runs br WHERE br.strategy_version_id=s.id AND br.status='success' AND br.sealed_at IS NOT NULL
                        ORDER BY br.created_at DESC LIMIT 1
                    ) r ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT pi.* FROM paper_instances pi WHERE pi.strategy_version_id=s.id
                        ORDER BY pi.created_at DESC LIMIT 1
                    ) i ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT bt.symbol,bt.reason FROM backtest_trades bt WHERE bt.backtest_run_id=r.id
                        ORDER BY bt.trade_date DESC,bt.id DESC LIMIT 1
                    ) t ON TRUE
                    WHERE s.id::text=%s OR s.legacy_strategy_id::text=%s
                    ORDER BY s.version DESC,s.created_at DESC LIMIT 1
                    """,
                    (raw, raw),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _insert_validation(cursor, version_id: str, code_hash: str, validation: dict) -> None:
        status = "valid" if validation.get("valid") else "invalid"
        cursor.execute(
            """
            INSERT INTO strategy_validation_runs
            (strategy_version_id,strategy_api_version,status,report,code_hash)
            VALUES (%s,'stockpro.v1',%s,%s,%s)
            """,
            (version_id, status, psycopg2.extras.Json(validation), code_hash),
        )

    def create_strategy(self, payload: dict, validation: dict) -> dict:
        code = str(payload["script_content"])
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        try:
            with self._connect(readonly=False) as connection:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO strategy_scripts
                        (name,description,script_content,interval_seconds,enabled,data_purpose)
                        VALUES (%s,%s,%s,86400,FALSE,'user') RETURNING id
                        """,
                        (payload["name"], payload.get("description") or "", code),
                    )
                    legacy_id = int(cursor.fetchone()["id"])
                    cursor.execute(
                        """
                        INSERT INTO strategy_versions
                        (legacy_strategy_id,name,version,description,script_content,content_hash,
                         strategy_api_version,parameter_schema,data_dependencies,output_contract,
                         dependency_manifest,status,validation_status,validation_report,validated_at,migration_status)
                        VALUES (%s,%s,1,%s,%s,%s,'stockpro.v1',%s,%s,%s,'{}'::jsonb,'draft',%s,%s,NOW(),'native_v1')
                        RETURNING *
                        """,
                        (
                            legacy_id, payload["name"], payload.get("description") or "", code, code_hash,
                            psycopg2.extras.Json(payload.get("parameter_schema") or {}),
                            psycopg2.extras.Json(payload.get("data_dependencies") or ["daily_bars"]),
                            psycopg2.extras.Json({"type": "order_intents"}),
                            "valid" if validation.get("valid") else "invalid",
                            psycopg2.extras.Json(validation),
                        ),
                    )
                    row = dict(cursor.fetchone())
                    self._insert_validation(cursor, str(row["id"]), code_hash, validation)
            return row
        except psycopg2.errors.UniqueViolation as exc:
            raise ValueError("策略名称已存在，请使用编辑创建新版本") from exc

    def create_version(self, strategy_id: int | str, payload: dict, validation: dict) -> dict:
        parent = self.get_strategy(strategy_id)
        if not parent:
            raise ValueError("父策略版本不存在")
        old_name = str(parent["name"])
        new_name = str(payload.get("name") or old_name).strip()
        code = str(payload["script_content"])
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        try:
            with self._connect(readonly=False) as connection:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT COALESCE(MAX(version),0)+1 AS next_version FROM strategy_versions WHERE name=%s", (new_name,))
                    version = int(cursor.fetchone()["next_version"])
                    cursor.execute(
                        """
                        INSERT INTO strategy_versions
                        (legacy_strategy_id,name,version,description,script_content,content_hash,
                         strategy_api_version,parameter_schema,data_dependencies,output_contract,
                         parent_version_id,dependency_manifest,status,validation_status,validation_report,
                         validated_at,migration_status)
                        VALUES (%s,%s,%s,%s,%s,%s,'stockpro.v1',%s,%s,%s,%s,'{}'::jsonb,
                                'draft',%s,%s,NOW(),'native_v1') RETURNING *
                        """,
                        (
                            parent.get("legacy_strategy_id"), new_name, version,
                            payload.get("description", parent.get("description") or ""), code, code_hash,
                            psycopg2.extras.Json(payload.get("parameter_schema") or parent.get("parameter_schema") or {}),
                            psycopg2.extras.Json(payload.get("data_dependencies") or parent.get("data_dependencies") or ["daily_bars"]),
                            psycopg2.extras.Json({"type": "order_intents"}), parent["id"],
                            "valid" if validation.get("valid") else "invalid", psycopg2.extras.Json(validation),
                        ),
                    )
                    row = dict(cursor.fetchone())
                    self._insert_validation(cursor, str(row["id"]), code_hash, validation)
                    if new_name != old_name:
                        cursor.execute("UPDATE strategy_versions SET status='archived' WHERE name=%s AND id<>%s", (old_name, row["id"]))
            return row
        except psycopg2.errors.UniqueViolation as exc:
            raise ValueError("目标策略名称已存在") from exc

    def archive_strategy(self, strategy_id: int | str) -> bool:
        row = self.get_strategy(strategy_id)
        if not row:
            return False
        with self._connect(readonly=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE strategy_versions SET status='archived' WHERE name=%s", (row["name"],))
                if row.get("legacy_strategy_id") is not None:
                    cursor.execute("UPDATE strategy_scripts SET enabled=FALSE,is_running=FALSE,updated_at=NOW() WHERE id=%s", (row["legacy_strategy_id"],))
        return True
