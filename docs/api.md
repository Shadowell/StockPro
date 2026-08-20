# StockPro API 指南

> 基础路径：`/api`
> 本地地址：`http://localhost:4445`
> 运行时完整契约：`http://localhost:4445/docs` 或 `/openapi.json`
> 更新日期：2026-07-29

本文说明稳定接口域、鉴权、状态语义和写操作边界。请求/响应字段持续由 FastAPI OpenAPI 生成，避免在手写文档中复制一份容易过期的完整 Schema。

## 1. 基本约定

- JSON 请求使用 `Content-Type: application/json`。
- 除健康和登录接口外，业务接口都需要认证。
- Web 管理员和访客使用 Bearer Token。
- 所有时间字段都应包含时区；交易日使用 `YYYY-MM-DD`。
- 股票标识优先使用带市场身份的标准符号，不能依赖六位代码猜交易所。
- 分页、排序和过滤参数以 OpenAPI 为准。
- 缺失、无权限、过期、质量失败和真正的数值 0 是不同语义。

## 2. 健康接口

健康接口无需登录：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health/health` | 后端进程健康 |
| `GET` | `/api/health/storage` | PostgreSQL 连接与存储状态 |
| `GET` | `/api/health/report` | 汇总诊断 |
| `GET` | `/api/health/dns-diagnostic` | Provider DNS 诊断 |
| `GET` | `/api/health/dashscope-endpoint` | DashScope 端点诊断 |

健康接口是只读诊断，不应触发迁移、同步、bootstrap、Paper 恢复或策略执行。

## 3. Web 鉴权

### 管理员登录

```http
POST /api/auth/admin/login
Content-Type: application/json

{
  "username": "configured-admin",
  "password": "configured-password"
}
```

响应返回 `access_token`、有效期、角色和权限。后续请求：

```http
Authorization: Bearer <access_token>
```

验证当前身份：

```http
GET /api/auth/me
Authorization: Bearer <access_token>
```

### 访客登录

管理员先创建带有效期和回测配额的访客码，访客调用：

```http
POST /api/auth/guest/login
Content-Type: application/json

{
  "code": "<guest-code>"
}
```

访客默认只读，只在返回权限允许的范围内运行回测。

### 管理端安全接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/auth/guest-codes` | 创建访客码 |
| `GET` | `/api/auth/guest-codes` | 列出访客码 |
| `DELETE` | `/api/auth/guest-codes/{id}` | 撤销访客码 |
| `POST` | `/api/auth/mcp-agent-tokens` | 创建 Agent Token |
| `GET` | `/api/auth/mcp-agent-tokens` | 列出 Agent Token 元数据 |
| `DELETE` | `/api/auth/mcp-agent-tokens/{id}` | 撤销 Agent Token |

Token/访客码明文只应在必要时展示一次，禁止写入仓库、日志或截图。

## 4. 业务接口域

| 接口域 | 代表路径 | 说明 |
| --- | --- | --- |
| 工作流发现 | `/api/workflow/capabilities` | 客户端先确认阶段、能力和真实交易边界 |
| 首次就绪 | `/api/workflow/onboarding-readiness` | 只读检查安全、存储、Provider、封存数据与后续主线状态 |
| 市场研究 | `/api/market/*` | 概览、情绪、涨停生态、板块、事件、日历和 PostgreSQL 自选清单 |
| 股票与图表 | `/api/stocks/*`、`/api/charts/*` | 搜索、筛选、日线和分时 |
| 因子 | `/api/factors/*`、`/api/factor-*` | 定义、版本、计算、快照、指标与相关性 |
| 股票池 | `/api/pools/*`、`/api/pool-snapshots/*` | 股票池、成员、快照和回测草稿 |
| 策略 | `/api/strategy/*` | 策略目录、版本、验证、快速运行与回放 |
| 回测 | `/api/backtest/*` | 任务、运行、指标、序列、订单、成交和比较 |
| Paper | `/api/paper/*` | 实例、周期、事件、K 线和模拟账户 |
| 盯盘 | `/api/watch/*` | 观察上下文、告警确认、版本化规则创建/预览/显式评估；评估只写告警与站内通知，不触发订单 |
| 监控 | `/api/monitor/*` | 运行、数据和风险健康 |
| 复盘 | `/api/review/*` | 交易日记录、组装、保存和封存 |
| 数据中心 | `/api/data/*` | 数据集、快照、质量、同步、Provider、计划及隔离扩展数据导入导出 |
| 数据任务 | `/api/data-hub/*`、`/api/data-dev/*` | 任务、日志、质量报告和开发任务 |
| AI | `/api/ai/*` | 能力发现、个股和批量分析 |
| 本地验收 | `/api/acceptance/*` | 本地恢复、性能和备份演练 |

