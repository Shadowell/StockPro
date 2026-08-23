# BitPro-first 重建 Wave 3：策略、回测、模拟主线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 直接使用 BitPro 策略、回测和 InstanceDashboard 产品骨架，接入 StockPro 当前策略合同、A股回测证据和现有 PostgreSQL Paper 历史，形成唯一“策略 → 回测 → 模拟”主线。

**Architecture:** 策略代码继续以不可变版本和内容哈希存储，公共产品不使用 API 版本名称；历史合同字段只读。回测与 Paper 共用当前策略执行语义和封存输入，BitPro ViewModel 由 PostgreSQL Application Service 生成，不改变已有 UUID 和账本。

**Tech Stack:** FastAPI、PostgreSQL、isolated Python worker、Backtrader/A股撮合、React、TypeScript、ECharts、Playwright、异步 job worker。

**Spec:** `docs/contracts/active-bitpro-first-a-share-rebuild.md`

## Global Constraints

- Wave 2 的数据、因子、股票池 API 和页面必须全绿。
- 产品/API/页面只使用当前策略合同，不公开旧合同入口或版本命名。
- 历史版本字段只读，不得改写现有策略、回测或 Paper lineage。
- 快速诊断、参数矩阵、Walk-forward 和 AI 实验不能生成 Paper 晋级资格。
- 只有完整回测通过研究协议、成本、容量、数据质量和样本外门控后才能创建 Paper。
- Paper 适配不允许 configure/reset/clear/archive 现有实例。
- 每个 Paper 相关提交前后运行完整 continuity manifest。

---

### Task 1: 建立当前策略合同与 PostgreSQL Application Service

**Files:**
- Restore/adapt: `backend/app/services/strategy_runtime_service.py`
- Restore/adapt: `backend/app/services/strategy_runtime_worker.py`
- Create: `backend/app/domain/strategy/models.py`
- Create: `backend/app/services/strategy_application_service.py`
- Create: `backend/app/api/endpoints/strategy.py`
- Modify: `backend/app/repositories/protocols.py`
- Modify: `backend/app/repositories/postgres_repository.py`
- Modify: `backend/app/api/api.py`
- Test: `backend/tests/test_strategy_current_contract.py`

**Interfaces:**
- Produces: `GET/POST /api/strategies`、`GET /api/strategies/{id}`、`POST /api/strategies/{id}/versions`、`POST /api/strategies/validate`、`POST /api/strategies/{id}/quick-run`。
- Produces: `StrategyDefinitionView`, `StrategyVersionView`, `ValidationResult`, `ReplayResult`。

- [x] **Step 1: 写当前合同与历史元数据失败测试**

```python
def test_new_strategy_uses_current_contract_without_public_version_name(client):
    response = client.post("/api/strategies", json={
        "name": "动量轮动", "description": "封存股票池动量策略",
        "script_content": "def initialize(context): pass\ndef handle_data(context, data): pass",
    }, headers=admin_headers())
    assert response.status_code == 200
    body = response.json()
    assert "api_version" not in body
    assert body["strategy_version"]["content_hash"]

def test_historical_contract_metadata_is_readonly(repository):
    historical = repository.get_strategy_version("historical-id")
    assert historical.contract_metadata
    with pytest.raises(ImmutableEvidenceError):
        repository.update_contract_metadata(historical.id, {})
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_strategy_current_contract.py -q`

Expected: FAIL，当前 Strategy Service/Router 不存在或仍公开版本名称。

- [x] **Step 3: 定义当前策略模型**

```python
@dataclass(frozen=True)
class StrategyVersionView:
    id: UUID
    strategy_id: UUID
    version: int
    name: str
    script_content: str
    parameters: Mapping[str, object]
    content_hash: str
    validation_status: Literal["pending", "valid", "invalid"]
    historical_contract_metadata: Mapping[str, object] | None
```

公共 response 不返回产品 API 版本名；历史 metadata 只在审计详情中按需展示。

