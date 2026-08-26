#!/usr/bin/env bash
# One-command isolation DB for scripts/check.sh and the API golden path.
#
#   ./scripts/setup_isolation_db.sh
#   export DATABASE_URL="$(./scripts/setup_isolation_db.sh --print-url)"
#   ./scripts/check.sh
#
# Creates stockpro_bitpro_rebase_dev via docker compose or an already-running
# Postgres. It must not target production or the shared development database.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ISOLATION_DB="stockpro_bitpro_rebase_dev"
PYTHON_BIN="${ROOT_DIR}/backend/venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="${PYTHON:-python3}"
fi

load_database_url_from_env_file() {
  if [ -n "${DATABASE_URL:-}" ]; then
    return 0
  fi
  local env_file="$ROOT_DIR/backend/.env"
  if [ ! -f "$env_file" ]; then
    return 0
  fi
  local loaded
  loaded="$(grep -E '^DATABASE_URL=' "$env_file" | tail -n 1 | sed -E 's/^DATABASE_URL=//; s/^"//; s/"$//; s/^'\''//; s/'\''$//')" || true
  if [ -n "$loaded" ]; then
    export DATABASE_URL="$loaded"
  fi
}

derive_database_url() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
import sys
from urllib.parse import urlparse, urlunparse

source = sys.argv[1]
database = sys.argv[2]
parsed = urlparse(source)
print(urlunparse(parsed._replace(path=f"/{database}")))
PY
}

mask_database_url() {
  "$PYTHON_BIN" - "$1" <<'PY'
import sys
from urllib.parse import urlparse, urlunparse

parsed = urlparse(sys.argv[1])
netloc = parsed.netloc
if "@" in netloc:
    userinfo, host = netloc.rsplit("@", 1)
    user = userinfo.split(":", 1)[0]
    netloc = f"{user}:[redacted]@{host}"
print(urlunparse(parsed._replace(netloc=netloc)))
PY
}

load_database_url_from_env_file
DEFAULT_USER="${POSTGRES_USER:-stockpro}"
DEFAULT_PASSWORD="${POSTGRES_PASSWORD:-stockpro}"
DEFAULT_HOST="${POSTGRES_HOST:-127.0.0.1}"
DEFAULT_PORT="${POSTGRES_PORT:-55432}"
if [ -n "${DATABASE_URL:-}" ]; then
  DEFAULT_URL="$(derive_database_url "$DATABASE_URL" "$ISOLATION_DB")"
  ADMIN_URL="${DATABASE_ADMIN_URL:-${POSTGRES_ADMIN_URL:-$(derive_database_url "$DATABASE_URL" postgres)}}"
else
  DEFAULT_URL="postgresql://${DEFAULT_USER}:${DEFAULT_PASSWORD}@${DEFAULT_HOST}:${DEFAULT_PORT}/${ISOLATION_DB}"
  ADMIN_URL="${DATABASE_ADMIN_URL:-${POSTGRES_ADMIN_URL:-postgresql://${DEFAULT_USER}:${DEFAULT_PASSWORD}@${DEFAULT_HOST}:${DEFAULT_PORT}/postgres}}"
fi
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"
SQL_FILE="${ROOT_DIR}/scripts/sql/create_isolation_db.sql"
PYTHON_PROVISION="${ROOT_DIR}/scripts/provision_isolation_db.py"

usage() {
  cat <<'EOF'
Usage: ./scripts/setup_isolation_db.sh [--print-url] [--migrate] [--sql-only] [--help]

  --print-url   Print the isolation DATABASE_URL and exit.
  --migrate     Apply backend/postgres/migrations after the database exists.
  --sql-only    Skip Docker; create the DB on an already-running Postgres.
  --help        Show this help.

Default local URL:
  postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro_bitpro_rebase_dev

Override with POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST / POSTGRES_PORT
or DATABASE_ADMIN_URL (maintenance DB, usually /postgres).
EOF
}

