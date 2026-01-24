# AkShare 股票接口汇总

本文档整理了在股票分析项目中可用的AkShare接口，按功能分类列出，并标注了实际使用效果。

## 1. A股实时行情接口

### 主要接口
- `stock_zh_a_spot_em()` - 东方财富A股实时行情
  - 数据字段：代码、名称、最新价、涨跌幅、成交量、成交额、振幅、最高/最低、市盈率、市净率等
  - 数据量：约5800+只股票
  - 性能：稳定，推荐使用
  - 返回：DataFrame(序号,代码,名称,最新价,涨跌幅,涨跌额,成交量,成交额,振幅,最高,最低,今开,昨收,量比,换手率,市盈率-动态,市净率,总市值,流通市值,涨速,5分钟涨跌,60日涨跌幅,年初至今涨跌幅)

- `stock_zh_a_spot_ths()` - 同花顺A股实时行情
  - 注意：目前测试发现该接口可能存在问题

### 备选接口
- `stock_zh_a_spot()` - 传统A股实时行情
  - 可能存在解码问题，不推荐

## 2. A股历史数据接口

### 历史日线数据
- `stock_zh_a_hist(symbol, period='daily', start_date, end_date, adjust='')` - A股历史行情
  - 参数：symbol(股票代码), period(周期), start_date(开始日期), end_date(结束日期), adjust(复权)
  - 数据字段：日期,股票代码,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
  - 示例：`stock_zh_a_hist('000001', period='daily', start_date='20240101', end_date='20240110')`

### 分时数据
- `stock_zh_a_hist_min_em(symbol, period='1', adjust='0', start_date, end_date)` - A股分时数据
  - 参数：symbol(股票代码), period(周期), adjust(复权), start_date(开始时间), end_date(结束时间)
  - 数据字段：时间,开盘,收盘,最高,最低,成交量,成交额,均价

### 其他A股数据
- `stock_zh_a_new_em()` - A股新股
- `stock_zh_a_st_em()` - ST股票
- `stock_zh_a_stop_em()` - 停牌股票

## 3. 板块与概念接口

### 概念板块
- `stock_board_concept_name_em()` - 概念板块-东方财富
  - 数据字段：同实时行情，包含板块信息
- `stock_board_concept_cons_em(symbol)` - 概念板块成份股
  - 参数：symbol(板块代码)

### 行业板块
- `stock_board_industry_name_em()` - 行业板块-东方财富
- `stock_board_industry_cons_em(symbol)` - 行业板块成份股

### 同花顺板块接口
- `stock_board_concept_name_ths()` - 概念板块-同花顺
- `stock_board_concept_cons_ths(symbol)` - 概念板块成份股-同花顺
- `stock_board_industry_name_ths()` - 行业板块-同花顺
- `stock_board_industry_cons_ths(symbol)` - 行业板块成份股-同花顺

## 4. 热门股票与排行榜

### 热门排行
- `stock_hot_rank_em()` - 热门股票-东方财富
- `stock_hot_rank_wc()` - 热门股票-问财

### 涨停相关
- `stock_zt_pool_em(date)` - 涨停池
  - 参数：date(日期)
- `stock_zt_pool_previous_em()` - 昨日涨停池
- `stock_zt_pool_strong_em()` - 强势股池
- `stock_zt_pool_sub_new_em()` - 次新股池

## 5. 资金流向接口

### 个股资金流
- `stock_individual_fund_flow(symbol)` - 个股资金流
  - 参数：symbol(股票代码)

### 市场资金流
- `stock_market_fund_flow()` - 市场资金流
  - 数据字段：日期,上证收盘价,上证涨跌幅,深证收盘价,深证涨跌幅,主力净流入,超大单净流入,大单净流入,中单净流入,小单净流入等

### 资金流排名
- `stock_sector_fund_flow_rank()` - 行业资金流排名
- `stock_individual_fund_flow_rank()` - 个股资金流排名

## 6. 基本面数据接口

### 财务数据
- `stock_financial_abstract(symbol)` - 财务摘要
  - 参数：symbol(股票代码)
  - 数据字段：包含多个季度的财务指标

### 估值数据
- `stock_pe_ratio(symbol)` - 市盈率
- `stock_pb_ratio(symbol)` - 市净率

## 7. 其他有用接口

### 港股数据
- `stock_hk_spot()` - 港股实时行情

### 美股数据
- `stock_us_spot()` - 美股实时行情
- `stock_us_hist()` - 美股历史行情

### 交易日历
- `tool_trade_date_hist_sina()` - 交易日历

## 8. 项目中实际使用的接口

根据项目API文档，以下是在项目中实际使用的接口：

| 功能 | 接口 | 用途 |
|------|------|------|
| 股票筛选 | `stock_zh_a_spot_em` + `stock_zh_a_hist` | 获取股票实时行情和历史数据 |
| 热门概念 | `stock_board_concept_name_em` | 获取概念板块数据 |
| 概念资金流 | `stock_fund_flow_concept(symbol="即时")` | 获取概念板块资金流 |
| 热榜数据 | `stock_hot_rank_wc` / `stock_hot_rank_em` | 获取热门股票排行 |
| 涨停池 | `stock_zt_pool_em` | 获取涨停股票数据 |
| 概念分时 | `stock_board_concept_hist_min_em` | 获取概念板块分时数据 |
| 成份股 | `stock_board_concept_cons_em` | 获取概念板块成分股 |
| 历史数据 | `stock_zh_a_hist` | 获取股票历史数据 |
| 分时数据 | `stock_zh_a_minute` | 获取股票分时数据 |

## 9. 实际可用接口验证

经过实际测试，以下是验证可用的接口：

| 接口 | 数据形状 | 说明 |
|------|----------|------|
| `stock_zh_a_spot_em()` | (5800, 23) | 东方财富A股实时行情，返回5800+只股票数据 |
| `stock_zh_a_hist(symbol, ...)` | (7, 12) | A股历史数据，需提供股票代码等参数 |
| `stock_board_concept_name_em()` | (441, 12) | 东方财富概念板块，返回441个概念 |
| `stock_hot_rank_em()` | (100, 6) | 东方财富热门股票排行榜 |
| `stock_zt_pool_em(date)` | (58, 16) | 涨停池数据，返回当日涨停股票 |
| `stock_market_fund_flow()` | (120, 15) | 市场整体资金流向数据 |
| `stock_board_concept_name_ths()` | (375, 2) | 同花顺概念板块，返回375个概念 |

**注意**：以下接口在当前版本AkShare中可能不可用或已更改：
- `stock_hot_rank_wc()` - 经测试此接口不存在
- `stock_board_concept_cons_ths()` - 经测试此接口不存在

## 10. 接口使用建议

1. **优先级策略**：根据经验，建议使用同花顺接口优先，若不可用则降级至东方财富接口
2. **错误处理**：所有接口都应做好异常处理，因为网络接口可能不稳定
3. **缓存策略**：对于频繁访问的数据，应使用适当的缓存机制
4. **频率限制**：注意不要过于频繁地调用接口，以免被限制访问
5. **参数验证**：部分接口需要特定参数，如股票代码、日期等，使用前需确认参数要求
6. **版本兼容性**：AkShare接口可能会随版本变化，定期验证接口可用性