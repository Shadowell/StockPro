# StockPro 数据架构设计

## 概述

本文档描述 StockPro 应用的数据获取、存储和调度架构。所有数据都通过 AKShare 接口获取，按照不同的更新频率分为三类：天级、小时级和秒级数据。

## 核心原则

1. **数据库优先**：页面所有数据从本地数据库获取，不直接调用外部接口
2. **定时调度**：通过调度任务定期从 AKShare 获取数据并写入数据库
3. **接口-表一致**：AKShare 返回的字段尽量与数据库表字段保持一致
4. **实时数据特殊处理**：秒级数据通过 WebSocket 推送或内存缓存

---

## 一、数据分类与调度策略

### 1.1 天级数据（Daily）

每日收盘后更新一次，适用于历史类、统计类数据。

| 数据类型 | AKShare 接口 | 调度时间 | 数据库表 |
|----------|--------------|----------|----------|
| 股票历史K线 | `stock_zh_a_hist` | 16:00 | `stock_history` |
| 股票基本面 | `stock_zh_a_spot_em` | 16:00 | `stock_fundamentals` |
| 涨停股池 | `stock_zt_pool_em` | 16:00 | `lianban_ladder_history` |
| 连板数据 | `stock_zt_pool_lbc_em` | 16:00 | `lianban_ladder_history` |
| 龙虎榜 | `stock_lhb_detail_em` | 18:00 | `dragon_tiger_board` |
| 北向资金 | `stock_hsgt_hist_em` | 18:00 | `northbound_flow` |
| 融资融券 | `stock_margin_detail_szse/sse` | 19:00 | `margin_trading` |
| 财务报表 | `stock_profit_sheet_by_report_em` | 季度 | `financial_statements` |
| 股东数据 | `stock_gdfx_holding_detail_em` | 季度 | `shareholder_data` |
| 均线数据 | 计算生成 | 16:00 | `stock_ma_data` |
| 因子数据 | 计算生成 | 16:00 | `factor_data` |

### 1.2 小时级数据（Hourly）

交易时间内每小时更新，适用于排行、热度类数据。

| 数据类型 | AKShare 接口 | 调度时间 | 数据库表 |
|----------|--------------|----------|----------|
| 热门概念板块 | `stock_board_concept_name_em` | 每小时30分 | `hot_concepts_realtime` |
| 行业板块行情 | `stock_board_industry_name_em` | 每小时30分 | `sector_realtime` |
| 同花顺热榜 | `stock_hot_rank_ths` | 每小时30分 | `ths_hot_realtime` |
| 东财热度榜 | `stock_hot_rank_em` | 每小时30分 | `hot_stocks_realtime` |
| 板块资金流向 | `stock_sector_fund_flow_rank` | 每小时00分 | `sector_fund_flow` |
| 个股资金流向 | `stock_individual_fund_flow_rank` | 每小时00分 | `stock_fund_flow` |

### 1.3 秒级/分钟级数据（Realtime）

交易时间内高频更新，适用于实时行情类数据。

| 数据类型 | AKShare 接口 | 获取方式 | 存储方式 |
|----------|--------------|----------|----------|
| 全市场实时行情 | `stock_zh_a_spot_em` | 每分钟轮询 | `all_stocks_realtime` + 内存缓存 |
| 指数实时行情 | `stock_zh_index_spot_em` | 每分钟轮询 | `market_indices_realtime` |
| 分时数据 | `stock_intraday_em` | 按需请求 | 内存缓存 |
| 盘口异动 | `stock_changes_em` | 每30秒轮询 | WebSocket 推送 |
| 同花顺快讯 | `stock_info_global_ths` | 每分钟轮询 | `news_stream` |
| 财联社电报 | `stock_info_global_cls(symbol="全部")` | 每分钟轮询 | `news_stream` |

**资讯数据来源网站：**
- 同花顺实时快讯: https://news.10jqka.com.cn/realtimenews.html
- 财联社电报: https://www.cls.cn/telegraph