- [x] **Step 4: 恢复 AST 沙箱和隔离 worker**

保留 `initialize(context)` / `handle_data(context, data)` 当前语义、禁止模块/网络/文件/数据库访问、CPU/内存/时长/输出限制。代码验证与 quick-run 使用同一 worker。

- [x] **Step 5: 实现 Repository 和 Router**

Repository 只读写 `strategy_versions`、validation runs、replay runs/intents/custom records；
创建子版本，不原地更新已使用版本。

- [x] **Step 6: 运行测试、安全扫描和基线对账**

Run: `python -m pytest backend/tests/test_strategy_current_contract.py -q && python rebuild/assert_safety.py --root . --format json && python rebuild/verify_baseline.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL" --read-only`

Expected: PASS；现有策略数和 Paper lineage 未变化。

- [x] **Step 7: 提交**

```bash
git add backend/app/domain/strategy backend/app/services/strategy_runtime_service.py backend/app/services/strategy_runtime_worker.py backend/app/services/strategy_application_service.py backend/app/api/endpoints/strategy.py backend/app/repositories backend/app/api/api.py backend/tests/test_strategy_current_contract.py
git commit -m "feat(strategy): restore current immutable A-share contract"
```

### Task 2: 直接适配 BitPro 策略中心

**Files:**
- Modify: `frontend/src/pages/Strategy.tsx`
- Modify: `frontend/src/components/StrategyParameterSections.tsx`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/types/strategy.ts`
- Test: `frontend/tests/e2e/rebuild-strategy.spec.ts`
- Modify: `docs/pages/策略中心.md`

**Interfaces:**
- Consumes: `/api/strategies*` 当前合同、Wave 2 因子/股票池。
- Produces: BitPro 策略目录、筛选、详情、编辑/新版本、验证和输入证据页面。

- [ ] **Step 1: 写目录、详情和创建失败 E2E**

```typescript
test('strategy center keeps BitPro catalogue and A-share lineage', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/strategy')
  await expect(page.getByRole('heading', { name: '策略中心' })).toBeVisible()
  await expect(page.getByLabel('搜索策略')).toBeVisible()
  await page.getByTestId('strategy-card').first().getByRole('button', { name: '详情' }).click()
  await expect(page.getByText('封存输入')).toBeVisible()
  await expect(page.getByText(/合约|永续|USDT/)).toHaveCount(0)
})
```

- [ ] **Step 2: 运行失败 E2E**

Run: `npm --prefix frontend run test:e2e -- --grep "strategy center keeps BitPro"`

Expected: FAIL，页面仍未适配或显示数字资产字段。

- [ ] **Step 3: 绑定当前 Strategy client**

删除多版本 API client；目录、详情、验证、创建和子版本全部调用 `/api/strategies`。

- [ ] **Step 4: 替换领域筛选与参数**

资产筛选改为股票/ETF/指数，状态/策略类型/周期/资金筛选保留 BitPro 交互；
参数面板显示 A股交易日、股票池、因子、成本、T+1 和持仓限制。

- [ ] **Step 5: 保留 BitPro 列表/详情性能合同**

目录分页，详情按标签懒加载；编辑器与 Monaco 仅在编辑时加载；返回路径保持 URL 深链。

- [ ] **Step 6: 更新页面合同并运行 1440px/390px**

Run: `npm --prefix frontend run test:e2e -- --grep "strategy center keeps BitPro" && npm --prefix frontend run build`

Expected: PASS，无横向溢出、无旧合同文案。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/pages/Strategy.tsx frontend/src/components/StrategyParameterSections.tsx frontend/src/api/client.ts frontend/src/types/strategy.ts frontend/tests/e2e/rebuild-strategy.spec.ts docs/pages/策略中心.md
git commit -m "feat(strategy-ui): connect BitPro catalogue to A-share strategies"
```

### Task 3: 建立当前回测任务与证据 API

