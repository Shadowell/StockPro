from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "scripts" / "setup_isolation_db.sh"
CHECK = ROOT / "scripts" / "check.sh"
COMPOSE = ROOT / "docker-compose.yml"
SQL = ROOT / "scripts" / "sql" / "create_isolation_db.sql"


def test_setup_script_prints_isolation_url() -> None:
    result = subprocess.run([str(SETUP), "--print-url"], check=True, capture_output=True, text=True)
    assert result.stdout.strip().endswith("/stockpro_bitpro_rebase_dev")
    assert result.stdout.strip().startswith("postgresql://")


def test_compose_and_sql_target_isolation_db() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    sql = SQL.read_text(encoding="utf-8")
    setup = SETUP.read_text(encoding="utf-8")
    assert "stockpro_bitpro_rebase_dev" in compose
    assert "profile" in compose or "profiles:" in compose
    assert "isolation" in compose
    assert "CREATE DATABASE stockpro_bitpro_rebase_dev" in sql
    assert "stockpro_bitpro_rebase_dev" in setup
    assert SETUP.stat().st_mode & 0o111


def test_check_sh_points_at_setup_when_url_missing() -> None:
    env = {key: value for key, value in os.environ.items() if key != "DATABASE_URL"}
    env["STOCKPRO_CHECK_SKIP_ENV_FILE"] = "1"
    result = subprocess.run([str(CHECK)], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "setup_isolation_db.sh" in output
    assert "stockpro_bitpro_rebase_dev" in output
    assert "docs/deployment.md#isolation-database" in output


def test_check_sh_rejects_non_isolated_url() -> None:
    env = {**os.environ, "DATABASE_URL": "postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro_dev"}
    result = subprocess.run([str(CHECK)], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "refusing non-isolated DATABASE_URL" in output
    assert "setup_isolation_db.sh" in output
