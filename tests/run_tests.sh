#!/bin/bash
# ============================================
# BitPro 自动化测试 - 一键运行
# 用法: cd tests && bash run_tests.sh
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
REPORT_FILE="$SCRIPT_DIR/test_report.txt"
CORE_ONLY=false

for arg in "$@"; do
    case $arg in
        --core-only)
            CORE_ONLY=true
            ;;
        -h|--help)
            echo "用法: bash run_tests.sh [--core-only]"
            echo ""
            echo "选项:"
            echo "  --core-only   仅执行本地核心验收（不依赖外网/交易所）"
            exit 0
            ;;
    esac
done

if [ "$CORE_ONLY" = true ]; then
    exec "$SCRIPT_DIR/run_core_tests.sh"
fi

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║       BitPro 自动化测试套件 v1.0        ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}时间: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo ""

# ============ 前置检查 ============
echo -e "${BOLD}[0/5] 前置检查${NC}"

# 检查后端
if ! curl -s http://127.0.0.1:8889/api/v2/system/health > /dev/null 2>&1; then
    echo -e "${RED}✗ 后端未运行 (port 8889)，请先启动后端${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ 后端运行中 :8889${NC}"

# 检查前端
if ! curl -s http://127.0.0.1:8888 > /dev/null 2>&1; then
    echo -e "${RED}✗ 前端未运行 (port 8888)，请先启动前端${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ 前端运行中 :8888${NC}"

# 激活虚拟环境
source "$BACKEND_DIR/venv/bin/activate" 2>/dev/null || true

# 检查 pytest
if ! python -c "import pytest" 2>/dev/null; then
    echo -e "${RED}✗ pytest 未安装${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ pytest 已安装${NC}"
echo ""

# ============ 运行测试 ============
TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_SKIP=0
BUGS=""
ENV_ISSUES=""
APP_ISSUES=""

classify_failure() {
    local details="$1"
    if echo "$details" | grep -Eqi "Connection refused|ConnectError|Timeout|proxy|load_markets failed|network|not configured"; then
        echo "env"
    else
        echo "app"
    fi
}

