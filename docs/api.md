# StockPro AI API 接口文档

> 版本：2.0  
> 基础路径：`/api/v1`  
> 更新日期：2026-01-24

---

## 目录

1. [Market - 市场数据](#1-market---市场数据)
2. [Stocks - 股票筛选](#2-stocks---股票筛选)
3. [Charts - 图表数据](#3-charts---图表数据)
4. [AI - 智能分析](#4-ai---智能分析)
5. [Analysis - 情绪分析](#5-analysis---情绪分析)
6. [Database - 数据管理](#6-database---数据管理)
7. [Admin - 管理接口](#7-admin---管理接口)
8. [数据源速查表](#8-数据源速查表)

---

## 1. Market - 市场数据

### 1.1 GET /market/overview

获取市场概览数据（大盘指数、涨跌统计、成交量、市场情绪）

**请求参数**：无

**响应示例**：
```json
{
  "indices": [
    {
      "name": "上证指数",
      "code": "sh000001",
      "price": 3250.00,
      "change_amount": 25.50,
      "change_percent": 0.79
    },
    {
      "name": "深证成指",
      "code": "sz399001",
      "price": 10500.00,
      "change_amount": 80.00,
      "change_percent": 0.77
    },
    {
      "name": "创业板指",
      "code": "sz399006",
      "price": 2100.00,
      "change_amount": 15.00,
      "change_percent": 0.72
    },
    {
      "name": "科创50",
      "code": "sh000688",
      "price": 980.00,
      "change_amount": 8.00,
      "change_percent": 0.82
    }
  ],
  "is_open": true,
  "last_update": "2026-01-24T10:30:00",
  "sentiment": {
    "status": "偏多",
    "score": 65
  },
  "volume": {
    "amount": 8500,
    "unit": "亿",
    "ratio": 1.2,
    "sh_amount": 4200,
    "sz_amount": 4000,
    "bj_amount": 300
  },
  "advance_decline": {
    "up": 2800,
    "down": 1500,
    "flat": 200,
    "limit_up": 104,
    "limit_down": 0
  }
}
```

**数据来源**：
- 指数数据：`market_indices_realtime` 表 (优先) → AkShare `stock_zh_index_daily` (兜底)
- 股票统计：`all_stocks_realtime` 表 (优先) → AkShare `stock_zh_a_spot_em` (兜底)

---

### 1.2 GET /market/short-line-indices

获取短线交易核心指标

**请求参数**：无

**响应示例**：
```json
[
  {
    "code": "ZT",
    "name": "涨停数",
    "price": 104,
    "change_percent": 0,
    "change_amount": 0,
    "updated_at": "2026-01-24T10:30:00"
  },
  {
    "code": "LB",
    "name": "连板数",
    "price": 11,
    "change_percent": 0,
    "change_amount": 0,
    "updated_at": "2026-01-24T10:30:00"
  },
  {
    "code": "MLB",
    "name": "最高板",
    "price": 5,
    "change_percent": 0,
    "change_amount": 0,
    "updated_at": "2026-01-24T10:30:00"
  },
  {
    "code": "DT",
    "name": "跌停数",
    "price": 0,
    "change_percent": 0,
    "change_amount": 0,
    "updated_at": "2026-01-24T10:30:00"
  },
  {
    "code": "ZB",
    "name": "炸板数",
    "price": 18,
    "change_percent": 0,
    "change_amount": 0,
    "updated_at": "2026-01-24T10:30:00"
  },
  {
    "code": "FBL",
    "name": "封板率",
    "price": 85.2,
    "change_percent": 0,
    "change_amount": 0,
    "updated_at": "2026-01-24T10:30:00"
  }
]
```

**指标说明**：
| code | name | 计算方式 |
|------|------|----------|
| ZT | 涨停数 | 当日涨停板股票数量 |
| LB | 连板数 | 连续涨停2板及以上数量 |
| MLB | 最高板 | 当日最高连板数 |
| DT | 跌停数 | 当日跌停板股票数量 |
| ZB | 炸板数 | 当日炸板股票数量 |
| FBL | 封板率 | ZT/(ZT+ZB)*100% |

**数据来源**：`short_line_indices_realtime` 表 (后台每10秒同步)

---

### 1.3 GET /market/hot-concepts

获取热门概念板块列表

**请求参数**：
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| limit | int | 否 | 50 | 返回数量 (1-200) |
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
  },
  {
    "rank": 2,
    "name": "钙钛矿电池",
    "change_percent": 8.24,
    "inflow": 6800000000,
    "outflow": 5200000000,
    "net_inflow": 1600000000,
    "leading_stock": "协鑫科技",
    "leading_stock_change": 9.5
  }
]
```

**数据来源**：
- 实时数据：`hot_concepts_realtime` 表
- 历史数据：`hot_concepts_history` 表
- 原始接口：AkShare `stock_board_concept_name_em`

---

### 1.4 GET /market/hot-concept/leaders

获取概念板块龙头股列表 (优先从缓存读取)

**请求参数**：
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| name | string | 是 | - | 概念名称 |
| limit | int | 否 | 20 | 返回数量 (1-200) |
| date | string | 否 | - | 日期 |

**响应示例**：
```json
[
  {
    "code": "920368",
    "name": "连城数控",
    "price": 47.16,
    "change_percent": 29.99,
    "amount": 1261000000,
    "turnover": 12.65,
    "rank": 1
  },
  {
    "code": "688223",
    "name": "晶科能源",
    "price": 6.90,
    "change_percent": 20.00,
    "amount": 3768000000,
    "turnover": 5.75,
    "rank": 2
  }
]
```

**缓存策略**：
1. 优先从 `concept_leaders_cache` 表读取
2. 缓存有效期：5分钟
3. 缓存过期或不存在时，调用 AkShare `stock_board_concept_cons_em` 并存入缓存

---

### 1.5 GET /market/hot-concept/intraday

获取概念板块分时K线数据

**请求参数**：
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| name | string | 是 | - | 概念名称 |
| period | string | 否 | "1" | K线周期 |
| date | string | 否 | - | 日期 |

**响应示例**：
```json
[
  {
    "time": "2026-01-24 09:30",
    "open": 100.0,
    "high": 100.5,
    "low": 99.8,
    "close": 100.3,
    "volume": 1000000
  }
]
```

**数据来源**：AkShare `stock_board_concept_hist_min_em`

---

### 1.6 GET /market/ths-hot

获取同花顺人气榜

**请求参数**：
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| limit | int | 否 | 100 | 返回数量 (1-200) |
| date | string | 否 | 当天 | 日期 |

**响应示例**：
```json
[
  {
    "rank": 1,
    "code": "600519",
    "name": "贵州茅台",
    "hot": 985000,
    "change_percent": 2.5,
    "price": 1850.00,
    "reason": "白酒龙头，机构重仓",
    "tags": "白酒,食品饮料"
  }
]
```

**数据来源**：
- 实时数据：`ths_hot_realtime` 表
- 历史数据：`ths_hot_history` 表
- 原始接口：AkShare `stock_hot_rank_em`

---

### 1.7 GET /market/lianban-ladder

获取连板天梯数据

**请求参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| date | string | 否 | 日期 (YYYYMMDD格式)，默认当天 |

**响应示例**：
```json
{
  "date": "2026-01-24",
  "prev_date": "2026-01-23",
  "levels": [
    {
      "prev_level": 4,
      "prev_count": 2,
      "prev_items": [
        { "code": "000001", "name": "平安银行", "change_percent": 10.0 }
      ],
      "today_level": 5,
      "today_count": 1,
      "today_items": [
        {
          "code": "000001",
          "name": "平安银行",
          "change_percent": 10.0,
          "price": 12.50,
          "duration_days": 5,
          "success_rate": null,
          "reason": "金融"
        }
      ]
    },
    {
      "prev_level": 3,
      "prev_count": 5,
      "prev_items": [...],
      "today_level": 4,
      "today_count": 2,
      "today_items": [...]
    }
  ]
}
```

**数据来源**：
- 历史数据：`lianban_ladder_history` 表
- 原始接口：AkShare `stock_zt_pool_em`

---

### 1.8 GET /market/message-stream

获取消息流数据

**请求参数**：
| 参数 | 类型 | 必填 | 默认值 |
|------|------|------|--------|
| limit | int | 否 | 50 |

**响应示例**：
```json
{
  "updated_at": "2026-01-24T10:30:00",
  "abnormal_news": [
    {
      "code": "600000",
      "name": "浦发银行",
      "change_percent": 10.0,
      "direction": "UP",
      "rule_id": "sh_sz_main_10",
      "threshold_pct": 10
    }
  ],
  "mergers_news": [
    {
      "id": "xxx",
      "time": "2026-01-24",
      "title": "关于重大资产重组的公告",
      "source": "公告",
      "related_stocks": [{"code": "600000", "name": "浦发银行"}]
    }
  ],
  "good_news": [
    {
      "id": "xxx",
      "time": "09:00",
      "title": "央行降准0.5个百分点",
      "source": "财联社"
    }
  ],
  "bad_news": [...],
  "cailian_news": [
    {
      "time": "10:30:00",
      "title": "【快讯】xxx",
      "content": "详细内容...",
      "source": "财联社电报"
    }
  ],
  "xueqiu_news": [...],
  "eastmoney_news": [...]
}
```

**数据来源**：
- 异动数据：根据 `all_stocks_realtime` 实时计算
- 财联社：AkShare `stock_info_global_cls`
- 雪球：AkShare `stock_hot_tweet_xq`
- 东财：AkShare `stock_info_global_em`

---

### 1.9 GET /market/fundamentals/{symbol}

获取单只股票基本面数据

**路径参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| symbol | string | 股票代码 |

**响应示例**：
```json
{
  "code": "600519",
  "name": "贵州茅台",
  "price": 1850.00,
  "change_percent": 2.5,
  "pe_dynamic": 35.6,
  "pb": 12.3,
  "total_market_cap": 2320000000000,
  "float_market_cap": 2100000000000,
  "volume_ratio": 1.2,
  "turnover": 0.5,
  "amplitude": 3.2
}
```

---

### 1.10 GET /market/calendar

获取市场日历事件

**请求参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| start | string | 否 | 开始日期 (YYYY-MM-DD) |
| end | string | 否 | 结束日期 (YYYY-MM-DD) |
| limit | int | 否 | 返回数量 (默认200) |

**响应示例**：
```json
[
  {
    "event_key": "month_end:2026-01-30",
    "event_date": "2026-01-30",
    "title": "2026-01 月末交易日",
    "category": "结算",
    "market": "A",
    "source": "computed",
    "details": null
  }
]
```

**数据来源**：`market_calendar` 表

---

### 1.11 POST /market/calendar/refresh

刷新市场日历数据

**请求参数**：
| 参数 | 类型 | 必填 | 默认值 |
|------|------|------|--------|
| months | int | 否 | 6 |

**响应示例**：
```json
{
  "success": true,
  "count": 120,
  "message": "Refreshed 120 calendar events"
}
```

---

### 1.12 POST /market/calendar/generate-with-ai

使用AI生成日历事件

**请求参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| start_date | string | 是 | 开始日期 |
| end_date | string | 是 | 结束日期 |

---

## 2. Stocks - 股票筛选

### 2.1 GET /stocks/filter

获取策略筛选股票列表

**请求参数**：无

**响应示例**：
```json
{
  "stocks": [
    {
      "code": "000001",
      "name": "平安银行",
      "current_price": 12.50,
      "change_percent": 5.5,
      "volume": 1000000,
      "market_cap": 250000000000,
      "is_short": true
    }
  ],
  "filter_time": "2026-01-24T10:30:00"
}
```

**筛选策略**：
- 涨幅 >= 5%
- 非ST股
- 非停牌
- 市值 > 50亿

---

### 2.2 GET /stocks/search

搜索股票

**请求参数**：
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| q | string | 是 | - | 搜索关键词 |
| limit | int | 否 | 20 | 返回数量 |

**响应示例**：
```json
[
  {
    "code": "600519",
    "name": "贵州茅台"
  },
  {
    "code": "000568",
    "name": "泸州老窖"
  }
]
```

**数据来源**：
- `stock_fundamentals` 表
- `stock_history` 表
- `all_stocks_realtime` 表

---

## 3. Charts - 图表数据

### 3.1 GET /charts/daily/{symbol}

获取日K线数据

**路径参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| symbol | string | 股票代码 |

**响应示例**：
```json
[
  {
    "date": "2026-01-24",
    "open": 1800.00,
    "high": 1860.00,
    "low": 1795.00,
    "close": 1850.00,
    "volume": 5000000,
    "turnover": 9200000000
  }
]
```

**数据来源**：
- 优先：`stock_history` 表
- 兜底：AkShare `stock_zh_a_hist`

---

### 3.2 GET /charts/intraday/{symbol}

获取分时数据

**路径参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| symbol | string | 股票代码 |

**响应示例**：
```json
[
  {
    "time": "09:30",
    "price": 1820.00,
    "volume": 10000,
    "avg_price": 1820.00
  }
]
```

**数据来源**：AkShare `stock_zh_a_minute`

---

## 4. AI - 智能分析

### 4.1 POST /ai/analyze-stock

AI单股深度分析

**请求体**：
```json
{
  "symbol": "600519",
  "date": "2026-01-24"
}
```

**响应示例**：
```json
{
  "symbol": "600519",
  "name": "贵州茅台",
  "score": 78,
  "recommendation": "买入",
  "summary": "贵州茅台作为白酒龙头，基本面稳健，技术面处于上升趋势...",
  "technical_analysis": {
    "trend": "上升趋势",
    "trend_judgment": "短期看涨",
    "support_levels": [1800, 1750],
    "resistance_levels": [1900, 1950],
    "volume_analysis": "量能温和放大，多方占优"
  },
  "fundamental_analysis": {
    "pe_assessment": "估值合理",
    "growth_outlook": "增长稳定",
    "industry_position": "行业龙头"
  },
  "sentiment_analysis": {
    "market_sentiment": "偏多",
    "news_sentiment": "中性偏多"
  },
  "risk_alerts": [
    "注意高位回调风险",
    "关注白酒行业政策变化"
  ],
  "catalysts": [
    "春节旺季预期",
    "提价预期"
  ],
  "operation_advice": "建议逢低布局，目标价1900-1950，止损位1750"
}
```

**AI模型**：千问大模型 (qwen-plus)

---

### 4.2 POST /ai/analyze

批量AI分析（对一组股票评分）

**请求体**：
```json
{
  "stocks": [
    { "code": "600519", "name": "贵州茅台" },
    { "code": "000858", "name": "五粮液" }
  ]
}
```

---

## 5. Analysis - 情绪分析

### 5.1 POST /analysis/run-sentiment

计算市场情绪因子

**请求参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| date | string | 否 | 日期 (YYYYMMDD) |
| universe | string | 否 | 股票池 (all/hot) |

---

### 5.2 GET /analysis/sentiment

获取情绪榜单

**请求参数**：
| 参数 | 类型 | 必填 | 默认值 |
|------|------|------|--------|
| date | string | 否 | 当天 |
| limit | int | 否 | 200 |
| order | string | 否 | desc |

---

## 6. Database - 数据管理

### 6.1 GET /database/tables

获取所有表信息

**响应示例**：
```json
[
  {
    "name": "stock_history",
    "row_count": 1000000,
    "columns": ["id", "symbol", "name", "date", "open", "high", "low", "close", "volume"]
  }
]
```

---

### 6.2 POST /database/query

执行SQL查询（只读）

**请求体**：
```json
{
  "sql": "SELECT * FROM stock_history WHERE symbol = '600519' LIMIT 10"
}
```

**响应示例**：
```json
{
  "columns": ["id", "symbol", "name", "date", "open", "high", "low", "close", "volume"],
  "rows": [
    [1, "600519", "贵州茅台", "2026-01-24", 1800.0, 1860.0, 1795.0, 1850.0, 5000000]
  ],
  "row_count": 1
}
```

---

## 7. Admin - 管理接口

### 7.1 POST /admin/fetch-history

触发历史数据回补任务

### 7.2 GET /admin/task-status

获取任务状态

---

## 8. 数据源速查表

| API | 数据读取 | 数据写入/缓存 | 更新频率 |
|-----|----------|---------------|----------|
| GET /market/overview | `market_indices_realtime` + `all_stocks_realtime` | - | 10秒 |
| GET /market/short-line-indices | `short_line_indices_realtime` | - | 10秒 |
| GET /market/hot-concepts | `hot_concepts_realtime` | `hot_concepts_history` | 2分钟 |
| GET /market/hot-concept/leaders | `concept_leaders_cache` (5分钟缓存) | 同左 | 按需 |
| GET /market/ths-hot | `ths_hot_realtime` | `ths_hot_history` | 2分钟 |
| GET /market/lianban-ladder | `lianban_ladder_history` | 同左 | 2分钟 |
| GET /market/message-stream | AkShare 多接口 | - | 实时 |
| GET /charts/daily/{symbol} | `stock_history` → AkShare | `stock_history` | 按需 |
| GET /charts/intraday/{symbol} | AkShare `stock_zh_a_minute` | - | 实时 |
| POST /ai/analyze-stock | 千问大模型 | - | 按需 |

---

## 错误码说明

| HTTP状态码 | 说明 |
|------------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源未找到 |
| 500 | 服务器内部错误 |
| 503 | 外部服务不可用 |

---

## 请求/响应示例

### cURL 示例

```bash
# 获取市场概览
curl -X GET "http://localhost:4445/api/v1/market/overview"

# 获取短线指标
curl -X GET "http://localhost:4445/api/v1/market/short-line-indices"

# 获取热门概念
curl -X GET "http://localhost:4445/api/v1/market/hot-concepts?limit=20"

# 获取概念龙头股
curl -X GET "http://localhost:4445/api/v1/market/hot-concept/leaders?name=BC电池&limit=10"

# AI分析
curl -X POST "http://localhost:4445/api/v1/ai/analyze-stock" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "600519"}'
```

---

> 文档维护：技术团队  
> 最后更新：2026-01-24
