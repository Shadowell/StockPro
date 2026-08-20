# Sprint 合同：BitPro 流程对齐 — AI 策略研发闭环与操作台改造

- 状态：进行中
- 日期：2026-08-17
- 交付边界：B/S、PostgreSQL、研究优先、Paper 模拟 + 实盘预检留痕（不发出真实委托）

## 1. 目标

把 BitPro（永续合约平台）验证过的主干流程移植到 StockPro 的 A 股日线语境：

1. **AI 策略研发闭环**：Planner → [Sprint 合约 → Strategist → AST 沙箱 → Backtester → Evaluator] × N，
   任务与迭代全量落 PostgreSQL，服务重启自动恢复；采纳（promote）后进入既有策略版本体系。
2. **操作台形态对齐**：策略页增加「AI 写策略」入口；回测页改 BitPro 回测台形态
   （实例行卡片 + 判决带 + 绩效明细三列）；模拟页改实例卡片网格 + 指标详情（不动现有实例）。
3. **复盘页大盘 Snapshot**：当日指数、市场宽度、情绪、涨停生态、板块资金、人气榜一屏快照。
4. **实盘工作台**：券商通道状态、晋级候选、预检清单、双重确认与审计留痕；
   未配置通道时一切真实委托被安全拦截。
5. **温和裁剪**：一级导航按 2026-08-18 形态决策执行「核心链露出 + 实验区隐藏」（见 `docs/spec.md` §3）：
   侧栏露出 首页/行情/策略/回测/AI 研发/模拟/盯盘/数据；股票池/因子/监控/复盘/数据处理保持菜单隐藏，实盘保持直链。
   本合同不删除任何有效路由页面，只删除无路由/被替代的死代码。

> 2026-08-18 决策记录：本合同原定「12+1 导航入口不变、仅新增实盘入口」与后续「操作台收敛」切片的
> `HIDDEN_NAV_IDS`（把 AI 研发入口一并隐藏）冲突。裁定采用混合形态：AI 研发属于核心链恢复露出，
> 实盘/股票池/因子/监控/复盘仍隐藏。目标 2（策略页「AI 写策略」入口）随之恢复。

## 2. 后端交付

| 模块 | 说明 |
| --- | --- |
| `app/services/agent/` | orchestrator（线程化闭环）、planner/strategist/evaluator（LLM）、backtester（复用 `validate_strategy_python` + `BacktestWorkbenchService.run(mode="quick")`）、llm_client（DashScope 兼容）、prompts（Strategy API v1 硬约束）、schemas |
| 迁移 202608170001 | `agent_tasks` / `agent_iterations` 表 |
| `app/api/endpoints/agent.py` | 任务 CRUD、启动/停止、迭代查询、promote（要求版本 validation_status=valid） |
| 启动恢复 | `main.py` 启动时 `recover_interrupted()` 续跑未完成任务 |
| `app/services/live_trading_service.py` + 端点 `/live/*` + 迁移 202608170002 | 实盘预检/晋级/审计；`LIVE_TRADING_ENABLED` 默认 false |
| `QWEN_BASE_URL` 配置 | DashScope OpenAI 兼容端点 |

### 关键约束

- AI 生成代码必须通过 StockPro Strategy API v1 AST 沙箱；每轮迭代保存 sandbox_report。
- AI 诊断回测走 quick 模式（event_limit ≤ 60），不产生晋级证据；晋级仍走 11 项门控。
- promote 只暴露已验证版本，不自动创建 Paper、不自动晋级。
- Evaluator LLM 失败时退化为确定性评分（不伪造 AI 结论）。
- LLM 不可用（无 QWEN_API_KEY）时任务快速失败并明示原因。

## 3. 前端交付

| 页面 | 改造 |
| --- | --- |
| /strategy | 「AI 写策略」入口 + AI 研发标签页（任务列表、迭代时间线、多维评分、采纳） |
| /backtest | 回测台：行卡片（4 指标）、搜索/筛选/排序、判决带、绩效三列、晋级检查 |
| /paper | 实例卡片网格（运行呼吸灯、收益主指标、暂停/继续/关闭）、详情 KPI 行（保留现有实例与生命周期） |
| /review | 大盘 Snapshot（指数/宽度/情绪/涨停生态/板块资金/人气）+ 既有结论编辑 |
| /live（新增） | 实盘工作台：通道状态、晋级候选、预检+双重确认弹窗、审计事件 |

## 4. 验收标准

1. `./scripts/check.sh` 全绿（后端 pytest + 前端构建/测试）。
2. 本地 4444/4445 重启后健康检查通过。
3. AI 闭环单测覆盖：沙箱拒绝、达标完成、恢复、promote 校验。
4. 实盘服务单测覆盖：无通道阻断、门控不过、双重确认缺失。
5. 模拟盘现有实例数据与生命周期不变。
6. SSH 隧道冷连接下策略目录不得被普通页面超时误报为不可用；真实策略页需在既定冷读窗口内显示业务数据或诚实空状态。

## 5. 非目标

- 无人值守定时生成（第二期）。
- 真实券商委托路由、实盘订单（需新合同显式授权）。
- 一级导航结构变更（2026-08-18 已裁定混合形态：AI 研发露入侧栏，实盘维持直链隐藏；见 `docs/spec.md` §3）。
