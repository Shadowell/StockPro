from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DATABASE = ROOT / "scripts" / "local_database.sh"
START = ROOT / "start.sh"
RESTART = ROOT / "restart.sh"
STOP = ROOT / "stop.sh"
STATUS = ROOT / "status.sh"
BACKUP = ROOT / "scripts" / "backup_local_data.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_psql(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "psql",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "query=\"${*: -1}\"\n"
        "case \"$query\" in\n"
        "  *current_database*) printf 'stockpro_bitpro_rebase_dev\\n' ;;\n"
        "  *stock_history*) printf '682753|5567|2026-03-02|2026-08-27\\n' ;;\n"
        "  *) printf 'stockpro_bitpro_rebase_dev\\n' ;;\n"
        "esac\n",
    )


def test_local_database_rejects_non_isolated_target() -> None:
    env = {
        **os.environ,
        "STOCKPRO_LOCAL_DATABASE_URL": "postgresql:///stockpro_dev",
    }

    result = subprocess.run(
        [str(LOCAL_DATABASE), "--print-url"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "stockpro_bitpro_rebase_dev" in result.stderr


def test_local_database_accepts_reachable_isolated_target(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_psql(bin_dir)
    expected_url = "postgresql:///stockpro_bitpro_rebase_dev"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STOCKPRO_LOCAL_DATABASE_URL": expected_url,
    }

    result = subprocess.run(
        [str(LOCAL_DATABASE), "--print-url"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected_url

    check_result = subprocess.run(
        [str(LOCAL_DATABASE), "--check"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check_result.returncode == 0, check_result.stderr
    assert "url=postgresql:///stockpro_bitpro_rebase_dev" in check_result.stdout


def test_start_check_uses_local_database_without_install_or_tunnel(tmp_path: Path) -> None:
    sandbox = tmp_path / "stockpro"
    shutil.copytree(ROOT / "scripts", sandbox / "scripts")
    shutil.copy2(START, sandbox / "start.sh")
    (sandbox / "backend" / "venv" / "bin").mkdir(parents=True)
    (sandbox / "frontend" / "node_modules" / ".bin").mkdir(parents=True)
    _write_executable(sandbox / "backend" / "venv" / "bin" / "python", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(sandbox / "frontend" / "node_modules" / ".bin" / "vite", "#!/usr/bin/env bash\nexit 0\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_psql(bin_dir)
    forbidden_log = tmp_path / "forbidden.log"
    for command in ("ssh", "pip", "npm"):
        _write_executable(
            bin_dir / command,
            f"#!/usr/bin/env bash\nprintf '%s\\n' {command} >> '{forbidden_log}'\nexit 99\n",
        )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STOCKPRO_LOCAL_DATABASE_URL": "postgresql:///stockpro_bitpro_rebase_dev",
    }

    result = subprocess.run(
        [str(sandbox / "start.sh"), "--check"],
        cwd=sandbox,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "stockpro_bitpro_rebase_dev" in result.stdout
    assert "本地启动检查通过" in result.stdout
    assert not forbidden_log.exists()


def test_start_handles_free_ports_and_verifies_storage(tmp_path: Path) -> None:
    sandbox = tmp_path / "stockpro"
    shutil.copytree(ROOT / "scripts", sandbox / "scripts")
    shutil.copy2(START, sandbox / "start.sh")
    shutil.copy2(STOP, sandbox / "stop.sh")
    (sandbox / "backend" / "venv" / "bin").mkdir(parents=True)
    (sandbox / "frontend" / "node_modules" / ".bin").mkdir(parents=True)
    _write_executable(sandbox / "backend" / "venv" / "bin" / "python", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(sandbox / "frontend" / "node_modules" / ".bin" / "vite", "#!/usr/bin/env bash\nexit 0\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_psql(bin_dir)
    _write_executable(bin_dir / "lsof", "#!/usr/bin/env bash\nexit 1\n")
    _write_executable(
        bin_dir / "tmux",
        "#!/usr/bin/env bash\n"
        "case \"${1:-}\" in\n"
        "  has-session) exit 1 ;;\n"
        "  display-message) printf '12345\\n' ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
    )
    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        "  */api/health/storage*) printf '{\"status\":\"healthy\",\"database\":\"stockpro_bitpro_rebase_dev\"}' ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STOCKPRO_LOCAL_DATABASE_URL": "postgresql:///stockpro_bitpro_rebase_dev",
    }

    result = subprocess.run(
        [str(sandbox / "start.sh")],
        cwd=sandbox,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "本地服务启动完成" in result.stdout
    assert "database=stockpro_bitpro_rebase_dev" in result.stdout


def test_stop_is_idempotent_when_services_are_not_running(tmp_path: Path) -> None:
    sandbox = tmp_path / "stockpro"
    sandbox.mkdir()
    shutil.copy2(STOP, sandbox / "stop.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "lsof", "#!/usr/bin/env bash\nexit 1\n")
    _write_executable(bin_dir / "tmux", "#!/usr/bin/env bash\nexit 1\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    result = subprocess.run(
        [str(sandbox / "stop.sh")],
        cwd=sandbox,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "数据库与备份未改动" in result.stdout


def test_restart_delegates_to_stop_then_start(tmp_path: Path) -> None:
    sandbox = tmp_path / "stockpro"
    sandbox.mkdir()
    shutil.copy2(RESTART, sandbox / "restart.sh")
    calls = tmp_path / "calls.log"
    _write_executable(sandbox / "stop.sh", f"#!/usr/bin/env bash\nprintf 'stop\\n' >> '{calls}'\n")
    _write_executable(sandbox / "start.sh", f"#!/usr/bin/env bash\nprintf 'start\\n' >> '{calls}'\n")

    result = subprocess.run(
        [str(sandbox / "restart.sh")],
        cwd=sandbox,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == ["stop", "start"]


def test_status_reports_local_data_when_services_are_stopped(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_psql(bin_dir)
    _write_executable(bin_dir / "lsof", "#!/usr/bin/env bash\nexit 1\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STOCKPRO_LOCAL_DATABASE_URL": "postgresql:///stockpro_bitpro_rebase_dev",
    }

    result = subprocess.run(
        [str(STATUS), "--json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["frontend"] == {"running": False, "pid": 0}
    assert payload["backend"] == {"running": False, "pid": 0, "health": "down"}
    assert payload["database"] == {
        "name": "stockpro_bitpro_rebase_dev",
        "status": "reachable",
    }
    assert payload["data"] == {
        "stock_history_rows": 682753,
        "symbols": 5567,
        "first_trade_date": "2026-03-02",
        "last_trade_date": "2026-08-27",
    }


def test_backup_creates_verified_dump_and_metadata(tmp_path: Path) -> None:
    sandbox = tmp_path / "stockpro"
    (sandbox / "scripts").mkdir(parents=True)
    shutil.copy2(LOCAL_DATABASE, sandbox / "scripts" / "local_database.sh")
    shutil.copy2(BACKUP, sandbox / "scripts" / "backup_local_data.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_psql(bin_dir)
    _write_executable(
        bin_dir / "pg_dump",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "output=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  case \"$1\" in --file) output=\"$2\"; shift 2 ;; *) shift ;; esac\n"
        "  done\n"
        "printf 'verified-local-dump' > \"$output\"\n",
    )
    _write_executable(bin_dir / "pg_restore", "#!/usr/bin/env bash\nexit 0\n")
    backup_dir = tmp_path / "backups"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STOCKPRO_LOCAL_DATABASE_URL": "postgresql:///stockpro_bitpro_rebase_dev",
        "STOCKPRO_LOCAL_BACKUP_DIR": str(backup_dir),
        "STOCKPRO_BACKUP_TIMESTAMP": "20260828-120000",
    }

    result = subprocess.run(
        [str(sandbox / "scripts" / "backup_local_data.sh")],
        cwd=sandbox,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    dump = backup_dir / "stockpro_bitpro_rebase_dev-20260828-120000.dump"
    metadata = backup_dir / "stockpro_bitpro_rebase_dev-20260828-120000.json"
    assert dump.read_text(encoding="utf-8") == "verified-local-dump"
    assert (backup_dir / "latest.dump").resolve() == dump
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    assert payload == {
        "database": "stockpro_bitpro_rebase_dev",
        "dump_file": dump.name,
        "first_trade_date": "2026-03-02",
        "last_trade_date": "2026-08-27",
        "stock_history_rows": 682753,
        "symbols": 5567,
    }
    assert (backup_dir / f"{dump.name}.sha256").is_file()
