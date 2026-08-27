# StockPro API 指南

> 基础路径：`/api`
> 本地地址：`http://localhost:4445`
> 运行时完整契约：`http://localhost:4445/docs` 或 `/openapi.json`
> 更新日期：2026-08-24（对照 `backend/app/api/api.py` 路由注册表核验）

本文说明稳定接口域、鉴权、状态语义和写操作边界。请求/响应字段由 FastAPI OpenAPI 生成，本文不复制完整 Schema，只给出域级地图和约定。

## 1. 基本约定

- JSON 请求使用 `Content-Type: application/json`。
- 除健康检查外，业务接口都需要认证。
- Web 用户使用 Bearer Token；Agent 走独立 MCP Token（见第 8 节）。
- 所有时间字段都应包含时区；交易日使用 `YYYY-MM-DD`。
- 股票标识优先使用带市场身份的标准符号（如 `600000.SH`），不依赖六位代码猜交易所。
- 缺失、无权限、过期、质量失败和真正的数值 0 是不同语义。

## 2. 健康与能力发现

无需登录：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 后端进程健康 |
| `GET` | `/api/health/storage` | PostgreSQL 连接与迁移状态 |

需要登录：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/capabilities` | 启用的市场、Paper 运行时、live=false 等运行边界 |

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

响应返回 `access_token`、有效期、角色和权限。后续请求携带：

```http
Authorization: Bearer <access_token>
```

其余鉴权路由：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/auth/me` | 验证当前身份 |
| `POST` | `/api/auth/logout` | 登出 |
| `POST` | `/api/auth/guest/login` | 访客码登录 |

访客默认只读。当前版本没有管理访客码/Agent Token 的 HTTP 管理端点；Token 与访客码通过服务端配置或引导流程发放。Token 明文只在发放时展示一次，禁止写入仓库、日志或截图。

## 4. 业务接口域

下表对照当前路由注册表（`backend/app/api/api.py`）：

| 接口域 | 代表路径 | 说明 |
| --- | --- | --- |
| 行情研究 | `/api/v2/market/overview`、`/api/v2/market/*` | A 股首页基础层、标的搜索、日线/分时/盘口与研究指标 |
| 股票池 | `/api/pools/*`、`/api/pool-snapshots*` | 股票池、成员、生成、快照 |
| 因子 | `/api/factors*`、`/api/factor-versions*/validate|compute`、`/api/factor-snapshots*`、`/api/factor-runs`、`/api/factor-correlations` | 定义、版本验证、计算、快照、指标与相关性 |
| 策略 | `/api/strategies*` | 目录、不可变版本、`/validate`、`/{id}/quick-run` |
| 回测 | `/api/backtest/configuration|runs*`、`POST /run|matrix|walk-forward|jobs` | 异步任务、运行证据、指标、序列、订单、成交、持仓 |
| Paper 模拟 | `/api/paper/instances*` | 实例生命周期、事件、K 线与模拟账户 |
| 盯盘 | `/api/watch/context|alerts*|rules*` | 观察上下文、告警确认、版本化规则的创建/预览/显式评估 |
| 信号 | `/api/signals*` | 信号列表、详情与确认 |
| 监控 | `/api/monitor/summary|strategies|data|risk|notifications` | 运行、数据、风险与通知健康 |
| 复盘 | `/api/review/dates|{trade_date}|{trade_date}/assemble|seal` | 交易日记录、组装、保存和封存 |
| 数据中心 | `/api/data/status|datasets|snapshots|providers|schedules|jobs|quality|exchange/*` | 数据集、快照、质量、同步、Provider、计划及扩展数据导入导出 |
| AI 研发 | `/api/ai/config|tasks*`、`/api/ai/iterations/{id}/promote-candidate` | AI 研究任务循环与候选晋级 |

已移除的旧域：`/api/workflow/*`、`/api/stocks/*`、`/api/charts/*`、`/api/data-hub/*`、`/api/data-dev/*`、`/api/acceptance/*` 不存在；新客户端不要引用。完整字段以 OpenAPI 为准。

## 5. 常用读取示例

```bash
TOKEN='<bearer-token>'

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:4445/api/capabilities

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:4445/api/v2/market/overview

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  'http://127.0.0.1:4445/api/paper/instances?scope=business'

curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:4445/api/data/status
```

不要把真实 Token 直接写进 shell 历史、脚本或文档。

## 6. 异步任务

回测、全市场同步、因子计算等重任务异步执行。典型模式：

1. `POST` 创建任务，返回任务标识；
2. 客户端轮询任务详情或列表；
3. 终态为完成、失败或取消；
4. 失败任务保留错误和日志；重试会创建新的可审计尝试。

回测示例入口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/backtest/jobs` | 创建异步回测 |
| `GET` | `/api/backtest/runs` | 查询运行与结果证据 |
| `GET` | `/api/backtest/runs/{id}` | 单次运行详情 |
| `POST` | `/api/backtest/jobs/{job_id}/cancel` | 取消任务 |
| `POST` | `/api/backtest/jobs/{job_id}/retry` | 重试失败/取消任务 |

字段、合法状态和错误响应以 OpenAPI 为准。

## 7. 写操作边界

以下操作会调用外部 Provider、写入大量 PG 数据或改变研究状态，执行前必须确认目标和影响：

- `/api/data/sync`：外部数据同步
- `/api/data/quality/run`：质量检查
- `/api/data/exchange/imports`、`/api/data/exchange/http-imports`：扩展数据导入
- `/api/factor-versions/{id}/compute`：因子计算
- `/api/pools/{id}/generate` 与快照封存类 POST
- `/api/review/{trade_date}/seal`：复盘封存
- Paper 生命周期 POST（见第 8 节）

数据同步接口不应被健康检查或页面 GET 隐式调用。封存后的更正通过新分区和新快照表达，不修改历史证据。

当前全量 A 股同步合同：

- `GET /api/v2/sync/config`：返回当前全部证券及中文名称，不提供硬编码默认三只。
- `GET /api/v2/sync/schedule`：返回每日计划、下一运行时间和最近运行证据。
- `POST /api/v2/sync/instruments`：管理员显式触发一次全量证券主数据 + 最近交易日日线同步。
- `GET /api/v2/market/symbols`：返回 `symbols` 与带 `name/display_name` 的 `instruments`。
- `GET /api/v2/market/symbol-names`：批量只读名称解析，访客页面也可调用。

## 8. Paper 模拟写操作

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/paper/instances` | 创建实例 |
| `POST` | `/api/paper/instances/{id}/start` | 启动 |
| `POST` | `/api/paper/instances/{id}/pause` | 暂停 |
| `POST` | `/api/paper/instances/{id}/resume` | 恢复 |
| `POST` | `/api/paper/instances/{id}/stop` | 停止 |
| `POST` | `/api/paper/instances/{id}/advance` | 推进一个模拟周期 |

这些接口只改变模拟运行状态，不允许真实券商订单、资金划转或账户诊断。

## 9. Agent / MCP

`stockpro-mcp-v1` 使用独立的 Agent Token，请求头默认：

```http
X-BitPro-MCP-Token: <agent-token>
```

头名可经服务端 `BITPRO_MCP_AUTH_HEADER` 配置，客户端应以部署配置为准。

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