**Files:**
- Restore/adapt: `backend/app/services/ashare_backtest_engine.py`
- Restore/adapt: `backend/app/services/backtest_workbench_service.py`
- Restore/adapt: `backend/app/services/backtest_job_service.py`
- Restore/adapt: `backend/app/services/walk_forward_plan_service.py`
- Create: `backend/app/domain/backtest/models.py`
- Create: `backend/app/services/backtest_application_service.py`
- Create: `backend/app/api/endpoints/backtest.py`
- Modify: `backend/app/repositories/protocols.py`
- Modify: `backend/app/repositories/postgres_repository.py`
- Modify: `backend/app/api/api.py`
- Test: `backend/tests/test_backtest_current_contract.py`

**Interfaces:**
- Produces: configuration、jobs、logs、runs、metrics、series、orders、trades、positions、compare、matrix、Walk-forward endpoints，全部位于 `/api/backtest/*`。

- [ ] **Step 1: 写诊断/完整/矩阵/Walk-forward 门控失败测试**

```python
def test_only_full_protocol_run_can_be_paper_eligible(service):
    quick = service.run(valid_request(), mode="quick")
    matrix = service.run_matrix(valid_experiment(), {"lookback": [5, 10]})
    walk = service.run_walk_forward(valid_walk_request())
    assert quick.promotion_status == "not_evaluated"
    assert all(cell.promotion_status == "not_evaluated" for cell in matrix.cells)
    assert all(fold.promotion_eligible is False for fold in walk.folds)
    full = service.run(valid_protocol_request(), mode="full")
    assert full.promotion_checks
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_backtest_current_contract.py -q`

Expected: FAIL，当前 Backtest Application Service 不存在。

- [ ] **Step 3: 恢复 A股撮合与完整证据**

保留交易日、T+1、整手、涨跌停、停牌、成本、容量、无未来数据；
所有输入固定 snapshot/protocol/cost/strategy/pool/factor IDs 和 hash。

- [ ] **Step 4: 统一 job 生命周期**

```python
@dataclass(frozen=True)
class BacktestRequest:
    strategy_version_id: UUID
    dataset_snapshot_id: int
    universe_snapshot_id: int
    factor_snapshot_id: int | None
    pool_snapshot_id: int | None
    cost_model_id: UUID
    research_protocol_id: UUID | None
    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    initial_cash: Decimal
    parameters: Mapping[str, object]

@dataclass(frozen=True)
class BacktestJobView:
    job_id: UUID
    status: str
    progress: int
    run_id: UUID | None
    message: str

@dataclass(frozen=True)
class WalkForwardRequest:
    backtest: BacktestRequest
    parameter_grid: Mapping[str, Sequence[object]]
    objective: str
    train_sessions: int
    test_sessions: int
    step_sessions: int

@dataclass(frozen=True)
class MatrixResult:
    experiment_id: UUID
    cells: tuple[BacktestRunView, ...]

class BacktestApplicationService:
    def create_job(self, request: BacktestRequest, mode: Literal["quick", "full"]) -> BacktestJobView: ...
    def cancel_job(self, job_id: UUID, actor: AuthProfile) -> BacktestJobView: ...
    def retry_job(self, job_id: UUID, actor: AuthProfile) -> BacktestJobView: ...
    def run_matrix(self, experiment_id: UUID, grid: Mapping[str, Sequence[object]]) -> MatrixResult: ...
    def run_walk_forward(self, request: WalkForwardRequest) -> BacktestJobView: ...
```

- [ ] **Step 5: 注册当前 endpoints 并迁移 worker**

worker 只读 PostgreSQL job；重启恢复 interrupted 状态；取消点在折叠/组合/分页之间检查。

- [ ] **Step 6: 运行门控、任务和对账测试**

Run: `python -m pytest backend/tests/test_backtest_current_contract.py backend/tests/test_backtest_job_recovery.py -q && python rebuild/verify_baseline.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL" --read-only`

