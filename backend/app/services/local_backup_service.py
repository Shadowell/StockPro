"""Local-only PostgreSQL backup and disposable restore rehearsal evidence."""
from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse, urlunparse

import psycopg2
import psycopg2.extras

from app.core.config import settings
from app.services.dataset_snapshot_service import canonical_hash


class LocalBackupService:
    def __init__(self, database, database_url: Optional[str] = None):
        self.database = database
        self.database_url = database_url or settings.DATABASE_URL
        self.parsed = urlparse(self.database_url)

    def create_backup(self, output_dir: Optional[str] = None, backup_type: str = "daily") -> Dict[str, Any]:
        if backup_type not in {"daily", "manual"}:
            raise ValueError("backup_type 必须是 daily 或 manual")
        root = Path(output_dir) if output_dir else Path(__file__).resolve().parents[3] / ".local" / "backups"
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = root / f"stockpro-{stamp}.dump"
        manifest = self._manifest(self.database_url)
        run_id = self._insert_run(backup_type, "running", str(target), manifest)
        try:
            self._command(["pg_dump", *self._connection_args(), "--format=custom", "--no-owner", "--no-acl", "--file", str(target)])
            digest = self._file_hash(target)
            size = target.stat().st_size
            stored_manifest = {"database": manifest, "dump_sha256": digest, "size": size}
            manifest_hash = canonical_hash(stored_manifest)
            self._execute("UPDATE backup_runs SET status='success',manifest=%s,manifest_hash=%s,backup_size_bytes=%s,finished_at=NOW() WHERE id=%s", (psycopg2.extras.Json(stored_manifest, dumps=self._json_dumps), manifest_hash, size, run_id))
            return self._row("SELECT * FROM backup_runs WHERE id=%s", (run_id,)) or {}
        except Exception as exc:
            self._execute("UPDATE backup_runs SET status='failed',restore_evidence=%s,finished_at=NOW() WHERE id=%s", (psycopg2.extras.Json({"error": str(exc)[:1000]}), run_id))
            raise

    def restore_latest(self) -> Dict[str, Any]:
        backup = self._row("SELECT * FROM backup_runs WHERE backup_type IN ('daily','manual') AND status='success' ORDER BY finished_at DESC LIMIT 1")
        if not backup:
            raise ValueError("没有可还原的成功本地备份")
        source = Path(str(backup["location_ref"]))
        stored_manifest = dict(backup.get("manifest") or {})
        if not source.exists():
            raise ValueError("备份文件不存在")
        if self._file_hash(source) != stored_manifest.get("dump_sha256"):
            raise ValueError("备份文件哈希与审计清单不一致")
        database_name = f"stockpro_restore_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        run_id = self._insert_run("restore_rehearsal", "running", str(source), dict(backup.get("manifest") or {}), restore_database=database_name)
        restored_url = self._database_url(database_name)
        try:
            self._command(["createdb", *self._connection_args(include_database=False), database_name])
            try:
                self._command(["pg_restore", *self._connection_args(database_name=database_name), "--no-owner", "--no-acl", str(source)])
            except RuntimeError as exc:
                # pg_dump 17 adds transaction_timeout while the local PG 16 server does not know it.
                # Without --exit-on-error pg_restore completes every remaining object; reconciliation below is decisive.
                if "transaction_timeout" not in str(exc):
                    raise
            expected = dict(stored_manifest.get("database") or {})
            observed = self._manifest(restored_url)
            checks = {key: observed.get(key) == value for key, value in expected.items()}
            evidence = {"source_backup_id": str(backup["id"]), "expected": expected, "observed": observed, "checks": checks, "all_match": all(checks.values())}
            status = "success" if evidence["all_match"] else "failed"
            self._execute("UPDATE backup_runs SET status=%s,restore_evidence=%s,manifest_hash=%s,finished_at=NOW() WHERE id=%s", (status, psycopg2.extras.Json(evidence, dumps=self._json_dumps), canonical_hash(evidence), run_id))
            if status != "success":
                raise ValueError("还原数据库证据清单不一致")
            return self._row("SELECT * FROM backup_runs WHERE id=%s", (run_id,)) or {}
        except Exception as exc:
            self._execute("UPDATE backup_runs SET status='failed',restore_evidence=%s,finished_at=NOW() WHERE id=%s AND status='running'", (psycopg2.extras.Json({"error": str(exc)[:1000]}), run_id))
            raise
        finally:
            try:
                self._command(["dropdb", *self._connection_args(include_database=False), "--if-exists", "--force", database_name])
            except Exception:
                pass

    def latest(self) -> Dict[str, Any]:
        rows = self._rows("SELECT * FROM backup_runs ORDER BY started_at DESC LIMIT 20")
        return {"items": rows, "latest_success": next((item for item in rows if item["status"] == "success" and item["backup_type"] in {"daily", "manual"}), None)}

    def _manifest(self, database_url: str) -> Dict[str, Any]:
        with psycopg2.connect(database_url) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                def one(query: str) -> Dict[str, Any]:
                    cursor.execute(query)
                    row = cursor.fetchone()
                    return dict(row) if row else {}
                dataset = one("SELECT id,manifest_hash FROM dataset_snapshots WHERE status='sealed' ORDER BY id DESC LIMIT 1")
                factor = one("SELECT id,manifest_hash FROM factor_snapshots WHERE status='sealed' ORDER BY id DESC LIMIT 1")
                backtest = one("SELECT id,result_manifest->>'manifest_hash' AS manifest_hash FROM backtest_runs WHERE status='success' AND run_mode='full' ORDER BY sealed_at DESC NULLS LAST LIMIT 1")
                paper = one("""
                    SELECT i.id,i.last_processed_trade_date,i.last_cycle_key,p.cash_balance,
                           (SELECT COUNT(*) FROM trades t WHERE t.paper_instance_id=i.id)::INTEGER AS trade_count,
                           (SELECT COUNT(*) FROM cash_ledger l WHERE l.paper_instance_id=i.id)::INTEGER AS ledger_count,
                           (SELECT COALESCE(SUM(l.amount),0) FROM cash_ledger l WHERE l.paper_instance_id=i.id) AS ledger_total
                    FROM paper_instances i JOIN portfolios p ON p.id=i.portfolio_id
                    ORDER BY (SELECT COUNT(*) FROM trades t WHERE t.paper_instance_id=i.id) DESC,i.created_at DESC LIMIT 1
                """)
                review = one("SELECT id,trade_date,source_manifest_hash,status FROM daily_reviews ORDER BY trade_date DESC LIMIT 1")
                cursor.execute("SELECT COUNT(*)::INTEGER AS count FROM schema_migrations")
                migrations = dict(cursor.fetchone() or {})
        import json
        return json.loads(json.dumps({"dataset": dataset, "factor": factor, "backtest": backtest, "paper": paper, "review": review, "migrations": migrations}, default=str))

    def _connection_args(self, *, include_database: bool = True, database_name: Optional[str] = None) -> list[str]:
        args = ["--host", str(self.parsed.hostname or "127.0.0.1"), "--port", str(self.parsed.port or 5432), "--username", unquote(self.parsed.username or "")]
        if include_database:
            args.extend(["--dbname", database_name or self.parsed.path.lstrip("/")])
        return args

    def _command(self, command: list[str]) -> None:
        env = {**os.environ, "PGPASSWORD": unquote(self.parsed.password or "")}
        try:
            subprocess.run(command, env=env, check=True, capture_output=True, text=True, timeout=600)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError((exc.stderr or exc.stdout or "PostgreSQL command failed")[-2000:]) from exc

    def _database_url(self, database_name: str) -> str:
        return urlunparse(self.parsed._replace(path=f"/{database_name}"))

    def _insert_run(self, backup_type: str, status: str, location: str, manifest: Dict[str, Any], restore_database: Optional[str] = None) -> str:
        row = self._row("INSERT INTO backup_runs(backup_type,status,location_ref,manifest,restore_database) VALUES (%s,%s,%s,%s,%s) RETURNING id", (backup_type, status, location, psycopg2.extras.Json(manifest, dumps=self._json_dumps), restore_database))
        return str((row or {})["id"])

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _json_dumps(value: Any) -> str:
        import json
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def _row(self, query: str, params=()) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return dict(row) if row else None

    def _rows(self, query: str, params=()) -> list[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(item) for item in cursor.fetchall()]

    def _execute(self, query: str, params=()) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
