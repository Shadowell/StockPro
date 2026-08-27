# StockPro API 指南

> 本地地址：`http://localhost:4445`
> 运行时完整契约：`http://localhost:4445/docs` 或 `/api/openapi.json`
> 更新日期：2026-08-28（对照 `backend/app/main.py` 路由注册表核验）

本文说明当前稳定接口域、鉴权、状态语义和写操作边界。请求/响应字段由 FastAPI OpenAPI 生成，本文不复制完整 Schema，只给出域级地图和约定。

## 1. 路径命名空间

当前运行事实不是旧文档中的“所有业务都在 `/api/*`”：

- 健康检查与 Web 鉴权主入口使用 `/api/*`：`/api/health`、`/api/health/storage`、`/api/auth/*`。
- 鉴权兼容入口同时注册 `/api/v2/auth/*`，用于 BitPro-first 页面迁移期兼容。
- 当前产品业务域使用 `/api/v2/*`：行情、策略、回测、Paper、监控、数据同步、因子、设置、复盘、订单流、AI 研究等。
- 新增接口必须先查 `backend/app/main.py` 与运行中 OpenAPI，不能根据历史计划继续新增 `/api/paper/*`、`/api/data/*`、`/api/backtest/*` 等旧业务路径。

前端开发环境仍通过 Vite 把 `/api` 代理到 `http://127.0.0.1:4445`，因此浏览器 URL 前缀保持 `/api`，具体业务路径以 `/api/v2/...` 为准。

## 2. 基本约定

- JSON 请求使用 `Content-Type: application/json`。
- 除健康检查外，业务接口都需要认证。
- Web 用户使用 Bearer Token / HttpOnly session cookie；Agent 走独立 MCP Token（见第 10 节）。
- 所有时间字段都应包含时区；交易日使用 `YYYY-MM-DD`。
- 股票标识优先使用带市场身份的标准符号（如 `600000.SH`），页面展示中文名称在前、标准代码在后。
- 缺失、无权限、过期、质量失败和真正的数值 0 是不同语义。

## 3. 健康与能力发现

无需登录：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 后端进程健康 |
| `GET` | `/api/health/storage` | PostgreSQL 连接与迁移状态 |

需要登录：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/capabilities` | 启用的市场、Paper 运行时、live=false 等运行边界 |
| `GET` | `/api/v2/system/health` | BitPro-first 运行壳层健康摘要 |

健康接口是只读诊断，不应触发迁移、同步、bootstrap、Paper 恢复或策略执行。

## 4. Web 鉴权

### 管理员登录

```http
POST /api/auth/admin/login
Content-Type: application/json

{
  "username": "configured-admin",
  "password": "configured-password"
}
```

响应返回会话、角色和权限。后续请求通过 HttpOnly cookie 或 Bearer Token 鉴权。

其余鉴权路由：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/auth/me` | 验证当前身份 |
| `POST` | `/api/auth/logout` | 登出 |
| `POST` | `/api/auth/guest/login` | 访客码登录 |
| `GET/POST/DELETE` | `/api/v2/auth/guest-codes`、`/api/v2/auth/guest-codes/{code_id}` | 管理员管理访客码 |

访客默认只读。访客码和 Agent Token 的明文只在发放时展示一次，禁止写入仓库、日志或截图。

## 5. 当前业务接口域

下表对照当前 `backend/app/main.py` 注册表：

