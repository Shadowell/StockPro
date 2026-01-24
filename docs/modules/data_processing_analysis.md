# 数据处理与分析模块

## 页面与路由
- 路由：`/analysis`
- 目标：提供历史数据回补控制台 + 情绪因子计算/查询入口。

## 历史数据回补（History Fetch）
### 现状
- 后端启动时自动开启 APScheduler 每日任务（见 `backend/app/services/scheduler_service.py`）。
- 同时提供管理接口：
  - `POST /api/v1/admin/fetch-history`
  - `GET /api/v1/admin/task-status`

### 页面能力
- 展示当前任务状态（是否运行、进度、提示信息）。\n- 支持手动触发全市场回补（后台异步执行）。\n
## 情绪因子（Sentiment Factor）
### 接口
- 计算并写入：`POST /api/v1/analysis/run-sentiment?date=YYYYMMDD&universe=all|hot`\n- 查询榜单：`GET /api/v1/analysis/sentiment?date=YYYYMMDD&limit=200&order=desc`\n
### 计算逻辑（当前实现）
- 输入数据（AkShare）：\n  - 全市场现货：涨跌幅、成交额、换手率\n  - 涨停池：连板数（用于加分）\n  - 热度榜：排名（用于加分）\n  - 市场新闻情绪指数：作为市场层面的加减项\n- 输出：`score(0~100)` + `level(冷/中/热)`，并保留 `components` 明细便于后续调参。\n
### 存储表（Supabase）
当前实现默认写入：`stock_sentiment_daily`\n
建议建表 SQL：\n```sql\ncreate table if not exists public.stock_sentiment_daily (\n  code text not null,\n  name text,\n  date date not null,\n  score double precision,\n  level text,\n  components jsonb,\n  created_at timestamptz default now(),\n  primary key (code, date)\n);\n```\n
## 后端实现位置
- Analysis endpoints：`backend/app/api/endpoints/analysis.py`\n- SentimentService：`backend/app/services/sentiment_service.py`\n
