#!/bin/bash
# Runs only on an empty Postgres data volume (docker-entrypoint-initdb.d).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<'SQL'
SELECT 'CREATE DATABASE stockpro_bitpro_rebase_dev OWNER CURRENT_USER'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'stockpro_bitpro_rebase_dev'
)\gexec
SQL