Expected: PASS；历史 79 个回测仍可读且未修改。

- [ ] **Step 7: 提交**

```bash
git add backend/app/domain/backtest/models.py backend/app/services/ashare_backtest_engine.py backend/app/services/backtest_workbench_service.py backend/app/services/backtest_job_service.py backend/app/services/walk_forward_plan_service.py backend/app/services/backtest_application_service.py backend/app/api/endpoints/backtest.py backend/app/repositories backend/app/api/api.py backend/tests/test_backtest_current_contract.py backend/tests/test_backtest_job_recovery.py
git commit -m "feat(backtest): restore A-share evidence workbench"
```

### Task 4: 直接适配 BitPro 回测控制台

**Files:**
- Modify: `frontend/src/pages/Backtest.tsx`
- Modify: `frontend/src/pages/backtest/backtestSupport.tsx`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/types/backtest.ts`
- Test: `frontend/tests/e2e/rebuild-backtest.spec.ts`
- Modify: `docs/pages/回测.md`

**Interfaces:**
- Consumes: `/api/backtest/*` 当前合同。
- Produces: BitPro 多实例历史、创建向导、任务控制、详情、比较、矩阵和 Walk-forward UI。

- [ ] **Step 1: 写控制台/向导/详情失败 E2E**

```typescript
test('backtest console keeps BitPro workflow and A-share evidence', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/backtest')
  await expect(page.getByTestId('backtest-history-table')).toBeVisible()
  await page.getByRole('button', { name: '创建回测实例' }).click()
  for (const step of ['选择策略','配置参数','确认运行']) await expect(page.getByText(step)).toBeVisible()
  await expect(page.getByText('T+1')).toBeVisible()
  await expect(page.getByText('100股')).toBeVisible()
})
```

- [ ] **Step 2: 运行失败 E2E**

Run: `npm --prefix frontend run test:e2e -- --grep "backtest console keeps BitPro"`

Expected: FAIL，页面尚未接当前合同。

- [ ] **Step 3: 绑定 BitPro 控制台全部模式**

保留任务列表、状态筛选、收益排序、创建向导、结果详情、交易/K线/日志、对比；
增加参数矩阵与 Walk-forward，所有诊断模式标明不可晋级。

- [ ] **Step 4: 分层加载大结果**

核心 run/metrics 先加载，series 和各明细 tab 按需请求；列表分页，不首屏读取全部 ledger。

- [ ] **Step 5: 更新页面合同并运行 E2E/build**

Run: `npm --prefix frontend run test:e2e -- --grep "backtest console keeps BitPro" && npm --prefix frontend run build`

Expected: PASS；详情刷新深链保持，bundle 预算通过。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/Backtest.tsx frontend/src/pages/backtest/backtestSupport.tsx frontend/src/api/client.ts frontend/src/types/backtest.ts frontend/tests/e2e/rebuild-backtest.spec.ts docs/pages/回测.md
git commit -m "feat(backtest-ui): adapt BitPro console to A-share evidence"
```

### Task 5: 建立 Paper Application Service 与 BitPro ViewModel

**Files:**
- Restore/adapt: `backend/app/services/paper_runtime_service.py`
- Create: `backend/app/services/paper_application_service.py`
- Create: `backend/app/api/endpoints/paper.py`
- Modify: `backend/app/repositories/protocols.py`
- Modify: `backend/app/repositories/postgres_repository.py`
- Modify: `backend/app/api/api.py`
- Create: `backend/tests/test_paper_current_contract.py`
- Create: `rebuild/verify_paper_continuity.py`
- Create: `rebuild/tests/test_paper_continuity.py`

**Interfaces:**
- Produces: `GET/POST /api/paper/instances`、detail、start/pause/resume/stop、cycles、advance、events、klines；BitPro `PaperInstanceView`。

- [ ] **Step 1: 写只读 ViewModel 不变性测试**

```python
def test_paper_view_model_does_not_change_ledger(service, repository):
    before = repository.continuity_manifest()
    view = service.list_instances(scope="business")
    after = repository.continuity_manifest()
    assert len(view.items) == 15
    assert before == after
    assert view.items[0].id == before["instances"][0]["instance_id"]
```

- [ ] **Step 2: 写 continuity verifier 失败测试**

```python
def test_continuity_verifier_detects_equity_or_event_loss():
    baseline = manifest(equity=428, events=681)
    current = manifest(equity=427, events=681)
    result = compare_continuity(baseline, current)
    assert result.passed is False
    assert result.differences[0].field == "paper.equity_sample_count"
```

- [ ] **Step 3: 运行失败测试**

Run: `python -m pytest backend/tests/test_paper_current_contract.py rebuild/tests/test_paper_continuity.py -q`

Expected: FAIL，Service/verifier 不存在。

- [ ] **Step 4: 恢复 Paper 状态机和账本**

保留固定输入、exactly-once cycle、signal→risk→order→trade、T+1、成本、
cash ledger、positions、equity snapshots、events 和 stale-feed 门禁。

- [ ] **Step 5: 实现 BitPro ViewModel 适配**

```python
@dataclass(frozen=True)
class PaperInstanceView:
    id: UUID
    name: str
    lifecycle_status: str
    health_state: str
    initial_cash: Decimal
    equity: Decimal | None
    total_pnl: Decimal | None
    return_rate: Decimal | None
    trade_count: int
    position_count: int
    heartbeat_at: datetime | None
```

缺少 equity 时保持 `None`，不得换成 `-100%` 或初始资金，除非 Portfolio 账本明确提供当前现金。

- [ ] **Step 6: 注册写操作并保护现有实例**

生命周期 action 只作用明确 ID；列表/详情 GET 不恢复、不推进。创建 Paper 必须绑定完整晋级回测；
现有实例禁止自动 configure、clear、archive。

- [ ] **Step 7: 运行 API 与完整连续性测试**

Run: `python -m pytest backend/tests/test_paper_current_contract.py rebuild/tests/test_paper_continuity.py -q && python rebuild/verify_paper_continuity.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL"`

Expected: PASS，15/61/47/23/428/681 及每实例关键字段一致。

- [ ] **Step 8: 提交**

```bash
git add backend/app/services/paper_runtime_service.py backend/app/services/paper_application_service.py backend/app/api/endpoints/paper.py backend/app/repositories backend/app/api/api.py backend/tests/test_paper_current_contract.py rebuild/verify_paper_continuity.py rebuild/tests/test_paper_continuity.py
git commit -m "feat(paper): adapt immutable PostgreSQL ledger to BitPro views"
```

### Task 6: 直接适配 BitPro InstanceDashboard 与详情

**Files:**
- Modify: `frontend/src/pages/liveTrading/index.tsx`
- Modify: `frontend/src/pages/liveTrading/InstanceDashboard.tsx`
- Modify: `frontend/src/pages/liveTrading/InstanceMonitor.tsx`
- Modify: `frontend/src/pages/liveTrading/CreateWizard.tsx`
- Modify: `frontend/src/pages/liveTrading/types.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/tests/e2e/rebuild-paper.spec.ts`
- Modify: `docs/pages/模拟盘.md`

**Interfaces:**
- Consumes: `/api/paper/*`。
- Produces: `/paper` BitPro 原生控制台、创建向导和实例详情；无 `/live-real`。

- [ ] **Step 1: 写历史实例与详情失败 E2E**

```typescript
test('paper dashboard renders existing instances without reset', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/paper')
  await expect(page.getByTestId('paper-instance-card')).toHaveCount(15)
  await page.getByTestId('paper-instance-card').first().getByRole('button', { name: '详情' }).click()
  for (const title of ['账户曲线','当前持仓','成交与事件','风控状态','诊断日志']) {
    await expect(page.getByRole('heading', { name: title })).toBeVisible()
  }
  await expect(page.getByText(/USDT|杠杆|强平/)).toHaveCount(0)
})
```

- [ ] **Step 2: 运行失败 E2E**

Run: `npm --prefix frontend run test:e2e -- --grep "paper dashboard renders existing"`

Expected: FAIL，BitPro页面仍绑定旧 live API 或币圈字段。

- [ ] **Step 3: 将 BitPro `/live` 页面改为 `/paper`**

保留 InstanceDashboard、状态分段、筛选、收益排序、卡片密度、详情连续模块和确认弹窗；
移除 live mode switch、杠杆、保证金、强平和交易所账户。

- [ ] **Step 4: 绑定 A股账户与执行字段**

卡片显示人民币、策略版本、股票池/因子、权益、PnL、交易数、心跳；详情显示持仓可用数量、
T+1、订单风险决策、成交成本和绑定快照。

- [ ] **Step 5: 验证 lifecycle actions**

Mock E2E 覆盖 start/pause/resume/stop 二次确认；真实验收阶段只读，不在本任务操作当前实例。

- [ ] **Step 6: 更新页面合同和运行 E2E/build**

Run: `npm --prefix frontend run test:e2e -- --grep "paper dashboard renders existing" && npm --prefix frontend run build`

Expected: PASS；15 个真实实例在隔离库可见，390px 无溢出。

- [ ] **Step 7: 再次运行 continuity verifier**

Run: `python rebuild/verify_paper_continuity.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL"`

Expected: PASS，页面适配没有业务写入。

- [ ] **Step 8: 提交**

```bash
git add frontend/src/pages/liveTrading frontend/src/App.tsx frontend/src/api/client.ts frontend/tests/e2e/rebuild-paper.spec.ts docs/pages/模拟盘.md
git commit -m "feat(paper-ui): use BitPro instance dashboard for A-share Paper"
```

### Task 7: Wave 3 主线闭环验收

**Files:**
- Create: `frontend/tests/e2e/rebuild-mainline.spec.ts`
- Modify: `scripts/check.sh`
- Modify: `docs/progress.md`
- Create: `docs/screenshots/rebuild-wave-3-capture.json`

**Interfaces:**
- Consumes: 策略、回测、Paper 全部 API/页面。
- Produces: Wave 4 可依赖的标准信号、订单、成交、风险和事件链。

- [ ] **Step 1: 写端到端主线 E2E**

```typescript
test('strategy backtest paper is the only execution mainline', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/strategy')
  await page.getByTestId('strategy-card').first().getByRole('button', { name: '回测' }).click()
  await expect(page).toHaveURL(/\/backtest/)
  await expect(page.getByText('快速预检不可晋级')).toBeVisible()
  await page.goto('/paper')
  await expect(page.getByText('仅模拟')).toBeVisible()
  await expect(page.getByText(/真实下单|实盘账户/)).toHaveCount(0)
})
```

- [ ] **Step 2: 运行主线 E2E、后端和全仓检查**

Run: `npm --prefix frontend run test:e2e -- --grep "only execution mainline" && python -m pytest backend/tests/test_strategy_current_contract.py backend/tests/test_backtest_current_contract.py backend/tests/test_paper_current_contract.py -q && ./scripts/check.sh`

Expected: 全绿。

- [ ] **Step 3: 运行真实隔离库页面和 continuity 验收**

真实浏览器只读打开 Strategy、Backtest、Paper 和实例详情；随后运行 verifier。

Expected: 无 console error；历史对象可见；continuity PASS。

- [ ] **Step 4: 更新进度、截图索引并提交**

```bash
git add frontend/tests/e2e/rebuild-mainline.spec.ts scripts/check.sh docs/progress.md docs/screenshots/rebuild-wave-3-capture.json
git commit -m "docs(rebuild): accept strategy backtest Paper mainline"
```
