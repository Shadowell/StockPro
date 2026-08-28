# AI 研发模块说明

> 页面：`/ai-lab`；个股 AI 面板也可从 `/market?tab=stock&panel=ai` 进入。

AI 研发用于对固定研究对象和证据进行辅助分析，不是自动荐股或自动策略生成器。

## 能力

- `/api/v2/agent/*`：AI 助手任务、优化器配置、研究运行状态和只读能力摘要。
- `/api/v2/research-workbench/*`：A 股研究 mandate、job、candidate、Paper promotion 观察和组合复核。
- `/api/v2/settings/llm-model` 与 `/api/v2/settings/llm-providers/{key}/capabilities|test`：
  读取模型配置、服务端 Provider 能力和连接测试结果。

字段以运行时 OpenAPI 为准。

## 配置

- `QWEN_API_KEY`：DashScope API Key；未配置时外部模型不可用。
- `QWEN_STOCK_MODEL`：股票分析模型，示例配置默认 `qwen-plus`。

## 产品边界

- 请求与结果需要表达研究对象、数据日期、模型和证据状态。
- Provider 不可用、证据缺失或过期时明确报错/降级，不伪造模型结果。
- AI 输出必须人工复核。候选保存不等于完整回测通过，也不能自动创建或控制 Paper。
- Key 只保存在后端本地环境变量，不进入前端或 Git。

详见 [产品规格](../spec.md) 和 [API 指南](../api.md)。
