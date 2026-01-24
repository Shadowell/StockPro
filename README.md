# StockPro AI - 智能股票分析系统

> A股实时行情监控、智能选股、AI分析一体化平台

![Version](https://img.shields.io/badge/version-2.0-blue)
![Python](https://img.shields.io/badge/python-3.11-green)
![React](https://img.shields.io/badge/react-18-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 功能特性

### 核心功能

| 模块 | 功能 | 说明 |
|------|------|------|
| **首页看板** | 市场指数、短线指标、热门板块、筛选股票 | 一站式市场概览 |
| **市场概览** | 热门概念、同花顺热榜、连板天梯 | 板块轮动追踪 |
| **情绪分析** | 情绪仪表盘、涨跌统计、资金流向 | 市场情绪量化 |
| **AI 分析** | 单股深度分析、评分建议、风险提示 | 千问大模型驱动 |
| **消息流** | 异动监控、利好利空、财联社、雪球 | 多源消息聚合 |
| **数据中心** | 数据库管理、批量导入、历史回补 | 数据运维工具 |

### 短线指标

| 指标 | 说明 |
|------|------|
| 涨停数 | 当日涨停板股票数量 |
| 连板数 | 连续涨停2板及以上数量 |
| 最高板 | 当日最高连板数 |
| 跌停数 | 当日跌停板股票数量 |
| 炸板数 | 当日炸板股票数量 |
| 封板率 | 涨停成功率 = 涨停数/(涨停数+炸板数) |

### 数据缓存

- **市场指数**: 每10秒自动同步
- **全部股票**: 每30秒自动同步
- **热门概念**: 每2分钟自动同步
- **概念龙头股**: 5分钟本地缓存，查询更快

---

## 技术架构

```
Frontend (React + TypeScript + Vite)
          │
          ▼
Backend (FastAPI + Python 3.11)
          │
    ┌─────┴─────┐
    ▼           ▼
SQLite DB    AkShare API
(本地缓存)    (股票数据)
                │
                ▼
         千问大模型 API
         (AI 分析)
```

详细架构说明请参考 [技术架构文档](docs/technical_architecture.md)

---

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- npm 或 yarn

### 1. 克隆项目

```bash
git clone https://github.com/your-username/StockPro.git
cd StockPro
```

### 2. 启动后端

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入 QWEN_API_KEY

# 启动服务
uvicorn app.main:app --reload --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

### 4. 访问应用

打开浏览器访问 http://localhost:5173

---

## 配置说明

### 后端环境变量 (backend/.env)

```bash
# AI 服务配置 (必填，用于AI分析功能)
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxx
QWEN_STOCK_MODEL=qwen-plus

# 股票数据配置
AKSHARE_TIMEOUT=30

# CORS 配置
BACKEND_CORS_ORIGINS=["http://localhost:5173"]
```

### 前端环境变量 (frontend/.env)

```bash
VITE_API_URL=/api/v1
```

---

## 项目结构

```
StockPro/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── api/endpoints/      # API 端点
│   │   │   ├── market.py       # 市场数据 API
│   │   │   ├── stocks.py       # 股票筛选 API
│   │   │   ├── charts.py       # 图表数据 API
│   │   │   ├── ai.py           # AI 分析 API
│   │   │   └── ...
│   │   ├── services/           # 业务服务
│   │   │   ├── market_service.py
│   │   │   ├── realtime_sync_service.py  # 实时同步
│   │   │   ├── ai_service.py
│   │   │   └── ...
│   │   ├── db/
│   │   │   └── local_db.py     # 本地数据库
│   │   └── main.py             # 应用入口
│   └── requirements.txt
│
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── pages/              # 页面组件
│   │   │   ├── Home.tsx
│   │   │   ├── MarketOverview.tsx
│   │   │   ├── SentimentAnalysis.tsx
│   │   │   ├── AIStockAnalysis.tsx
│   │   │   └── ...
│   │   ├── components/         # 通用组件
│   │   ├── stores/             # 状态管理
│   │   ├── api/                # API 客户端
│   │   └── types/              # 类型定义
│   └── package.json
│
├── docs/                       # 文档
│   ├── technical_architecture.md  # 技术架构
│   ├── api.md                     # API 文档
│   └── modules/                   # 模块文档
│
└── README.md
```

---

## 文档

| 文档 | 说明 |
|------|------|
| [技术架构文档](docs/technical_architecture.md) | 系统架构、数据库设计、服务说明 |
| [API 接口文档](docs/api.md) | 完整的 API 接口说明 |
| [市场概览模块](docs/modules/market_overview.md) | 市场概览功能说明 |
| [AI 分析模块](docs/modules/ai_analysis.md) | AI 分析功能说明 |

---

## 数据库表说明

| 表名 | 用途 | 更新频率 |
|------|------|----------|
| `market_indices_realtime` | 大盘指数实时数据 | 10秒 |
| `short_line_indices_realtime` | 短线指标数据 | 10秒 |
| `all_stocks_realtime` | 全市场股票实时行情 | 30秒 |
| `hot_concepts_realtime` | 热门概念板块实时数据 | 2分钟 |
| `concept_leaders_cache` | 概念龙头股缓存 | 2分钟 |
| `ths_hot_realtime` | 同花顺热榜实时数据 | 2分钟 |
| `stock_history` | 股票日K线历史数据 | 按需 |
| `lianban_ladder_history` | 连板天梯历史数据 | 2分钟 |

完整表结构见 [技术架构文档](docs/technical_architecture.md#5-数据库设计)

---

## API 快速参考

```bash
# 市场概览
GET /api/v1/market/overview

# 短线指标
GET /api/v1/market/short-line-indices

# 热门概念
GET /api/v1/market/hot-concepts?limit=50

# 概念龙头股
GET /api/v1/market/hot-concept/leaders?name=BC电池&limit=20

# 日K线
GET /api/v1/charts/daily/600519

# AI分析
POST /api/v1/ai/analyze-stock
Body: {"symbol": "600519"}
```

完整 API 文档见 [api.md](docs/api.md)

---

## 常见问题

### Q: 短线指标没有数据？
A: 确保后端服务已启动，数据会在交易时段自动同步。非交易时段显示上一交易日数据。

### Q: 概念龙头股加载慢？
A: 首次查询会从 AkShare 获取数据并缓存到本地数据库，后续查询直接读取缓存，响应时间 <100ms。

### Q: AI 分析功能不可用？
A: 请检查 `backend/.env` 中的 `QWEN_API_KEY` 是否正确配置。

---

## 更新日志

### v2.0 (2026-01-24)
- 新增短线指标面板（涨停数、连板数、封板率等）
- 概念龙头股本地缓存，查询速度提升10倍
- 热门概念筛选增加 5%、8% 选项
- 优化数据同步服务，支持非交易时段展示历史数据
- 全面更新技术文档

### v1.0
- 基础功能实现

---

## 许可证

MIT License

---

## 贡献

欢迎提交 Issue 和 Pull Request！