---

## 二、数据库表设计

### 2.1 现有核心表

```
├── stock_history          # 股票历史K线（天级）
├── stock_fundamentals     # 股票基本面（天级）
├── stock_ma_data          # 均线数据（天级）
├── lianban_ladder_history # 连板历史（天级）
├── hot_concepts_history   # 热门概念历史（天级）
├── hot_concepts_realtime  # 热门概念实时（小时级）
├── ths_hot_history        # 同花顺热榜历史（天级）
├── ths_hot_realtime       # 同花顺热榜实时（小时级）
├── all_stocks_realtime    # 全股票实时行情（分钟级）
├── market_indices_realtime# 指数实时行情（分钟级）
├── message_stream         # 消息流（分钟级）
├── factor_data            # 因子数据（天级）
└── factor_definitions     # 因子定义
```

### 2.2 需新增的表

#### 资讯新闻表 (news_stream)

```sql
CREATE TABLE IF NOT EXISTS news_stream (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,           -- cls/ths/em/sina/futu
    publish_time DATETIME NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    importance INTEGER DEFAULT 1,   -- 1-5
    category TEXT,                  -- 宏观/公司/行业/市场
    related_stocks TEXT,            -- 关联股票,逗号分隔
    is_read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, publish_time, content)
);

CREATE INDEX idx_news_publish_time ON news_stream(publish_time DESC);
CREATE INDEX idx_news_source ON news_stream(source);
```

#### 板块行情实时表 (sector_realtime)

```sql
CREATE TABLE IF NOT EXISTS sector_realtime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_type TEXT NOT NULL,      -- industry/concept/geo
    sector_code TEXT,
    sector_name TEXT NOT NULL,
    price REAL,
    change_percent REAL,
    change_amount REAL,
    volume REAL,
    turnover REAL,
    total_market_cap REAL,
    leader_code TEXT,
    leader_name TEXT,
    leader_change REAL,
    up_count INTEGER,
    down_count INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sector_type, sector_name)
);

CREATE INDEX idx_sector_type ON sector_realtime(sector_type);
```

#### 资金流向表 (fund_flow_daily)

```sql
CREATE TABLE IF NOT EXISTS fund_flow_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    flow_type TEXT NOT NULL,        -- stock/industry/concept
    main_inflow REAL,
    main_outflow REAL,
    main_net REAL,
    super_large_inflow REAL,
    super_large_outflow REAL,
    super_large_net REAL,
    large_inflow REAL,
    large_outflow REAL,
    large_net REAL,
    medium_inflow REAL,
    medium_outflow REAL,
    medium_net REAL,
    small_inflow REAL,
    small_outflow REAL,
    small_net REAL,
    UNIQUE(date, symbol, flow_type)
);

CREATE INDEX idx_fund_flow_date ON fund_flow_daily(date);
CREATE INDEX idx_fund_flow_symbol ON fund_flow_daily(symbol);
```

#### 龙虎榜表 (dragon_tiger_board)

```sql
CREATE TABLE IF NOT EXISTS dragon_tiger_board (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    close_price REAL,
    change_percent REAL,
    turnover_rate REAL,
    net_buy REAL,
    buy_amount REAL,
    sell_amount REAL,
    reason TEXT,                    -- 上榜原因
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, code, reason)
);

CREATE INDEX idx_dtb_date ON dragon_tiger_board(date);
```

#### 北向资金流向表 (northbound_flow)

```sql
CREATE TABLE IF NOT EXISTS northbound_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    channel TEXT NOT NULL,          -- 沪股通/深股通/北向
    buy_amount REAL,
    sell_amount REAL,
    net_buy REAL,
    total_buy REAL,
    total_sell REAL,
    total_net REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, channel)
);

CREATE INDEX idx_nb_date ON northbound_flow(date);
```

---

## 三、数据同步服务架构

### 3.1 服务层结构

