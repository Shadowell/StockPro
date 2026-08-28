#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ISOLATION_DB="stockpro_bitpro_rebase_dev"
SOCKET_URL="postgresql:///${ISOLATION_DB}"
DOCKER_URL="postgresql://${POSTGRES_USER:-stockpro}:${POSTGRES_PASSWORD:-stockpro}@${POSTGRES_HOST:-127.0.0.1}:${POSTGRES_PORT:-55432}/${ISOLATION_DB}"

usage() {
  cat <<'EOF'
Usage: ./scripts/local_database.sh [--print-url|--check]

Select a reachable local PostgreSQL database named stockpro_bitpro_rebase_dev.
The script never opens an SSH tunnel, never inherits DATABASE_URL, and rejects
any host other than a Unix socket, 127.0.0.1, localhost, or ::1.

It prefers the Docker isolation port 127.0.0.1:55432, then a same-name local
socket. backend/.env credentials are reused only when that file already points
at a local host.

Optional override:
  STOCKPRO_LOCAL_DATABASE_URL=postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro_bitpro_rebase_dev
EOF
}

MODE="print"
case "${1:---print-url}" in
  --print-url) MODE="print" ;;
  --check) MODE="check" ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

if ! command -v psql >/dev/null 2>&1; then
  echo "[local-db] psql 未安装，无法验证本地 PostgreSQL。" >&2
  exit 1
fi

database_name_from_url() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlparse

print(urlparse(sys.argv[1]).path.lstrip("/"))
PY
}

mask_url() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlparse, urlunparse

parsed = urlparse(sys.argv[1])
netloc = parsed.netloc
if not netloc:
    print(f"{parsed.scheme}://{parsed.path}")
    raise SystemExit(0)
if "@" in netloc:
    userinfo, host = netloc.rsplit("@", 1)
    user = userinfo.split(":", 1)[0]
    netloc = f"{user}:[redacted]@{host}"
print(urlunparse(parsed._replace(netloc=netloc)))
PY
}

is_local_url() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
host = (parsed.hostname or "").lower()
if not host:
    raise SystemExit(0)
raise SystemExit(0 if host in {"127.0.0.1", "localhost", "::1"} else 1)
PY
}

local_env_isolation_url() {
  local env_file="$ROOT_DIR/backend/.env"
  if [ ! -f "$env_file" ]; then
    return 1
  fi
  local loaded
  loaded="$(grep -E '^DATABASE_URL=' "$env_file" | tail -n 1 | sed -E 's/^DATABASE_URL=//; s/^"//; s/"$//; s/^'\''//; s/'\''$//')" || true
  if [ -z "$loaded" ] || ! is_local_url "$loaded"; then
    return 1
  fi
  python3 - "$loaded" "$ISOLATION_DB" <<'PY'
import sys
from urllib.parse import urlparse, urlunparse

parsed = urlparse(sys.argv[1])
database = sys.argv[2]
if parsed.netloc:
    print(urlunparse(parsed._replace(path=f"/{database}")))
else:
    print(f"{parsed.scheme}:///{database}")
PY
}

validate_candidate() {
  local candidate="$1"
  if ! is_local_url "$candidate"; then
    echo "[local-db] 拒绝远程数据库；本地服务只连接本机 ${ISOLATION_DB}。" >&2
    return 1
  fi
  local configured_name
  configured_name="$(database_name_from_url "$candidate")"
  if [ "$configured_name" != "$ISOLATION_DB" ]; then
    echo "[local-db] 拒绝数据库 ${configured_name:-<empty>}；本地服务只允许 ${ISOLATION_DB}。" >&2
    return 1
  fi

  local actual_name
  if ! actual_name="$(psql "$candidate" -X -Atqc "SELECT current_database()" 2>/dev/null)"; then
    return 1
  fi
  if [ "$actual_name" != "$ISOLATION_DB" ]; then
    echo "[local-db] 连接实际落到 ${actual_name:-<unknown>}，不是 ${ISOLATION_DB}。" >&2
    return 1
  fi
  return 0
}

explicit_url="${STOCKPRO_LOCAL_DATABASE_URL:-}"
if [ -n "$explicit_url" ]; then
  if ! validate_candidate "$explicit_url"; then
    echo "[local-db] 显式本地数据库不可用，请修正 STOCKPRO_LOCAL_DATABASE_URL。" >&2
    exit 1
  fi
  selected_url="$explicit_url"
else
  selected_url=""
  derived_url="$(local_env_isolation_url || true)"
  candidate_urls=("$DOCKER_URL")
  if [ -n "$derived_url" ]; then
    candidate_urls+=("$derived_url")
  fi
  candidate_urls+=("$SOCKET_URL")
  for candidate_url in "${candidate_urls[@]}"; do
    if validate_candidate "$candidate_url"; then
      selected_url="$candidate_url"
      break
    fi
  done
  if [ -z "$selected_url" ]; then
    cat >&2 <<EOF
[local-db] 未找到可达的本机 ${ISOLATION_DB}。

先初始化本地隔离库：
  ./scripts/setup_isolation_db.sh

或显式指定本机地址：
  STOCKPRO_LOCAL_DATABASE_URL='postgresql://stockpro:stockpro@127.0.0.1:55432/${ISOLATION_DB}' ./start.sh
EOF
    exit 1
  fi
fi

if [ "$MODE" = "check" ]; then
  echo "database=${ISOLATION_DB}"
  echo "url=$(mask_url "$selected_url")"
  echo "status=reachable"
else
  echo "$selected_url"
fi
