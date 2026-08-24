-- Create the StockPro isolation database used by scripts/check.sh.
-- Connect to a maintenance database (usually `postgres` or `stockpro`) first.
--
--   psql "postgresql://stockpro:stockpro@127.0.0.1:55432/postgres" \
--     -v ON_ERROR_STOP=1 -f scripts/sql/create_isolation_db.sql
--
-- Docker first-boot uses scripts/sql/docker-init-isolation-db.sh instead.
-- The one-command wrapper is ./scripts/setup_isolation_db.sh.

SELECT 'CREATE DATABASE stockpro_bitpro_rebase_dev OWNER CURRENT_USER'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'stockpro_bitpro_rebase_dev'
)\gexec

\connect stockpro_bitpro_rebase_dev

GRANT CONNECT ON DATABASE stockpro_bitpro_rebase_dev TO CURRENT_USER;
GRANT USAGE, CREATE ON SCHEMA public TO CURRENT_USER;
