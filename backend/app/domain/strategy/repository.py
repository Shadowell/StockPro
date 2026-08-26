"""PostgreSQL repository for BitPro's A-share strategy workbench port."""
from __future__ import annotations

import hashlib
from typing import Callable

import psycopg2
import psycopg2.extras

from app.core.config import settings


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
                    """
                    SELECT DISTINCT ON (name)
                           id,legacy_strategy_id,name,version,description,script_content,
                           parameter_schema,data_dependencies,output_contract,status,
                           validation_status,created_at,updated_at
                    FROM strategy_versions
                    WHERE status <> 'archived'
                    ORDER BY name,version DESC,created_at DESC
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_strategy(self, strategy_id: int | str) -> dict | None:
        raw = str(strategy_id)
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id,legacy_strategy_id,name,version,description,script_content,
                           parameter_schema,data_dependencies,output_contract,status,
                           validation_status,created_at,updated_at
                    FROM strategy_versions
                    WHERE id::text=%s OR legacy_strategy_id::text=%s
                    ORDER BY version DESC,created_at DESC LIMIT 1
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
