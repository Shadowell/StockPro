#!/bin/bash

# 停止服务脚本 - 优雅地关闭前后端服务
# 使用方法: ./stop.sh 或 sh stop.sh

cd "$(dirname "$0")"

echo "================================"
echo "🛑 停止应用服务..."
echo "================================"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 1. 从PID文件停止服务
echo -e "\n${YELLOW}📦 尝试从PID文件停止服务...${NC}"

if [ -f "logs/backend.pid" ]; then
    BACKEND_PID=$(cat logs/backend.pid)
    if ps -p $BACKEND_PID > /dev/null 2>&1; then
        echo "  停止后端服务 (PID: $BACKEND_PID)..."
        kill $BACKEND_PID 2>/dev/null || true
        echo -e "  ${GREEN}✓ 后端服务已停止${NC}"
    else
        echo "  后端进程不存在 (PID: $BACKEND_PID)"
    fi
    rm -f logs/backend.pid
fi

if [ -f "logs/frontend.pid" ]; then
    FRONTEND_PID=$(cat logs/frontend.pid)
    if ps -p $FRONTEND_PID > /dev/null 2>&1; then
        echo "  停止前端服务 (PID: $FRONTEND_PID)..."
        kill $FRONTEND_PID 2>/dev/null || true
        echo -e "  ${GREEN}✓ 前端服务已停止${NC}"
    else
        echo "  前端进程不存在 (PID: $FRONTEND_PID)"
    fi
    rm -f logs/frontend.pid
fi

# 2. 按端口停止服务
echo -e "\n${YELLOW}🔍 检查端口占用...${NC}"

# 停止后端服务 (端口 4445)
if lsof -t -i :4445 > /dev/null 2>&1; then
    echo "  发现端口 4445 正在使用，正在关闭..."
    lsof -t -i :4445 | xargs kill -9 2>/dev/null || true
    echo -e "  ${GREEN}✓ 端口 4445 已释放${NC}"
else
    echo "  端口 4445 未被占用"
fi

# 停止前端服务 (端口 4444)
if lsof -t -i :4444 > /dev/null 2>&1; then
    echo "  发现端口 4444 正在使用，正在关闭..."
    lsof -t -i :4444 | xargs kill -9 2>/dev/null || true
    echo -e "  ${GREEN}✓ 端口 4444 已释放${NC}"
else
    echo "  端口 4444 未被占用"
fi

# 3. 清理进程
echo -e "\n${YELLOW}🧹 清理相关进程...${NC}"
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
echo -e "  ${GREEN}✓ 清理完成${NC}"

# 等待清理完成
sleep 1

# 4. 最终检查
echo -e "\n${YELLOW}✅ 最终检查...${NC}"
if lsof -t -i :4445 > /dev/null 2>&1; then
    echo -e "  ${RED}⚠️  警告: 端口 4445 仍被占用${NC}"
else
    echo -e "  ${GREEN}✓ 端口 4445 已释放${NC}"
fi

if lsof -t -i :4444 > /dev/null 2>&1; then
    echo -e "  ${RED}⚠️  警告: 端口 4444 仍被占用${NC}"
else
    echo -e "  ${GREEN}✓ 端口 4444 已释放${NC}"
fi

echo -e "\n================================"
echo -e "${GREEN}✨ 所有服务已停止！${NC}"
echo "================================"
echo ""
echo "🔄 重新启动服务:"
echo "  ./restart.sh"
echo ""