| 接口域 | 代表路径 | 说明 |
| --- | --- | --- |
| 行情研究 | `/api/v2/market/overview`、`/api/v2/market/ticker`、`/api/v2/market/symbols`、`/api/v2/market/klines`、`/api/v2/market/movers` | A 股首页、标的搜索、日线/分时/盘口、市场阶段、行业 RPS 与异动边缘 |
| 策略 | `/api/v2/strategies`、`/api/v2/strategies/{id}` | 策略目录、详情、创建、编辑、归档 |
| 回测 | `/api/v2/backtest/configuration`、`/api/v2/backtest/run_job`、`/api/v2/backtest/job/{id}`、`/api/v2/backtest/jobs` | 异步任务、运行证据、配置与任务控制 |
| Paper 模拟 | `/api/v2/live/instances`、`/api/v2/live/candidates`、`/api/v2/live/dashboard`、`/api/v2/live/events`、`/api/v2/live/accounts` | Paper 实例生命周期、账户、订单、成交、持仓、权益曲线和盯盘证据 |
| 盯盘 | `/api/v2/live/watchlist`、`/api/v2/live/watchlist/market`、`/api/v2/live/watchlist/markers` | 同一 Paper 证据链的人工观察面 |
| 信号 | `/api/v2/signals`、`/api/v2/signal-channels`、`/api/v2/signal-strategies` | 信号目录、详情、通道和策略聚合 |
| 监控 | `/api/v2/monitor/active_strategies`、`/api/v2/monitor/running-strategies`、`/api/v2/monitor/alerts`、`/api/v2/monitor/events` | 运行、告警、事件流与系统状态 |
| 复盘 | `/api/v2/review/summary` | 每日复盘摘要与运行证据 |
| 数据中心 / 同步 | `/api/v2/sync/status`、`/api/v2/sync/ashare/dataset-foundation`、`/api/v2/sync/config`、`/api/v2/sync/schedule`、`/api/v2/sync/instruments`、`/api/v2/sync/history/sync-all`、`/api/v2/sync/jobs` | 数据集、Provider、调度、全量证券主数据、最近交易日同步和近半年历史回补 |
| 因子 | `/api/v2/factorlab/summary`、`/api/v2/factorlab/research/tasks`、`/api/v2/factorlab/fundamentals/pit` | 因子研究、任务、诊断和点时数据 |
| 股票池 / 价差研究 | `/api/v2/arbitrage/summary` | 股票池/价差研究摘要与封存输入入口 |
| 设置 | `/api/v2/settings/feishu-webhook`、`/api/v2/settings/mcp-agent-tokens`、`/api/v2/settings/llm-model`、`/api/v2/settings/llm-providers/{key}/test` | 飞书 Webhook、MCP Token、LLM 模型与 Provider 状态 |
| AI 研究 | `/api/v2/agent/*`、`/api/v2/research-workbench/*`、`/api/v2/arc/*` | AI 助手、研究 mandate/job/candidate、候选保存和 Paper promotion 观察 |
| 订单流 / 基本面预留 | `/api/v2/orderflow/*`、`/api/v2/onchain/summary` | A 股订单流、资金流/基本面研究预留；不可伪造 tick/L2 |

已移除或不作为当前业务合同的旧域：`/api/workflow/*`、`/api/stocks/*`、`/api/charts/*`、`/api/data-hub/*`、`/api/data-dev/*`、`/api/acceptance/*`、`/api/paper/*`、`/api/backtest/*`、`/api/data/*`。完整字段以 OpenAPI 为准。

## 6. 常用读取示例

```bash
TOKEN='<bearer-token>'

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:4445/api/capabilities

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:4445/api/v2/market/overview

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  'http://127.0.0.1:4445/api/v2/live/instances?scope=business'

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:4445/api/v2/sync/status
```

不要把真实 Token 直接写进 shell 历史、脚本或文档。

## 7. 异步任务

回测、全市场同步、近半年历史同步、因子计算等重任务异步执行。典型模式：

1. `POST` 创建任务，返回任务标识；
2. 客户端轮询任务详情或列表；
3. 终态为完成、失败或取消；
4. 失败任务保留错误和日志；重试会创建新的可审计尝试。