```
backend/app/services/
├── scheduler_service.py      # 调度服务（APScheduler）
├── data_sync_service.py      # 数据同步基础服务
├── daily_sync_service.py     # 天级数据同步
├── hourly_sync_service.py    # 小时级数据同步
├── realtime_sync_service.py  # 实时数据同步
├── news_sync_service.py      # 资讯同步服务
└── websocket_service.py      # WebSocket 推送服务
```

### 3.2 调度配置

```python
# scheduler_service.py

class SchedulerService:
    async def initialize(self):
        # ========== 天级任务 ==========
        
        # 股票历史数据 - 每天16:00
        self.scheduler.add_job(
            func=self._sync_stock_history,
            trigger=CronTrigger(hour=16, minute=0),
            id='daily_stock_history'
        )
        
        # 涨停连板数据 - 每天16:30
        self.scheduler.add_job(
            func=self._sync_zt_pool,
            trigger=CronTrigger(hour=16, minute=30),
            id='daily_zt_pool'
        )
        
        # 龙虎榜数据 - 每天18:00
        self.scheduler.add_job(
            func=self._sync_dragon_tiger,
            trigger=CronTrigger(hour=18, minute=0),
            id='daily_dragon_tiger'
        )
        
        # 北向资金 - 每天18:30
        self.scheduler.add_job(
            func=self._sync_northbound,
            trigger=CronTrigger(hour=18, minute=30),
            id='daily_northbound'
        )
        
        # ========== 小时级任务 ==========
        
        # 板块行情 - 交易时间每小时30分
        self.scheduler.add_job(
            func=self._sync_sector_realtime,
            trigger=CronTrigger(minute=30, hour='9-15', day_of_week='mon-fri'),
            id='hourly_sector'
        )
        
        # 热度排行 - 交易时间每小时00分
        self.scheduler.add_job(
            func=self._sync_hot_rank,
            trigger=CronTrigger(minute=0, hour='9-15', day_of_week='mon-fri'),
            id='hourly_hot_rank'
        )
        
        # 资金流向 - 交易时间每小时15分
        self.scheduler.add_job(
            func=self._sync_fund_flow,
            trigger=CronTrigger(minute=15, hour='9-15', day_of_week='mon-fri'),
            id='hourly_fund_flow'
        )
        
        # ========== 分钟级任务 ==========
        
        # 全市场行情 - 交易时间每分钟
        self.scheduler.add_job(
            func=self._sync_all_stocks_realtime,
            trigger=CronTrigger(second=0, hour='9-15', day_of_week='mon-fri'),
            id='minute_stocks'
        )
        
        # 快讯资讯 - 每分钟
        self.scheduler.add_job(
            func=self._sync_news,
            trigger=CronTrigger(second=30),
            id='minute_news'
        )
```

### 3.3 数据同步流程

```
┌─────────────────────────────────────────────────────────────┐
│                      调度器 (APScheduler)                    │
├─────────────────────────────────────────────────────────────┤
│  触发时间到达                                                 │
│      ↓                                                       │
│  ┌─────────────────────┐                                     │
│  │   同步服务           │                                     │
│  │   - 检查是否交易日   │                                     │
│  │   - 调用 AKShare    │                                     │
│  │   - 数据清洗转换     │                                     │
│  │   - 写入数据库       │                                     │
│  └─────────────────────┘                                     │
│      ↓                                                       │
│  ┌─────────────────────┐                                     │
│  │   SQLite 数据库     │                                     │
│  │   - 实时表          │                                     │
│  │   - 历史表          │                                     │
│  └─────────────────────┘                                     │
│      ↓                                                       │
│  ┌─────────────────────┐                                     │
│  │   API 接口          │                                     │
│  │   - 从数据库读取    │                                     │
│  │   - 返回给前端      │                                     │
│  └─────────────────────┘                                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、API 设计规范

### 4.1 数据获取 API

所有数据获取 API 都应从数据库读取，不直接调用 AKShare：

```python
# ❌ 错误做法 - 直接调用 AKShare
@router.get("/stocks/realtime")
async def get_stocks_realtime():
    df = ak.stock_zh_a_spot_em()  # 不推荐
    return df.to_dict('records')

