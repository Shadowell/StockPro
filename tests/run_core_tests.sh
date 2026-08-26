#!/bin/bash
# ============================================
# BitPro 核心本地验收（无外网依赖）
# 用法: cd tests && bash run_core_tests.sh
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PASSED=0
FAILED=0

run_step() {
    local name="$1"
    local cmd="$2"
    echo -e "${BOLD}${CYAN}[${name}]${NC}"
    if eval "$cmd"; then
        echo -e "  ${GREEN}✓ 通过${NC}"
        PASSED=$((PASSED + 1))
    else
        echo -e "  ${RED}✗ 失败${NC}"
        FAILED=$((FAILED + 1))
    fi
    echo ""
}

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║      BitPro 核心本地验收 (Core)         ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}时间: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo ""

run_step "Backend 语法编译" "cd \"$PROJECT_DIR\" && python3 -m compileall backend/app"

TEST_PYTHON="python3"
if [ -x "$BACKEND_DIR/venv/bin/python" ] && "$BACKEND_DIR/venv/bin/python" -c "import pytest" >/dev/null 2>&1; then
    TEST_PYTHON="$BACKEND_DIR/venv/bin/python"
fi
run_step "Core 单元测试" "cd \"$PROJECT_DIR\" && \"$TEST_PYTHON\" -m pytest tests/test_00_core_local.py tests/test_01_v2_contract_local.py -q -c \"$PROJECT_DIR/tests/pytest.ini\""

run_step "Frontend 构建" "cd \"$FRONTEND_DIR\" && npm run build"

echo -e "${BOLD}${CYAN}══════════════════════════════════════════${NC}"
echo -e "${BOLD}   Core 验收汇总${NC}"
echo -e "${BOLD}${CYAN}══════════════════════════════════════════${NC}"
echo -e "  ${GREEN}通过: ${PASSED}${NC}"
echo -e "  ${RED}失败: ${FAILED}${NC}"
echo ""

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi
exit 0
