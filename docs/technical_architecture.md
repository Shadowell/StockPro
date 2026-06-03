# StockPro AI 技术架构文档

> 版本：2.0  
> 更新日期：2026-01-24

---

## 目录

1. [系统架构概览](#1-系统架构概览)
2. [技术栈](#2-技术栈)
3. [前端架构](#3-前端架构)
4. [后端架构](#4-后端架构)
5. [数据库设计](#5-数据库设计)
6. [API 接口文档](#6-api-接口文档)
7. [数据同步服务](#7-数据同步服务)
8. [页面与模块交互](#8-页面与模块交互)
9. [环境配置](#9-环境配置)
10. [部署说明](#10-部署说明)

---

## 1. 系统架构概览

### 1.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户浏览器 / Electron                            │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    React 前端应用 (Vite + TypeScript)                   │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │  │
│  │  │  Home   │  │ Market  │  │   AI    │  │Sentiment│  │    Data     │  │  │
│  │  │  Page   │  │Overview │  │Analysis │  │Analysis │  │  Center     │  │  │
│  │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └──────┬──────┘  │  │
│  └───────┼───────────┼───────────┼───────────┼───────────────┼──────────┘  │
│          │           │           │           │               │             │
└──────────┼───────────┼───────────┼───────────┼───────────────┼─────────────┘
           │           │           │           │               │
           ▼           ▼           ▼           ▼               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI 后端服务 (Python 3.11)                        │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                           API 路由层 (/api/v1)                         │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │   │
│  │  │stocks  │ │market  │ │charts  │ │  ai    │ │analysis│ │database│   │   │
│  │  └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘   │   │
│  └──────┼──────────┼──────────┼──────────┼──────────┼──────────┼────────┘   │
│         │          │          │          │          │          │            │
│  ┌──────▼──────────▼──────────▼──────────▼──────────▼──────────▼────────┐   │
│  │                          业务服务层 (Services)                         │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐  │   │
│  │  │StockService │ │MarketService│ │ChartService │ │ AIService       │  │   │
│  │  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └────────┬────────┘  │   │
│  │  ┌──────┴──────┐ ┌──────┴──────┐ ┌──────┴──────┐ ┌────────┴────────┐  │   │
│  │  │SectorService│ │SentimentSvc │ │RealtimeSyncS│ │SchedulerService│  │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                    │                    │                         │
└─────────┼────────────────────┼────────────────────┼─────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────────┐
│   SQLite 数据库  │  │   AkShare API   │  │       千问大模型 API            │
│   (本地缓存)     │  │   (股票数据)     │  │    (AI 分析 / 日历生成)         │
└─────────────────┘  └─────────────────┘  └─────────────────────────────────┘
```

### 1.2 数据流向

```
外部数据源                    后端服务                      前端展示
    │                           │                            │
    │  ┌───────────────────────┐│                            │
    │  │   定时同步服务         ││                            │
    │  │ (RealtimeSyncService) ││                            │
    │◄─┤  - 每10秒: 市场指数    ├┤                            │
    │  │  - 每30秒: 全部股票    ││                            │
    │  │  - 每2分钟: 热门概念   ││                            │
    │  └───────────┬───────────┘│                            │
    │              │            │                            │
    │              ▼            │                            │
    │  ┌───────────────────────┐│  ┌──────────────────────┐  │
    │  │    SQLite 本地数据库   │├──►    API 请求/响应     ├──►
    │  │  (缓存 + 历史数据)     ││  └──────────────────────┘  │
    │  └───────────────────────┘│                            │
    │                           │                            │
```

---

## 2. 技术栈

### 2.1 前端技术

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18.x | UI 框架 |
| TypeScript | 5.x | 类型安全 |
| Vite | 5.x | 构建工具 |
| Tailwind CSS | 3.x | 样式框架 |
| Zustand | 4.x | 状态管理 |
| React Router | 6.x | 路由管理 |
| Apache ECharts | 5.x | 图表展示 |
| Axios | 1.x | HTTP 客户端 |
| Lucide React | - | 图标库 |

### 2.2 后端技术

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.11 | 运行时 |
| FastAPI | 0.104+ | Web 框架 |
| Uvicorn | 0.40+ | ASGI 服务器 |
| AkShare | 1.x | 股票数据获取 |
| SQLite | 3.x | 本地数据库 |
| APScheduler | 3.x | 定时任务 |
| DashScope | - | 千问大模型 SDK |

### 2.3 外部服务

| 服务 | 用途 |
|------|------|
| 东方财富/同花顺 (via AkShare) | 实时行情、概念板块、热榜数据 |
| 千问大模型 (Qwen) | AI 股票分析、日历事件生成 |

---

## 3. 前端架构

### 3.1 页面结构

| 路由 | 页面组件 | 功能描述 |
|------|----------|----------|
| `/` | `Home.tsx` | 主页：市场指数、短线指标、热门板块、筛选股票列表 |
| `/market` | `MarketOverview.tsx` | 市场概览：热门概念、同花顺热榜、连板天梯 |
| `/sentiment` | `SentimentAnalysis.tsx` | 市场情绪分析：情绪仪表盘、涨跌统计、板块热度 |
| `/ai` | `AIStockAnalysis.tsx` | AI 智能分析：单股深度分析、评分、建议 |
| `/news` | `NewsCalendar.tsx` | 消息流：异动、并购重组、利好利空、财联社、雪球 |
| `/calendar` | `TradingCalendarPage.tsx` | 交易日历：重要事件、财报日期 |
| `/data` | `DataProcessingAnalysis.tsx` | 数据中心：数据库管理、批量导入 |

### 3.2 核心组件

| 组件 | 功能 |
|------|------|
| `MainLayout.tsx` | 全局布局：侧边栏导航、顶部指数行情、语言切换 |
| `ChartPanel.tsx` | 图表面板：日K线、分时图（带0轴线） |
| `StockTable.tsx` | 股票列表：筛选结果展示 |
| `SectorMonitor.tsx` | 板块监控：热门板块涨跌情况 |
| `NewsFeed.tsx` | 消息流：多 Tab 切换、自动滚动 |
| `DatabaseManager.tsx` | 数据库管理：表查询、SQL 执行 |

### 3.3 状态管理 (Zustand Store)

```typescript
interface AppState {
  // 基础状态
  language: 'zh' | 'en';
  selectedStock: Stock | null;
  
  // 市场数据
  stocks: Stock[];
  sectors: Sector[];
  marketOverview: MarketOverview | null;
  
  // 图表数据
  dailyData: DailyChartData[];
  intradayData: IntradayChartData[];
  
  // 加载状态
  isLoadingStocks: boolean;
  isLoadingSectors: boolean;
  isLoadingCharts: boolean;
  isLoadingMarket: boolean;
  
  // Actions
  fetchStocks: () => Promise<void>;
  fetchSectors: () => Promise<void>;
  fetchMarketOverview: () => Promise<void>;
  selectStock: (stock: Stock) => void;
}
```

---

## 4. 后端架构

### 4.1 目录结构

```
backend/app/
├── main.py                    # FastAPI 应用入口
├── api/
│   ├── api.py                 # 路由聚合
│   └── endpoints/             # API 端点
│       ├── stocks.py          # 股票筛选相关
│       ├── market.py          # 市场数据相关
│       ├── charts.py          # 图表数据
│       ├── ai.py              # AI 分析
│       ├── analysis.py        # 情绪分析
│       ├── database.py        # 数据库管理
│       ├── batch_import.py    # 批量导入
│       └── health.py          # 健康检查
├── services/                  # 业务服务层
│   ├── stock_service.py       # 股票筛选服务
│   ├── market_service.py      # 市场数据服务
│   ├── chart_service.py       # 图表数据服务
│   ├── ai_service.py          # AI 分析服务
│   ├── sentiment_service.py   # 情绪分析服务
│   ├── realtime_sync_service.py  # 实时同步服务
│   ├── scheduler_service.py   # 定时任务服务
│   └── batch_import_service.py   # 批量导入服务
├── db/
│   └── local_db.py            # 本地数据库操作
├── core/
│   └── config.py              # 配置管理
├── models/
│   └── schemas.py             # Pydantic 模型
└── utils/
    └── dashscope_utils.py     # 千问 API 工具
```

### 4.2 服务层职责

| 服务 | 文件 | 职责 |
|------|------|------|
| **StockService** | `stock_service.py` | 股票筛选策略、涨停板识别、ST 股过滤 |
| **MarketService** | `market_service.py` | 热门概念、同花顺热榜、连板天梯、消息流、日历 |
| **ChartService** | `chart_service.py` | 日 K 线数据、分时数据、技术指标计算 |
| **AIService** | `ai_service.py` | 千问大模型调用、股票分析、结构化输出 |
| **SentimentService** | `sentiment_service.py` | 市场情绪计算、涨跌家数统计 |
| **RealtimeSyncService** | `realtime_sync_service.py` | 后台数据同步、缓存更新 |
| **SchedulerService** | `scheduler_service.py` | 定时任务调度 |
| **BatchImportService** | `batch_import_service.py` | 历史数据批量导入 |

### 4.3 数据缓存策略

| 数据类型 | 缓存位置 | 更新频率 | 缓存时长 |
|----------|----------|----------|----------|
| 市场指数 | `market_indices_realtime` | 10秒 (交易时段) | 实时覆盖 |
| 全部股票 | `all_stocks_realtime` | 30秒 (交易时段) | 实时覆盖 |
| 热门概念 | `hot_concepts_realtime` | 2分钟 | 实时覆盖 |
| 同花顺热榜 | `ths_hot_realtime` | 2分钟 | 实时覆盖 |
| 短线指标 | `short_line_indices_realtime` | 2分钟 | 实时覆盖 |
| 概念龙头股 | `concept_leaders_cache` | 按需 + 2分钟 | 5分钟有效期 |
| 日 K 线 | `stock_history` | 按需 | 永久 |
| 基本面数据 | `stock_fundamentals` | 每日一次 | 永久 |

---

## 5. 数据库设计

### 5.1 数据库概览

**数据库类型**：SQLite (本地文件数据库)  
**文件位置**：
- macOS: `~/Library/Application Support/StockApp/stock_data.db`
- Windows: `~/AppData/Roaming/StockApp/stock_data.db`
- Linux: `~/.local/share/StockApp/stock_data.db`

### 5.2 表结构详解

#### 5.2.1 stock_history - 股票历史数据表

**用途**：存储股票日K线历史数据，用于图表展示和技术分析

```sql
CREATE TABLE stock_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,           -- 股票代码 (如: 600519)
    name TEXT NOT NULL,             -- 股票名称 (如: 贵州茅台)
    date DATE NOT NULL,             -- 交易日期
    open REAL,                      -- 开盘价
    high REAL,                      -- 最高价
    low REAL,                       -- 最低价
    close REAL,                     -- 收盘价
    volume BIGINT,                  -- 成交量 (股)
    turnover BIGINT,                -- 成交额 (元)
    UNIQUE(symbol, date)            -- 唯一约束: 每只股票每天一条记录
);
```

#### 5.2.2 stock_fundamentals - 股票基本面数据表

**用途**：存储股票基本面信息，用于筛选和展示

```sql
CREATE TABLE stock_fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,    -- 股票代码
    name TEXT NOT NULL,             -- 股票名称
    pe REAL,                        -- 市盈率
    pb REAL,                        -- 市净率
    dividend_yield REAL,            -- 股息率
    market_cap BIGINT,              -- 总市值
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 5.2.3 market_indices_realtime - 市场指数实时表

**用途**：存储大盘指数实时数据，用于顶部行情展示

```sql
CREATE TABLE market_indices_realtime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,      -- 指数名称 (如: 上证指数)
    code TEXT,                      -- 指数代码 (如: sh000001)
    price REAL,                     -- 当前点位
    change_amount REAL,             -- 涨跌点数
    change_percent REAL,            -- 涨跌幅 (%)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**数据示例**：
| name | code | price | change_amount | change_percent |
|------|------|-------|---------------|----------------|
| 上证指数 | sh000001 | 3250.00 | 25.50 | 0.79 |
| 深证成指 | sz399001 | 10500.00 | 80.00 | 0.77 |
| 创业板指 | sz399006 | 2100.00 | 15.00 | 0.72 |
| 科创50 | sh000688 | 980.00 | 8.00 | 0.82 |

#### 5.2.4 all_stocks_realtime - 全部股票实时表

**用途**：存储全市场A股实时行情数据，用于股票筛选和列表展示

```sql
CREATE TABLE all_stocks_realtime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,      -- 股票代码
    name TEXT NOT NULL,             -- 股票名称
    price REAL,                     -- 最新价
    change_percent REAL,            -- 涨跌幅 (%)
    volume REAL,                    -- 成交量 (手)
    amount REAL,                    -- 成交额 (元)
    turnover REAL,                  -- 换手率 (%)
    volume_ratio REAL,              -- 量比
    pe_dynamic REAL,                -- 动态市盈率
    pb REAL,                        -- 市净率
    total_market_cap REAL,          -- 总市值 (元)
    float_market_cap REAL,          -- 流通市值 (元)
    amplitude REAL,                 -- 振幅 (%)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 5.2.5 short_line_indices_realtime - 短线指标实时表

**用途**：存储短线交易核心指标，用于短线投资者决策参考

```sql
CREATE TABLE short_line_indices_realtime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,      -- 指标代码 (ZT/LB/MLB/DT/ZB/FBL)
    name TEXT NOT NULL,             -- 指标名称
    price REAL,                     -- 指标数值
    change_percent REAL,            -- 变化幅度 (预留)
    change_amount REAL,             -- 变化量 (预留)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**指标说明**：
| code | name | 计算方式 | 意义 |
|------|------|----------|------|
| ZT | 涨停数 | 当日涨停板股票数量 | 市场做多情绪 |
| LB | 连板数 | 连续涨停2板及以上数量 | 市场连续性热度 |
| MLB | 最高板 | 当日最高连板数 | 市场高度 |
| DT | 跌停数 | 当日跌停板股票数量 | 市场恐慌程度 |
| ZB | 炸板数 | 当日炸板股票数量 | 做多失败率 |
| FBL | 封板率 | ZT/(ZT+ZB)*100% | 涨停成功率 |

#### 5.2.6 hot_concepts_realtime - 热门概念实时表

**用途**：存储热门概念板块实时数据

```sql
CREATE TABLE hot_concepts_realtime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rank INTEGER,                   -- 排名
    name TEXT NOT NULL UNIQUE,      -- 概念名称
    change_percent REAL,            -- 涨跌幅 (%)
    inflow REAL,                    -- 流入资金 (元)
    outflow REAL,                   -- 流出资金 (元)
    net_inflow REAL                 -- 净流入资金 (元)
);
```

#### 5.2.7 hot_concepts_history - 热门概念历史表

**用途**：存储热门概念板块历史数据，用于趋势分析

```sql
CREATE TABLE hot_concepts_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,             -- 日期
    rank INTEGER,                   -- 当日排名
    name TEXT NOT NULL,             -- 概念名称
    change_percent REAL,            -- 涨跌幅 (%)
    inflow REAL,                    -- 流入资金
    outflow REAL,                   -- 流出资金
    net_inflow REAL,                -- 净流入
    UNIQUE(date, name)
);
```

#### 5.2.8 concept_leaders_cache - 概念龙头股缓存表

**用途**：缓存概念板块成分股数据，加速龙头股查询

```sql
CREATE TABLE concept_leaders_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_name TEXT NOT NULL,     -- 概念名称
    stock_code TEXT NOT NULL,       -- 股票代码
    stock_name TEXT NOT NULL,       -- 股票名称
    price REAL,                     -- 最新价
    change_percent REAL,            -- 涨跌幅 (%)
    amount REAL,                    -- 成交额
    turnover REAL,                  -- 换手率 (%)
    rank INTEGER,                   -- 排名 (按涨跌幅)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(concept_name, stock_code)
);

-- 索引: 加速按概念名称查询
CREATE INDEX idx_concept_leaders_name ON concept_leaders_cache(concept_name);
```

#### 5.2.9 ths_hot_realtime - 同花顺热榜实时表

**用途**：存储同花顺人气榜实时数据

```sql
CREATE TABLE ths_hot_realtime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rank INTEGER,                   -- 热度排名
    code TEXT NOT NULL UNIQUE,      -- 股票代码
    name TEXT NOT NULL,             -- 股票名称
    hot_value REAL,                 -- 热度值
    change_percent REAL,            -- 涨跌幅 (%)
    price REAL,                     -- 最新价
    reason TEXT,                    -- 上榜理由
    tags TEXT                       -- 相关板块标签
);
```

#### 5.2.10 ths_hot_history - 同花顺热榜历史表

**用途**：存储同花顺热榜历史数据

```sql
CREATE TABLE ths_hot_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,             -- 日期
    rank INTEGER,                   -- 排名
    code TEXT NOT NULL,             -- 股票代码
    name TEXT NOT NULL,             -- 股票名称
    hot_value REAL,                 -- 热度值
    change_percent REAL,            -- 涨跌幅
    price REAL,                     -- 价格
    reason TEXT,                    -- 上榜理由
    tags TEXT,                      -- 相关板块
    UNIQUE(date, code)
);
```

#### 5.2.11 lianban_ladder_history - 连板天梯历史表

**用途**：存储连板天梯数据，追踪连板晋级情况

```sql
CREATE TABLE lianban_ladder_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,             -- 当日日期
    prev_date DATE,                 -- 前一交易日
    level INTEGER NOT NULL,         -- 连板层级 (1板/2板/3板...)
    code TEXT NOT NULL,             -- 股票代码
    name TEXT NOT NULL,             -- 股票名称
    change_percent REAL,            -- 涨跌幅
    price REAL,                     -- 当前价格
    duration_days INTEGER,          -- 连板天数
    success_rate REAL,              -- 晋级成功率 (预留)
    reason TEXT,                    -- 涨停原因/所属行业
    UNIQUE(date, code)
);
```

#### 5.2.12 market_calendar - 市场日历事件表

**用途**：存储股市重要事件，如月末交易日、财报日期等

```sql
CREATE TABLE market_calendar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE, -- 事件唯一标识
    event_date DATE NOT NULL,       -- 事件日期
    title TEXT NOT NULL,            -- 事件标题
    category TEXT,                  -- 分类 (结算/财报/停牌等)
    market TEXT,                    -- 市场 (A股/港股等)
    source TEXT,                    -- 数据来源
    details TEXT,                   -- 详情 (JSON)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_date, title) ON CONFLICT REPLACE
);
```

#### 5.2.13 message_stream - 消息流表

**用途**：存储消息流数据（预留）

```sql
CREATE TABLE message_stream (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,    -- 消息时间
    source TEXT NOT NULL,           -- 来源 (财联社/雪球/东财等)
    title TEXT NOT NULL,            -- 标题
    content TEXT,                   -- 内容
    category TEXT,                  -- 分类 (异动/利好/利空等)
    importance INTEGER DEFAULT 1    -- 重要性 (1-5)
);
```

### 5.3 表关系图

```
┌─────────────────────┐     ┌─────────────────────┐
│ market_indices_     │     │ short_line_indices_ │
│ realtime           │     │ realtime            │
│ (大盘指数)          │     │ (短线指标)          │
└─────────────────────┘     └─────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│ all_stocks_realtime │────►│ stock_history       │
│ (全市场实时行情)     │     │ (历史K线)           │
└─────────────────────┘     └─────────────────────┘
         │
         │
         ▼
┌─────────────────────┐
│ stock_fundamentals  │
│ (基本面数据)        │
└─────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│ hot_concepts_       │────►│ hot_concepts_       │
│ realtime           │     │ history             │
│ (概念板块实时)       │     │ (概念板块历史)      │
└──────────┬──────────┘     └─────────────────────┘
           │
           ▼
┌─────────────────────┐
│ concept_leaders_    │
│ cache              │
│ (概念龙头股缓存)     │
└─────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│ ths_hot_realtime   │────►│ ths_hot_history     │
│ (热榜实时)          │     │ (热榜历史)          │
└─────────────────────┘     └─────────────────────┘

┌─────────────────────┐
│ lianban_ladder_    │
│ history            │
│ (连板天梯历史)       │
└─────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│ market_calendar    │     │ message_stream      │
│ (市场日历)          │     │ (消息流)            │
└─────────────────────┘     └─────────────────────┘
```

---

## 6. API 接口文档

### 6.1 Market 模块 - 市场数据

#### GET /api/v1/market/overview
**功能**：获取市场概览数据（指数、涨跌统计、成交量等）

**请求参数**：无

**响应示例**：
```json
{
  "indices": [
    { "name": "上证指数", "code": "sh000001", "price": 3250.00, "change_amount": 25.50, "change_percent": 0.79 }
  ],
  "is_open": true,
  "last_update": "2026-01-24T10:30:00",
  "sentiment": { "status": "偏多", "score": 65 },
  "volume": { "amount": 8500, "unit": "亿", "ratio": 1.2 },
  "advance_decline": { "up": 2800, "down": 1500, "flat": 200 }
}
```

#### GET /api/v1/market/short-line-indices
**功能**：获取短线指标数据

**响应示例**：
```json
[
  { "code": "ZT", "name": "涨停数", "price": 104, "change_percent": 0, "change_amount": 0 },
  { "code": "LB", "name": "连板数", "price": 11, "change_percent": 0, "change_amount": 0 },
  { "code": "MLB", "name": "最高板", "price": 5, "change_percent": 0, "change_amount": 0 },
  { "code": "DT", "name": "跌停数", "price": 0, "change_percent": 0, "change_amount": 0 },
  { "code": "ZB", "name": "炸板数", "price": 18, "change_percent": 0, "change_amount": 0 },
  { "code": "FBL", "name": "封板率", "price": 85.2, "change_percent": 0, "change_amount": 0 }
]
```

#### GET /api/v1/market/hot-concepts
**功能**：获取热门概念板块列表

**请求参数**：
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| limit | int | 否 | 50 | 返回数量限制 (1-200) |
| date | string | 否 | 当天 | 日期 (YYYY-MM-DD) |

**响应示例**：
```json
[
  {
    "rank": 1,
    "name": "BC电池",
    "change_percent": 8.56,
    "inflow": 7149000000,
    "outflow": 5000000000,
    "net_inflow": 2149000000,
    "leading_stock": "通威股份",
    "leading_stock_change": 10.0
  }
]
```

#### GET /api/v1/market/hot-concept/leaders
**功能**：获取概念板块龙头股列表（优先从缓存读取）

**请求参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 概念名称 |
| limit | int | 否 | 返回数量 (默认20) |

**响应示例**：
```json
[
  { "code": "920368", "name": "连城数控", "price": 47.16, "change_percent": 29.99, "amount": 1261000000, "turnover": 12.65 },
  { "code": "688223", "name": "晶科能源", "price": 6.90, "change_percent": 20.00, "amount": 3768000000, "turnover": 5.75 }
]
```

#### GET /api/v1/market/hot-concept/intraday
**功能**：获取概念板块分时K线

**请求参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 概念名称 |
| period | string | 否 | 周期 (默认"1") |

#### GET /api/v1/market/ths-hot
**功能**：获取同花顺人气榜

**请求参数**：
| 参数 | 类型 | 必填 | 默认值 |
|------|------|------|--------|
| limit | int | 否 | 100 |
| date | string | 否 | 当天 |

#### GET /api/v1/market/lianban-ladder
**功能**：获取连板天梯数据

**请求参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| date | string | 否 | 日期 (YYYYMMDD格式) |

**响应示例**：
```json
{
  "date": "2026-01-24",
  "prev_date": "2026-01-23",
  "levels": [
    {
      "prev_level": 4,
      "prev_count": 2,
      "prev_items": [...],
      "today_level": 5,
      "today_count": 1,
      "today_items": [
        { "code": "000001", "name": "平安银行", "change_percent": 10.0, "price": 12.50, "duration_days": 5 }
      ]
    }
  ]
}
```

#### GET /api/v1/market/message-stream
**功能**：获取消息流数据（异动、利好利空、财联社、雪球、东财）

**响应结构**：
```json
{
  "updated_at": "2026-01-24T10:30:00",
  "abnormal_news": [...],
  "mergers_news": [...],
  "good_news": [...],
  "bad_news": [...],
  "cailian_news": [...],
  "xueqiu_news": [...],
  "eastmoney_news": [...]
}
```

#### GET /api/v1/market/fundamentals/{symbol}
**功能**：获取单只股票基本面数据

### 6.2 Stocks 模块 - 股票筛选

#### GET /api/v1/stocks/filter
**功能**：获取策略筛选股票列表

**响应**：返回符合打板策略的股票列表

#### GET /api/v1/stocks/search
**功能**：搜索股票

**请求参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| q | string | 是 | 搜索关键词 (代码/名称) |
| limit | int | 否 | 返回数量 (默认20) |

### 6.3 Charts 模块 - 图表数据

#### GET /api/v1/charts/daily/{symbol}
**功能**：获取日K线数据

**响应示例**：
```json
[
  { "date": "2026-01-24", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.3, "volume": 1000000 }
]
```

#### GET /api/v1/charts/intraday/{symbol}
**功能**：获取分时数据

### 6.4 AI 模块 - 智能分析

#### POST /api/v1/ai/analyze-stock
**功能**：AI 单股深度分析

**请求体**：
```json
{ "symbol": "600519", "date": "2026-01-24" }
```

**响应示例**：
```json
{
  "symbol": "600519",
  "name": "贵州茅台",
  "score": 78,
  "recommendation": "买入",
  "summary": "...",
  "technical_analysis": { "trend": "上升", "support": 1800, "resistance": 1900 },
  "fundamental_analysis": { "pe_assessment": "合理", "growth_outlook": "稳定" },
  "risk_alerts": ["注意高位风险"],
  "catalysts": ["春节旺季预期"],
  "operation_advice": "..."
}
```

### 6.5 Analysis 模块 - 情绪分析

#### POST /api/v1/analysis/run-sentiment
**功能**：计算市场情绪因子

#### GET /api/v1/analysis/sentiment
**功能**：获取情绪榜单

### 6.6 Database 模块 - 数据管理

#### GET /api/v1/database/tables
**功能**：获取所有表信息

#### POST /api/v1/database/query
**功能**：执行 SQL 查询（只读）

### 6.7 Calendar 模块 - 交易日历

#### GET /api/v1/market/calendar
**功能**：获取市场日历事件

#### POST /api/v1/market/calendar/refresh
**功能**：刷新日历数据（从交易日历计算）

#### POST /api/v1/market/calendar/generate-with-ai
**功能**：使用 AI 生成日历事件

---

## 7. 数据同步服务

### 7.1 RealtimeSyncService

**位置**：`backend/app/services/realtime_sync_service.py`

**职责**：后台线程定期同步实时数据到本地数据库

#### 同步任务

| 任务 | 方法 | 频率 | 数据源 | 目标表 |
|------|------|------|--------|--------|
| 市场指数 | `_sync_market_indices()` | 10秒 | `ak.stock_zh_index_daily` | `market_indices_realtime` |
| 短线指标 | `_sync_short_line_indices()` | 10秒 | `ak.stock_zt_pool_em` 等 | `short_line_indices_realtime` |
| 全部股票 | `_sync_all_stocks()` | 30秒 | `ak.stock_zh_a_spot_em` | `all_stocks_realtime` |
| 热门概念 | `_sync_hot_concepts()` | 2分钟 | `ak.stock_board_concept_name_em` | `hot_concepts_realtime` |
| 概念龙头 | `_sync_concept_leaders()` | 2分钟 | `ak.stock_board_concept_cons_em` | `concept_leaders_cache` |
| 同花顺热榜 | `_sync_ths_hot()` | 2分钟 | `ak.stock_hot_rank_em` | `ths_hot_realtime` |
| 连板天梯 | `_sync_lianban_ladder()` | 2分钟 | `ak.stock_zt_pool_em` | `lianban_ladder_history` |

#### 时间控制

```python
def _is_market_hours(self) -> bool:
    """检查是否在交易时间"""
    now = datetime.now()
    # 周末不同步
    if now.weekday() >= 5:
        return False
    
    hour, minute = now.hour, now.minute
    time_val = hour * 60 + minute
    
    # 交易时间: 9:15-11:30, 13:00-15:05
    morning_start, morning_end = 9*60+15, 11*60+30
    afternoon_start, afternoon_end = 13*60, 15*60+5
    
    return (morning_start <= time_val <= morning_end) or \
           (afternoon_start <= time_val <= afternoon_end)
```

### 7.2 SchedulerService

**位置**：`backend/app/services/scheduler_service.py`

**职责**：APScheduler 定时任务调度

| 任务 | Cron 表达式 | 说明 |
|------|-------------|------|
| 股票历史同步 | `0 18 * * 1-5` | 每个交易日18:00 |
| 市场数据同步 | `*/30 9-15 * * 1-5` | 交易时段每30分钟 |
| 同花顺热榜同步 | `0 9,12,15 * * 1-5` | 每日9点、12点、15点 |

---

## 8. 页面与模块交互

### 8.1 首页 (Home)

```
┌─────────────────────────────────────────────────────────────┐
│                    顶部: 市场指数行情栏                       │
│  上证指数 3250.00 +0.79%  深证成指 10500 +0.77%  开市中      │
├─────────────────────────────────────────────────────────────┤
│  短线指标面板                                                │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐           │
│  │涨停数│ │连板数│ │最高板│ │跌停数│ │炸板数│ │封板率│          │
│  │ 104 │ │ 11  │ │  5  │ │  0  │ │ 18  │ │85.2%│          │
│  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘           │
├─────────────────────────────────────────────────────────────┤
│  快速洞察卡片                                                │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ 领涨板块     │ │ 市场情绪    │ │ 成交金额    │           │
│  │ BC电池 +8.5%│ │ 偏多 65分   │ │ 8500亿      │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
├─────────────────────────────────────────────────────────────┤
│  热门板块监控                     筛选股票列表                │
│  ┌────────────────────┐         ┌────────────────────────┐ │
│  │ BC电池   +8.56%    │         │ 代码  名称   涨跌  ...  │ │
│  │ TOPCon  +7.39%    │         │ ...                    │ │
│  │ HJT电池  +7.30%    │         │                        │ │
│  └────────────────────┘         └────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

数据流:
  1. 页面加载 → fetchMarketOverview() → GET /market/overview
  2. 10秒定时 → fetchMarketOverview() → 刷新指数
  3. 页面加载 → getShortLineIndices() → GET /market/short-line-indices
  4. 页面加载 → fetchStocks() → GET /stocks/filter
  5. 页面加载 → fetchSectors() → GET /sectors/hot
```

### 8.2 市场概览 (MarketOverview)

```
┌─────────────────────────────────────────────────────────────┐
│  Tab: [热门概念板块] [同花顺热榜] [连板天梯]     日期选择器    │
├─────────────────────────────────────────────────────────────┤
│  左侧: 概念/热榜列表              右侧: 详情面板               │
│  ┌────────────────────┐         ┌────────────────────────┐ │
│  │ 筛选: >=3% ▼       │         │ ● BC电池               │ │
│  ├────────────────────┤         │ [龙头股] [分时K线]      │ │
│  │ 1 BC电池  +8.56%  │ ──────► │ ┌────────────────────┐ │ │
│  │ 2 TOPCon +7.39%   │         │ │ 代码  名称  涨跌幅   │ │ │
│  │ 3 HJT电池 +7.30%  │         │ │ 920368 连城数控 +30%│ │ │
│  │ ...               │         │ │ 688223 晶科能源 +20%│ │ │
│  └────────────────────┘         │ └────────────────────┘ │ │
│                                 │ 点击股票 → 展开图表     │ │
│                                 │ ┌─────────┬─────────┐  │ │
│                                 │ │ 分时图  │  日K线   │  │ │
│                                 │ └─────────┴─────────┘  │ │
│                                 └────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

数据流:
  1. 页面加载 → getHotConcepts() → GET /market/hot-concepts
  2. 选择概念 → getHotConceptLeaders() → GET /market/hot-concept/leaders?name=BC电池
     (优先从 concept_leaders_cache 表读取，5分钟缓存)
  3. 选择概念 → getHotConceptIntradayKline() → GET /market/hot-concept/intraday
  4. 点击股票 → selectStock() → GET /charts/daily/{symbol} + /intraday/{symbol}
```

### 8.3 AI 智能分析 (AIStockAnalysis)

```
┌─────────────────────────────────────────────────────────────┐
│  搜索栏: [输入股票代码或名称...] [一键智能分析]               │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 综合评分: 78分   推荐: 买入                              ││
│  │ ┌─────────────┬─────────────┬─────────────┐            ││
│  │ │ 技术面 75   │ 基本面 80   │ 情绪面 72   │            ││
│  │ └─────────────┴─────────────┴─────────────┘            ││
│  ├─────────────────────────────────────────────────────────┤│
│  │ AI趋势判断: 短期看涨，中期震荡                           ││
│  │ 核心观点: xxx                                           ││
│  ├─────────────────────────────────────────────────────────┤│
│  │ 关键价位          风险提示                               ││
│  │ 支撑: 1800        [注意高位回调风险]                     ││
│  │ 阻力: 1900        [注意政策风险]                        ││
│  ├─────────────────────────────────────────────────────────┤│
│  │ 分时走势                        日K线                    ││
│  │ ┌─────────────────────┐    ┌─────────────────────┐     ││
│  │ │                     │    │                     │     ││
│  │ └─────────────────────┘    └─────────────────────┘     ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘

数据流:
  1. 输入搜索 → searchStocks() → GET /stocks/search?q=xxx
  2. 点击分析 → analyzeStockByAI() → POST /ai/analyze-stock
  3. 获取图表 → getDailyChart() + getIntradayChart()
```

### 8.4 情绪分析 (SentimentAnalysis)

```
┌─────────────────────────────────────────────────────────────┐
│  状态: ● 交易中                                              │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌─────────────────────────────────────┐ │
│  │ 情绪仪表盘     │  │ 核心指标卡片                        │ │
│  │    [偏多]      │  │ 上涨: 2800  涨停: 104  最高板: 5    │ │
│  │   ┌─────┐     │  │ 下跌: 1500  封板率: 85.2%          │ │
│  │   │ 65  │     │  │ 成交额: 8500亿  量比: 1.2          │ │
│  │   └─────┘     │  └─────────────────────────────────────┘ │
│  └───────────────┘                                          │
├─────────────────────────────────────────────────────────────┤
│  板块涨幅TOP10              连板天梯                         │
│  ┌────────────────────┐    ┌────────────────────┐          │
│  │ BC电池   ████ 8.5% │    │ 5板: 1只            │          │
│  │ TOPCon  ███ 7.4%  │    │ 4板: 2只            │          │
│  │ ...                │    │ 3板: 5只            │          │
│  └────────────────────┘    └────────────────────┘          │
└─────────────────────────────────────────────────────────────┘

数据流:
  1. 页面加载 → getMarketOverview() → GET /market/overview
  2. 页面加载 → getHotConcepts() → 获取板块涨幅
  3. 页面加载 → getLianbanLadder() → 获取连板数据
  4. 页面加载 → getThsHot() → 获取热门股票
  5. 1分钟定时刷新所有数据
```

---

## 9. 环境配置

### 9.1 后端环境变量

```bash
# .env 文件

# AI 服务配置
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
QWEN_STOCK_MODEL=qwen-plus

# 数据库配置 (可选，默认使用本地 SQLite)
# SUPABASE_URL=https://xxx.supabase.co
# SUPABASE_KEY=xxx

# 股票数据配置
AKSHARE_TIMEOUT=30

# 应用配置
BACKEND_CORS_ORIGINS=["http://localhost:4444"]
```

### 9.2 前端环境变量

```bash
# frontend/.env

# API 配置
VITE_API_URL=/api/v1
```

### 9.3 Vite 代理配置

```typescript
// frontend/vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:4445',
        changeOrigin: true
      }
    }
  }
})
```

---

## 10. 部署说明

### 10.1 本地开发

```bash
# 1. 启动后端
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 4445