# ✅ 正确做法 - 从数据库读取
@router.get("/stocks/realtime")
async def get_stocks_realtime():
    return db.get_all_stocks_realtime()  # 从数据库读取
```

### 4.2 API 路径规范

```
/api/v1/
├── market/                      # 市场数据
│   ├── indices                  # 指数行情
│   ├── stocks                   # 全市场行情
│   └── summary                  # 市场总览
├── sectors/                     # 板块数据
│   ├── industry                 # 行业板块
│   ├── concept                  # 概念板块
│   └── geo                      # 地域板块
├── stocks/{symbol}/             # 个股数据
│   ├── history                  # 历史K线
│   ├── fundamentals             # 基本面
│   ├── fund-flow                # 资金流向
│   └── factors                  # 因子数据
├── hot/                         # 热度数据
│   ├── concepts                 # 热门概念
│   ├── stocks                   # 热门股票
│   └── ths                      # 同花顺热榜
├── news/                        # 资讯数据
│   ├── stream                   # 快讯流
│   └── notices                  # 公告
└── pulse/                       # 复盘中心
    ├── lianban-history          # 连板历史
    └── daily-stats              # 每日统计
```

---

## 五、WebSocket 实时推送

对于秒级更新的数据，使用 WebSocket 推送：

### 5.1 WebSocket 事件

| 事件类型 | 频率 | 数据内容 |
|----------|------|----------|
| `stock_tick` | 每秒 | 股票实时价格变动 |
| `index_tick` | 每秒 | 指数实时行情 |
| `alert` | 实时 | 盘口异动提醒 |
| `news` | 实时 | 快讯推送 |

### 5.2 客户端订阅

```javascript
// 前端订阅示例
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onopen = () => {
  // 订阅股票实时行情
  ws.send(JSON.stringify({
    action: 'subscribe',
    channels: ['stock_tick', 'alert']
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  switch(data.type) {
    case 'stock_tick':
      updateStockPrice(data.payload);
      break;
    case 'alert':
      showAlert(data.payload);
      break;
  }
};
```

---

## 六、缓存策略

### 6.1 内存缓存（Redis/内存字典）

- 全市场实时行情（1分钟TTL）
- 分时数据（5分钟TTL）
- 热度排行（10分钟TTL）

### 6.2 本地数据库缓存

- 历史K线数据
- 财务数据
- 因子数据

### 6.3 缓存更新策略

```python
# 写入时更新缓存
def update_stocks_realtime(stocks: List[Dict]):
    # 1. 写入数据库
    db.update_all_stocks_realtime(stocks)
    
    # 2. 更新内存缓存
    cache.set('stocks_realtime', stocks, ttl=60)
    
    # 3. 推送 WebSocket
    await ws_manager.broadcast('stock_tick', stocks)
```

---

## 七、错误处理与重试

### 7.1 AKShare 调用重试

```python
import time
from functools import wraps

def retry_on_failure(max_retries=3, delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i < max_retries - 1:
                        time.sleep(delay * (i + 1))
                        continue
                    raise e
        return wrapper
    return decorator

@retry_on_failure(max_retries=3, delay=2)
def fetch_stock_data():
    return ak.stock_zh_a_spot_em()
```

### 7.2 同步状态记录

```sql
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT NOT NULL,
    sync_date DATE NOT NULL,
    status TEXT NOT NULL,           -- success/failed/running
    records_count INTEGER DEFAULT 0,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_name, sync_date)
);
```

---

## 八、监控与告警

### 8.1 关键指标监控

- 同步任务执行状态
- 数据更新延迟
- 数据库存储空间
- API 响应时间

### 8.2 告警规则

- 同步任务连续失败 3 次
- 数据更新延迟超过 30 分钟
- API 响应时间超过 5 秒
