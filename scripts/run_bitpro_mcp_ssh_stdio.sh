#!/usr/bin/env bash
set -euo pipefail

TOKEN_FILE="${BITPRO_CODEX_MCP_TOKEN_FILE:-/opt/bitpro/.secrets/codex_mcp_token}"

if [ ! -s "${TOKEN_FILE}" ]; then
  echo "BitPro MCP Agent token file is missing or empty: ${TOKEN_FILE}" >&2
  exit 1
fi

if [ "$(stat -c '%a' "${TOKEN_FILE}")" != "600" ]; then
  echo "BitPro MCP Agent token file must have mode 600: ${TOKEN_FILE}" >&2
  exit 1
fi

export BITPRO_MCP_API_TOKEN="$(cat "${TOKEN_FILE}")"
export BITPRO_MCP_API_BASE="http://127.0.0.1:8889/api/v2"
export BITPRO_MCP_AUTH_HEADER="X-BitPro-MCP-Token"
export BITPRO_MCP_AUDIT_PATH="/opt/bitpro/data/mcp_tool_audit.jsonl"
export BITPRO_MCP_ENABLE_LIVE_TRADING="0"

cd /opt/bitpro/backend
exec /opt/bitpro/backend/venv/bin/python /opt/bitpro/scripts/bitpro_mcp_server.py
