# Market Overview 模块

## 页面与路由
- 路由：`/market`
- 目标：提供市场侧的三个高频看盘入口（热门概念资金、热榜、连板天梯）。

## Tab 设计
### 1) 热门概念板块
- 数据：`GET /api/v1/market/hot-concepts?limit=50`
- 字段：
  - `rank`：排名
  - `name`：概念名称
  - `change_percent`：涨跌幅
  - `inflow`：流入资金（亿元）
  - `outflow`：流出资金（亿元）
  - `net_inflow`：净流入（亿元）
- 数据源：优先使用 AkShare `stock_fund_flow_concept(symbol="即时")` 获取同花顺板块资金流数据，包含完整的资金流信息；若失败则使用 `stock_board_concept_name_em` 兜底（资金流字段为0）
- 展示：表格按涨幅排序，展示排名、概念名称、涨跌幅、流入/流出/净流入（单位：亿元）

### 2) 热榜
- 数据：`GET /api/v1/market/ths-hot?limit=100`
- 字段：
  - `rank`、`code`、`name`
  - `hot`：热度（若数据源不提供则为 0）
  - `change_percent`、`price`
  - `reason/tags`：上榜原因/标签（若可用）

### 3) 连板天梯
- 数据：`GET /api/v1/market/lianban-ladder?date=YYYYMMDD`
- 返回结构：
  - `date`：今日交易日（YYYYMMDD）
  - `prev_date`：昨日交易日（YYYYMMDD）
  - `levels[]`：按“昨日 N 板 → 今日 N+1 板”的层级对齐

## 后端实现位置
- Market endpoints：`backend/app/api/endpoints/market.py`
- MarketService：`backend/app/services/market_service.py`