旧接口仍可能为页面兼容存在。新客户端优先使用页面当前调用的工作流接口和 OpenAPI，不要仅凭旧文档猜路由。

## 5. 常用读取示例

```bash
TOKEN='<bearer-token>'

curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:4445/api/workflow/capabilities

curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:4445/api/market/overview

curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:4445/api/data/status

curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:4445/api/backtest/jobs
```

不要把真实 Token 直接写进 shell 历史、脚本或文档。

## 6. 异步任务

回测、全市场同步、因子计算和部分数据任务可能异步执行。典型模式：

1. `POST` 创建任务，返回 `202 Accepted` 和任务标识。
2. 客户端轮询任务详情或列表。
3. 终态为完成、失败或取消。
4. 失败任务保留错误和日志；重试创建新的可审计尝试。

回测示例入口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/backtest/jobs` | 创建异步回测 |
| `GET` | `/api/backtest/jobs` | 查询任务 |
| `GET` | `/api/backtest/jobs/{id}` | 查询单个任务 |
| `GET` | `/api/backtest/jobs/{id}/logs` | 查询日志 |
| `POST` | `/api/backtest/jobs/{id}/cancel` | 取消任务 |
| `POST` | `/api/backtest/jobs/{id}/retry` | 重试失败/取消任务 |

字段、合法状态和错误响应以 OpenAPI 为准。

## 7. 数据与快照写操作

以下操作会调用外部 Provider、写入大量 PG 数据或改变研究状态，执行前必须确认目标和影响：

- `/api/data/history/sync-all`
- `/api/data/realtime/sync`
- `/api/data/market-evidence/sync`
- `/api/data/snapshots`
- `/api/data/snapshots/{id}/seal`
- `/api/data/schedules/daily/run`
- `/api/factor-compute-runs`
- `/api/pools/{id}/generate`
- `/api/pool-snapshots/{id}/backtests`

数据同步接口不应被健康检查或页面 GET 隐式调用。封存快照后，后续更正通过新分区和新快照表达，不修改历史证据。

## 8. Paper 写操作

Paper 实例控制：

| 方法 | 路径 |
| --- | --- |
| `POST` | `/api/paper/instances` |
| `POST` | `/api/paper/instances/{id}/start` |
| `POST` | `/api/paper/instances/{id}/pause` |
| `POST` | `/api/paper/instances/{id}/resume` |
| `POST` | `/api/paper/instances/{id}/stop` |
| `POST` | `/api/paper/instances/{id}/cycles` |

这些接口只改变模拟运行状态，不允许真实券商订单、资金划转或账户诊断。

## 9. Agent / MCP

`stockpro-mcp-v1` 使用独立的 Agent Token：

```http
X-StockPro-MCP-Token: <one-time-token>
```

规则：

- Token 在 PG 中只保存 SHA-256 哈希；
- `R` 作用域用于合同列出的读工具；
- `W` 作用域只开放允许的研究/回测写操作；
- 每个写调用需要唯一 `Idempotency-Key`；
- 所有调用记录方法、路径、作用域、结果和审计信息；
- 当前仅支持本地 stdio MCP，不提供公网传输；
- Agent 无法访问真实券商操作。

本地 MCP 的工具清单和资源以运行时 capability discovery 为准。

## 10. 数据状态语义

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

## 11. 错误处理

常见 HTTP 状态：

| 状态 | 含义 |
| --- | --- |
| `400` | 参数或状态转换不合法 |
| `401` | 未登录或 Token 无效 |
| `403` | 当前角色/作用域不允许 |
| `404` | 对象不存在或不可见 |
| `409` | 状态冲突、幂等冲突或不可变对象修改 |
| `422` | 请求 Schema 校验失败 |
| `429` | 配额或并发限制 |
| `500` | 未处理的服务错误 |
| `503` | Provider、数据库或依赖暂不可用 |

客户端应显示可操作的中文错误和下一步，不直接把堆栈或原始 Provider JSON 暴露给用户。

## 12. 如何确认文档没有过期

启动本地后端后：

```bash
curl -fsS http://127.0.0.1:4445/openapi.json > /tmp/stockpro-openapi.json
```

优先根据 OpenAPI 生成客户端或核对字段。若 API 域、鉴权、状态或安全边界变化，应同时更新本文、`docs/spec.md` 和对应 Sprint 合同。
