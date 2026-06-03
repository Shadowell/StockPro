#!/bin/bash

# 一键重启脚本 - 优雅地关闭并重新启动前后端服务
# 使用方法: ./restart.sh 或 sh restart.sh

set -e  # 遇到错误立即退出

cd "$(dirname "$0")"

echo "================================"
echo "🔄 开始重启应用服务..."
echo "================================"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 1. 停止后端服务
echo -e "\n${YELLOW}📦 停止后端服务...${NC}"
if lsof -t -i :4445 > /dev/null 2>&1; then
    echo "  发现端口 4445 正在使用，正在关闭..."
    lsof -t -i :4445 | xargs kill -9 2>/dev/null || true
    echo -e "  ${GREEN}✓ 后端服务已停止${NC}"
else
    echo "  后端服务未运行"
fi

# 等待端口释放
sleep 1

# 2. 停止前端服务
echo -e "\n${YELLOW}🎨 停止前端服务...${NC}"
if lsof -t -i :4444 > /dev/null 2>&1; then
    echo "  发现端口 4444 正在使用，正在关闭..."
    lsof -t -i :4444 | xargs kill -9 2>/dev/null || true
    echo -e "  ${GREEN}✓ 前端服务已停止${NC}"
else
    echo "  前端服务未运行"
fi

# 等待端口释放
sleep 1

# 3. 清理可能的僵尸进程
echo -e "\n${YELLOW}🧹 清理僵尸进程...${NC}"
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
echo -e "  ${GREEN}✓ 清理完成${NC}"

# 等待清理完成
sleep 1

# 4. 创建日志目录（如果不存在）
echo -e "\n${YELLOW}📁 准备日志目录...${NC}"
mkdir -p logs
echo -e "  ${GREEN}✓ 日志目录就绪${NC}"

# 5. 启动后端服务
echo -e "\n${YELLOW}🚀 启动后端服务...${NC}"
cd backend

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "  创建虚拟环境..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# 启动 FastAPI
echo "  启动 FastAPI (端口 4445)..."
nohup uvicorn app.main:app --reload --port 4445 > ../logs/backend.log 2>&1 &
BACKEND_PID=$!
echo -e "  ${GREEN}✓ 后端服务已启动 (PID: $BACKEND_PID)${NC}"

cd ..

# 6. 启动前端服务
echo -e "\n${YELLOW}🚀 启动前端服务...${NC}"
cd frontend

# 检查依赖
if [ ! -d "node_modules" ]; then
    echo "  安装前端依赖..."
    npm install
fi

# 启动 Vite (固定端口 4444)
echo "  启动 Vite (端口 4444)..."
nohup npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
echo -e "  ${GREEN}✓ 前端服务已启动 (PID: $FRONTEND_PID)${NC}"

cd ..

# 7. 等待服务启动
echo -e "\n${YELLOW}⏳ 等待服务启动...${NC}"
sleep 3

# 8. 检查服务状态
echo -e "\n${YELLOW}🔍 检查服务状态...${NC}"

# 检查后端
if lsof -t -i :4445 > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓ 后端服务运行正常 (http://localhost:4445)${NC}"
else
    echo -e "  ${RED}✗ 后端服务启动失败${NC}"
    echo "  请查看日志: tail -f logs/backend.log"
fi

# 检查前端
if lsof -t -i :4444 > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓ 前端服务运行正常 (http://localhost:4444)${NC}"
else
    echo -e "  ${RED}✗ 前端服务启动失败${NC}"
    echo "  请查看日志: tail -f logs/frontend.log"
fi

# 9. 保存进程ID到文件
echo "$BACKEND_PID" > logs/backend.pid
echo "$FRONTEND_PID" > logs/frontend.pid

echo -e "\n================================"
echo -e "${GREEN}✨ 应用重启完成！${NC}"
echo "================================"
echo ""
echo "📝 服务信息:"
echo "  - 后端: http://localhost:4445"
echo "  - 前端: http://localhost:4444"
echo "  - API文档: http://localhost:4445/docs"
echo ""
echo "📋 日志文件:"
echo "  - 后端日志: tail -f logs/backend.log"
echo "  - 前端日志: tail -f logs/frontend.log"
echo ""
echo "🛑 停止服务:"
echo "  - 停止后端: kill \$(cat logs/backend.pid)"
echo "  - 停止前端: kill \$(cat logs/frontend.pid)"
echo "  - 停止全部: ./stop.sh"
echo ""
echo "🔄 重启服务:"
echo "  - 再次运行: ./restart.sh"
echo ""