# 2. 启动前端
cd frontend
npm install
npm run dev
```

### 10.2 生产部署

```bash
# 后端
uvicorn app.main:app --host 0.0.0.0 --port 4445 --workers 4

# 前端构建
npm run build
# 静态文件部署到 Nginx 或 CDN
```

### 10.3 Electron 打包

```bash
cd frontend
npm run build
npm run electron:build
```

---

## 附录

### A. AkShare 接口映射表

| 功能 | AkShare 接口 | 调用位置 |
|------|--------------|----------|
| A股实时行情 | `stock_zh_a_spot_em` | `RealtimeSyncService` |
| 日K线数据 | `stock_zh_a_hist` | `ChartService` |
| 分时数据 | `stock_zh_a_minute` | `ChartService` |
| 指数日K | `stock_zh_index_daily` | `RealtimeSyncService` |
| 概念板块列表 | `stock_board_concept_name_em` | `MarketService` |
| 概念板块成分 | `stock_board_concept_cons_em` | `MarketService` |
| 人气榜 | `stock_hot_rank_em` | `MarketService` |
| 涨停池 | `stock_zt_pool_em` | `RealtimeSyncService` |
| 跌停池 | `stock_zt_pool_dtgc_em` | `RealtimeSyncService` |
| 炸板池 | `stock_zt_pool_zbgc_em` | `RealtimeSyncService` |

### B. 错误码说明

| 错误码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 404 | 资源未找到 |
| 500 | 服务器内部错误 |
| 503 | 外部服务不可用 (AkShare 连接失败) |

---

> 文档维护：技术团队  
> 最后更新：2026-01-24
