# AI 分析模块

## 页面与路由
- 路由：`/ai`
- 目标：输入单只股票代码，调用千问（qwen-plus）输出结构化行情分析。

## 接口
- `POST /api/v1/ai/analyze-stock`
  - 请求：`{ "symbol": "600519", "date": "YYYYMMDD(可选)" }`
  - 响应：`{ "symbol", "name", "model", "result", "raw_text" }`

## Prompt 输出约束
后端要求模型严格输出 JSON（不含 markdown），并包含：\n- summary\n- trend\n- key_levels\n- catalysts\n- risks\n- plan\n- data_notes\n
## 模型配置
- 环境变量：`QWEN_STOCK_MODEL`（默认 `qwen-plus`）\n- API Key：`QWEN_API_KEY`\n
## 数据来源
- 现货：AkShare A 股现货接口\n- K 线：后端 ChartService（优先从 DB 回读，否则 AkShare 拉取）\n- 情绪因子：如果当日已生成，则读取 `stock_sentiment_daily`\n
## 后端实现位置
- AI endpoints：`backend/app/api/endpoints/ai.py`\n- AIService：`backend/app/services/ai_service.py`\n