PRINT_URL=0
MIGRATE=0
SQL_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --print-url) PRINT_URL=1 ;;
    --migrate) MIGRATE=1 ;;
    --sql-only) SQL_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "[setup] unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ "$PRINT_URL" -eq 1 ]; then
  echo "$DEFAULT_URL"
  exit 0
fi

echo "[setup] repository root: $ROOT_DIR"
echo "[setup] isolation database: $ISOLATION_DB"
echo "[setup] target URL: $(mask_database_url "$DEFAULT_URL")"

have_docker() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

compose_up() {
  echo "[setup] starting docker compose profile=isolation"
  docker compose --file "$COMPOSE_FILE" --profile isolation up -d postgres
  echo "[setup] waiting for postgres health"
  local attempt
  for attempt in $(seq 1 30); do
    if docker compose --file "$COMPOSE_FILE" --profile isolation exec -T postgres \
      pg_isready -U "$DEFAULT_USER" -d postgres >/dev/null 2>&1; then
      echo "[setup] postgres is ready"
      return 0
    fi
    sleep 1
  done
  echo "[setup] postgres did not become ready on 127.0.0.1:${DEFAULT_PORT}" >&2
  return 1
}

create_with_docker() {
  docker compose --file "$COMPOSE_FILE" --profile isolation exec -T postgres \
    psql -U "$DEFAULT_USER" -d postgres -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/zz-stockpro-isolation.sql
}

create_with_psql() {
  if ! command -v psql >/dev/null 2>&1; then
    return 1
  fi
  echo "[setup] creating ${ISOLATION_DB} via psql"
  psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -f "$SQL_FILE"
}

create_with_python() {
  echo "[setup] creating ${ISOLATION_DB} via ${PYTHON_PROVISION}"
  DATABASE_ADMIN_URL="$ADMIN_URL" "$PYTHON_BIN" "$PYTHON_PROVISION" --admin-url "$ADMIN_URL"
}

migrate_if_requested() {
  if [ "$MIGRATE" -ne 1 ]; then
    echo "[setup] skip migrations (pass --migrate to apply backend/postgres/migrations)"
    return 0
  fi
  echo "[setup] applying migrations"
  DATABASE_URL="$DEFAULT_URL" "$PYTHON_BIN" -c \
    "import sys; sys.path.insert(0, '${ROOT_DIR}/backend'); from app.db.postgres_migrations import apply_migrations; applied=apply_migrations('${DEFAULT_URL}'); print('[setup] applied', len(applied), 'migrations')"
}

if [ "$SQL_ONLY" -eq 0 ] && have_docker; then
  compose_up
  create_with_docker || true
  if ! create_with_python; then
    create_with_psql || {
      echo "[setup] Docker is up but CREATE DATABASE failed. See docs/deployment.md#isolation-database" >&2
      exit 1
    }
  fi
elif create_with_python || create_with_psql; then
  echo "[setup] used an already-running Postgres"
else
  cat <<EOF >&2
[setup] could not create ${ISOLATION_DB}.

Install Docker and re-run:

  ./scripts/setup_isolation_db.sh

Or create it on an existing Postgres:

  psql "\$DATABASE_ADMIN_URL" -v ON_ERROR_STOP=1 -f scripts/sql/create_isolation_db.sql

Then:

  export DATABASE_URL="$(./scripts/setup_isolation_db.sh --print-url)"
  ./scripts/setup_isolation_db.sh --sql-only --migrate

Docs: docs/deployment.md#isolation-database
EOF
  exit 1
fi

migrate_if_requested

cat <<EOF

[setup] isolation DB is ready.

  export DATABASE_URL="$(./scripts/setup_isolation_db.sh --print-url)"
  ./scripts/check.sh

API golden path after the backend is up:

  curl -fsS http://127.0.0.1:4445/api/health
  curl -fsS http://127.0.0.1:4445/api/health/storage

Docs: docs/deployment.md#isolation-database
EOF