当前主要异步入口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/v2/backtest/run_job` | 创建异步回测任务 |
| `GET` | `/api/v2/backtest/job/{job_id}` | 查询单个回测任务 |
| `GET` | `/api/v2/backtest/jobs` | 查询回测任务列表 |
| `POST` | `/api/v2/backtest/job/{job_id}/cancel` | 取消任务 |
| `POST` | `/api/v2/backtest/job/{job_id}/resume` | 恢复可恢复任务 |
| `POST` | `/api/v2/sync/history/sync-all` | 创建近半年全市场 A 股历史同步任务 |
| `GET` | `/api/v2/sync/jobs` | 查询同步任务列表 |

字段、合法状态和错误响应以 OpenAPI 为准。

## 8. 写操作边界

以下操作会调用外部 Provider、写入大量 PG 数据或改变研究状态，执行前必须确认目标和影响：

- `POST /api/v2/sync/instruments`：全量证券主数据 + 最近交易日日线同步。
- `POST /api/v2/sync/history/sync-all`：近半年全市场 A 股历史回补，会写 `stock_history`、基准、行业对照、市场证据快照和异动 metrics。
- `POST /api/v2/backtest/run_job`：创建回测任务。
- `POST /api/v2/live/instances`：创建 Paper 实例。
- `POST /api/v2/live/start|pause|resume|stop|advance`：控制 Paper 生命周期或显式推进周期。
- `/api/v2/research-workbench/*` 中的 mandate、job、candidate、promotion 写操作。
- `/api/v2/settings/*` 中的 Webhook、MCP Token、LLM 模型写操作。

数据同步接口不应被健康检查或页面 GET 隐式调用。封存后的更正通过新分区和新快照表达，不修改历史证据。

当前全量 A 股同步合同：

- `GET /api/v2/sync/config`：返回当前全部证券及中文名称，不提供硬编码默认三只。
- `GET /api/v2/sync/schedule`：返回每日计划、下一运行时间和最近运行证据。
- `POST /api/v2/sync/instruments`：管理员显式触发一次全量证券主数据 + 最近交易日日线同步。
- `POST /api/v2/sync/history/sync-all`：管理员显式触发最近 180 个自然日全市场历史回补；最终写入必须与市场证据快照和异动 metrics 保持事务一致。
- `GET /api/v2/market/symbols`：返回 `symbols` 与带 `name/display_name` 的 `instruments`。
- `GET /api/v2/market/symbol-names`：批量只读名称解析，访客页面也可调用。

## 9. Paper 模拟写操作

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/v2/live/instances` | 创建实例 |
| `POST` | `/api/v2/live/start` | 启动明确实例 |
| `POST` | `/api/v2/live/pause` | 暂停明确实例 |
| `POST` | `/api/v2/live/resume` | 恢复明确实例 |
| `POST` | `/api/v2/live/stop` | 停止明确实例 |
| `POST` | `/api/v2/live/advance` | 推进一个模拟周期 |

这些接口只改变模拟运行状态，不允许真实券商订单、资金划转或账户诊断。请求体中的实例标识、幂等键和状态转换以 OpenAPI 为准。

## 10. Agent / MCP

`stockpro-mcp-v1` 使用独立的 Agent Token，请求头默认：

```http
X-StockPro-MCP-Token: <agent-token>
```

主头名可经服务端 `STOCKPRO_MCP_AUTH_HEADER` 配置，静态 Token 主环境变量为
`STOCKPRO_MCP_API_TOKEN`。迁移期仍兼容 `X-BitPro-MCP-Token` 与
`BITPRO_MCP_API_TOKEN`；主 Header 存在时不会回退读取旧 Header。

规则：

- Token 在 PG 中只保存 SHA-256 哈希；
- `R` 作用域用于合同列出的读工具；
- `W` 作用域只开放允许的研究/回测写操作；
- 每个写调用需要唯一 `Idempotency-Key`；
- 所有调用记录方法、路径、作用域、结果和审计信息；
- 当前仅支持本地 stdio MCP，不提供公网传输；
- Agent 无法访问真实券商操作。

设置中心管理端点均要求管理员会话：

- `GET/POST /api/v2/settings/feishu-webhook`：只返回配置状态/掩码，保存值加密落 PostgreSQL；
- `GET /api/v2/settings/mcp-token`：返回主/兼容 Header 与环境变量状态，不返回明文；
- `GET/POST /api/v2/settings/mcp-agent-tokens`、`DELETE .../{id}`：明文仅在创建响应出现一次；
- `GET/PUT /api/v2/settings/llm-model` 与 `POST /api/v2/settings/llm-model/test`：读取/保存模型并执行受限连接测试；
- `GET/POST /api/v2/settings/llm-providers/{key}/capabilities|test`：返回服务端权威能力或测试结果。

本地 MCP 的工具清单和资源以运行时 capability discovery 为准。

## 11. 数据状态语义

推荐响应和前端共同表达：

| 状态 | 含义 |
| --- | --- |
| `ready` / `available` | 数据满足当前用途 |
| `empty` | 请求成功但没有符合条件的记录 |
| `stale` | 有记录但超过新鲜度阈值 |
| `partial` | 部分数据集或字段缺失 |
| `restricted` | Provider 权限或账号积分不足 |
| `unsupported` | 当前实现或 Provider 不支持 |
| `quality_failed` | 数据存在但未通过质量门 |
| `error` | 读取、任务或 Provider 调用失败 |

不能用响应生成时间覆盖来源更新时间，也不能把 `null` 转成 0。

## 12. 错误处理

常见 HTTP 状态：

| 状态 | 含义 |
| --- | --- |
| `400` | 参数或状态转换不合法 |
| `401` | 未登录或 Token 无效 |
| `403` | 当前角色/作用域不允许 |
| `404` | 对象不存在、不可见或路径不属于当前合同 |
| `409` | 状态冲突、幂等冲突或不可变对象修改 |
| `422` | 请求 Schema 校验失败 |
| `429` | 配额、并发或登录失败限流 |
| `500` | 未处理的服务错误 |
| `503` | Provider、数据库或依赖暂不可用 |

客户端应显示可操作的中文错误和下一步，不直接把堆栈或原始 Provider JSON 暴露给用户。

## 13. 如何确认文档没有过期

启动本地后端后：

```bash
curl -fsS http://127.0.0.1:4445/api/openapi.json > /tmp/stockpro-openapi.json
```

优先根据 OpenAPI 生成客户端或核对字段。若 API 域、鉴权、状态或安全边界变化，应同时更新本文、`docs/spec.md`、`docs/technical_architecture.md` 和对应 Sprint 合同。