run_module() {
    local module_name="$1"
    local test_file="$2"
    local marker="$3"

    echo -e "${BOLD}${CYAN}[$module_name]${NC}"

    output=$("$BACKEND_DIR/venv/bin/python" -m pytest "$SCRIPT_DIR/$test_file" \
        -c "$SCRIPT_DIR/pytest.ini" \
        --tb=short -q 2>&1) || true

    # 提取统计 — 匹配最后一行含 "passed"/"failed"/"error" 的汇总行
    summary_line=$(echo "$output" | grep -E "[0-9]+ (passed|failed|error)" | tail -1)
    passed=$(echo "$summary_line" | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+" || echo "0")
    failed=$(echo "$summary_line" | grep -oE "[0-9]+ failed" | grep -oE "[0-9]+" || echo "0")
    skipped=$(echo "$summary_line" | grep -oE "[0-9]+ skipped" | grep -oE "[0-9]+" || echo "0")
    errors=$(echo "$summary_line" | grep -oE "[0-9]+ error" | grep -oE "[0-9]+" || echo "0")

    passed=${passed:-0}
    failed=${failed:-0}
    skipped=${skipped:-0}
    errors=${errors:-0}

    # 累加
    TOTAL_PASS=$((TOTAL_PASS + passed))
    TOTAL_FAIL=$((TOTAL_FAIL + failed + errors))
    TOTAL_SKIP=$((TOTAL_SKIP + skipped))

    if [ "$((failed + errors))" -gt 0 ]; then
        echo -e "  ${RED}✗ ${passed} passed, ${failed} failed, ${errors} errors${NC}"
        # 提取失败详情（FAILED行 + AssertionError + assert行 + 实际错误内容）
        fail_details=$(echo "$output" | grep -E "^FAILED|Assertion|assert |Error:|error TS" | head -30)
        BUGS="${BUGS}\n--- ${module_name} ---\n${fail_details}\n"
        if [ "$(classify_failure "$output")" = "env" ]; then
            ENV_ISSUES="${ENV_ISSUES}\n--- ${module_name} ---\n${fail_details}\n"
        else
            APP_ISSUES="${APP_ISSUES}\n--- ${module_name} ---\n${fail_details}\n"
        fi
        # 完整输出保留给报告
        echo "====== ${module_name} ======" >> "$REPORT_FILE.detail"
        echo "$output" >> "$REPORT_FILE.detail"
        echo "" >> "$REPORT_FILE.detail"
    else
        echo -e "  ${GREEN}✓ ${passed} passed${NC}"
    fi
}

# 清空报告
echo "BitPro 自动化测试报告" > "$REPORT_FILE"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')" >> "$REPORT_FILE"
echo "================================" >> "$REPORT_FILE"
rm -f "$REPORT_FILE.detail"

echo -e "${BOLD}[1/5] 健康检查 & 交易所连接${NC}"
run_module "健康检查" "test_01_health.py" "health"

echo ""
echo -e "${BOLD}[2/5] 行情数据API${NC}"
run_module "行情API" "test_02_market.py" "market"

echo ""
echo -e "${BOLD}[3/5] 交易API${NC}"
run_module "交易API" "test_03_trading.py" "trading"

echo ""
echo -e "${BOLD}[4/5] 策略/回测/资金费率${NC}"
run_module "策略回测" "test_04_strategy.py" "strategy"

echo ""
echo -e "${BOLD}[5/6] 前端检查${NC}"
run_module "前端" "test_05_frontend.py" "frontend"

echo ""
echo -e "${BOLD}[6/6] E2E 页面交互测试 (Playwright)${NC}"
echo -e "${BOLD}${CYAN}[E2E测试]${NC}"

E2E_OUTPUT=$(cd "$SCRIPT_DIR" && npx playwright test --config=playwright.config.ts --reporter=list 2>&1) || true

# 提取 E2E 统计 — Playwright 汇总行格式: "  N passed (Xs)" 或 "  N failed"
E2E_SUMMARY=$(echo "$E2E_OUTPUT" | grep -E "^\s+[0-9]+ (passed|failed)" | tail -2 | tr '\n' ' ')
E2E_PASSED=$(echo "$E2E_SUMMARY" | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+" || echo "0")
E2E_FAILED=$(echo "$E2E_SUMMARY" | grep -oE "[0-9]+ failed" | grep -oE "[0-9]+" || echo "0")
E2E_PASSED=${E2E_PASSED:-0}
E2E_FAILED=${E2E_FAILED:-0}

TOTAL_PASS=$((TOTAL_PASS + E2E_PASSED))
TOTAL_FAIL=$((TOTAL_FAIL + E2E_FAILED))

if [ "$E2E_FAILED" -gt 0 ]; then
    echo -e "  ${RED}✗ ${E2E_PASSED} passed, ${E2E_FAILED} failed${NC}"
    # 提取失败测试名
    E2E_FAILURES=$(echo "$E2E_OUTPUT" | grep -E "✘|FAIL|failed|Error" | head -30)
    BUGS="${BUGS}\n--- E2E页面交互 ---\n${E2E_FAILURES}\n"
    if [ "$(classify_failure "$E2E_OUTPUT")" = "env" ]; then
        ENV_ISSUES="${ENV_ISSUES}\n--- E2E页面交互 ---\n${E2E_FAILURES}\n"
    else
        APP_ISSUES="${APP_ISSUES}\n--- E2E页面交互 ---\n${E2E_FAILURES}\n"
    fi
    echo "====== E2E页面交互 ======" >> "$REPORT_FILE.detail"
    echo "$E2E_OUTPUT" >> "$REPORT_FILE.detail"
    echo "" >> "$REPORT_FILE.detail"
else
    echo -e "  ${GREEN}✓ ${E2E_PASSED} passed${NC}"
fi

# ============ 汇总 ============
echo ""
echo -e "${BOLD}${CYAN}══════════════════════════════════════════${NC}"
echo -e "${BOLD}   测试汇总${NC}"
echo -e "${BOLD}${CYAN}══════════════════════════════════════════${NC}"
echo -e "  ${GREEN}通过: ${TOTAL_PASS}${NC}"
echo -e "  ${RED}失败: ${TOTAL_FAIL}${NC}"
echo -e "  ${YELLOW}跳过: ${TOTAL_SKIP}${NC}"
TOTAL=$((TOTAL_PASS + TOTAL_FAIL + TOTAL_SKIP))
echo -e "  总计: ${TOTAL}"
if [ -n "$ENV_ISSUES" ]; then
    echo -e "  ${YELLOW}环境依赖问题: 有${NC}"
else
    echo -e "  ${GREEN}环境依赖问题: 无${NC}"
fi
if [ -n "$APP_ISSUES" ]; then
    echo -e "  ${YELLOW}业务逻辑问题: 有${NC}"
else
    echo -e "  ${GREEN}业务逻辑问题: 无${NC}"
fi

# 写入报告文件
{
    echo ""
    echo "通过: ${TOTAL_PASS}"
    echo "失败: ${TOTAL_FAIL}"
    echo "跳过: ${TOTAL_SKIP}"
    echo "总计: ${TOTAL}"
} >> "$REPORT_FILE"

if [ "$TOTAL_FAIL" -gt 0 ]; then
    echo ""
    echo -e "${BOLD}${RED}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${RED}║            BUG 清单                     ║${NC}"
    echo -e "${BOLD}${RED}╚══════════════════════════════════════════╝${NC}"
    echo -e "$BUGS"

    {
        echo ""
        echo "====== BUG 清单 ======"
        echo -e "$BUGS"
        echo ""
        echo "====== 环境依赖问题 ======"
        echo -e "$ENV_ISSUES"
        echo ""
        echo "====== 业务逻辑问题 ======"
        echo -e "$APP_ISSUES"
    } >> "$REPORT_FILE"

    echo ""
    echo -e "${YELLOW}详细错误日志: ${REPORT_FILE}.detail${NC}"
    echo -e "${YELLOW}请将此报告交给 Tonny 修复。${NC}"
else
    echo ""
    echo -e "${GREEN}${BOLD}✓ 全部测试通过！无 BUG。${NC}"
    echo "" >> "$REPORT_FILE"
    echo "✓ 全部测试通过！无 BUG。" >> "$REPORT_FILE"
fi

echo ""
echo -e "${YELLOW}报告已保存: ${REPORT_FILE}${NC}"
