#!/bin/bash
set -euo pipefail

DB_NAME="${STOCKPRO_DB_NAME:-stockpro_prod}"
DB_USER="${STOCKPRO_DB_USER:-stockpro_app}"
DB_PASSWORD="${STOCKPRO_DB_PASSWORD:-}"
PG_SUPERUSER="${STOCKPRO_PG_SUPERUSER:-postgres}"

if [ -z "$DB_PASSWORD" ]; then
    echo "❌ 请通过 STOCKPRO_DB_PASSWORD 提供应用数据库密码"
    echo "示例：STOCKPRO_DB_PASSWORD='replace-with-strong-password' bash /opt/stockpro/deploy/setup-postgres.sh"
    exit 1
fi

as_pg_superuser() {
    if command -v sudo >/dev/null 2>&1; then
        sudo -u "$PG_SUPERUSER" "$@"
    else
        runuser -u "$PG_SUPERUSER" -- "$@"
    fi
}

echo ">>> 创建/更新 Postgres 用户: $DB_USER"
as_pg_superuser psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
    ELSE
        ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
    END IF;
END
\$\$;
SQL

echo ">>> 创建数据库: $DB_NAME"
if ! as_pg_superuser psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
    as_pg_superuser createdb -O "$DB_USER" "$DB_NAME"
fi

echo ">>> 授权 schema 权限"
as_pg_superuser psql -v ON_ERROR_STOP=1 -d "$DB_NAME" <<SQL
CREATE EXTENSION IF NOT EXISTS pgcrypto;
GRANT CONNECT ON DATABASE ${DB_NAME} TO ${DB_USER};
GRANT USAGE, CREATE ON SCHEMA public TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ${DB_USER};
SQL

echo ""
echo "✅ Postgres 初始化完成"
echo "DATABASE_URL=postgresql://${DB_USER}:<password>@127.0.0.1:5432/${DB_NAME}"
