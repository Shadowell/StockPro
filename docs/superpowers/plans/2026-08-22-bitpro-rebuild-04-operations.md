# BitPro-first 重建 Wave 4：盯盘、信号、监控与复盘实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 直接适配 BitPro 的盯盘、信号中心、监控和复盘页面，让所有运行证据回链同一 PostgreSQL Paper 实例，并保证观察和告警操作不能创建订单。

**Architecture:** `OperationsApplicationService` 以 Paper ID 为关联主键读取 signals/orders/trades/positions/risk/events/alerts/notifications/reviews，输出四个页面 ViewModel。信号中心负责审计与确认，盯盘负责市场/策略观察，监控负责系统健康，复盘负责交易日封存；职责不混写。

**Tech Stack:** FastAPI、PostgreSQL、React、TypeScript、ECharts、WebSocket/轮询读模型、Playwright。

**Spec:** `docs/contracts/active-bitpro-first-a-share-rebuild.md`

## Global Constraints

- Wave 3 Paper continuity 必须通过。
- 所有运行对象必须保留 `paper_instance_id` 和源对象 ID。
- 告警规则预览只读；显式评估只允许新增 alert/notification，`orders_created` 固定为 0。
- 信号确认、告警确认和通知确认不得删除原始证据。
- Monitor 的服务健康不能覆盖 Paper 生命周期；陈旧数据与策略失败分开表达。
- Review 按交易日组装；读取页面不自动 assemble、save 或 seal。
- 四个页面不读取真实券商账户或数字资产私有 API。

---

### Task 1: 定义统一运行证据模型与 Operations Service

**Files:**
- Create: `backend/app/domain/operations/models.py`
- Create: `backend/app/services/operations_application_service.py`
- Modify: `backend/app/repositories/protocols.py`
- Modify: `backend/app/repositories/postgres_repository.py`
- Test: `backend/tests/test_operations_evidence_chain.py`

**Interfaces:**
- Produces: `SignalView`, `AlertView`, `WatchContextView`, `MonitorView`, `ReviewView`；所有对象携带 source ID、Paper ID、时间和 data purpose。

- [x] **Step 1: 写同源证据失败测试**

```python
def test_operations_objects_link_same_paper_instance(service):
    context = service.watch_context(scope="business")
    paper_id = context.instances[0].id
    assert all(item.paper_instance_id == paper_id for item in context.signals)
    assert all(item.paper_instance_id == paper_id for item in context.orders)
    assert all(item.paper_instance_id == paper_id for item in context.trades)
    assert all(item.paper_instance_id == paper_id for item in context.positions)
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_operations_evidence_chain.py -q`

Expected: FAIL，Operations Service 不存在。

- [x] **Step 3: 定义不可变 ViewModel**

```python
@dataclass(frozen=True)
class SignalView:
    id: str
    paper_instance_id: UUID
    strategy_version_id: UUID
    symbol: str
    signal_type: str
    status: str
    signal_time: datetime
    evidence: Mapping[str, object]

@dataclass(frozen=True)
class AlertView:
    id: UUID
    paper_instance_id: UUID | None
    severity: str
    category: str
    title: str
    message: str
    source_object_type: str
    source_object_id: str
    triggered_at: datetime
    status: str
```

- [x] **Step 4: 实现 Repository 聚合查询**

使用现有 `strategy_signals`、orders、trades、positions、risk events、Paper events、alerts 和 notification deliveries；业务 scope 排除 acceptance/seed，audit scope 保留。

- [x] **Step 5: 运行测试和只读检查**

Run: `python -m pytest backend/tests/test_operations_evidence_chain.py -q`

Expected: PASS；构造 Watch/Monitor/Review read model 没有写入。

- [x] **Step 6: 提交**

```bash
git add backend/app/domain/operations backend/app/services/operations_application_service.py backend/app/repositories backend/tests/test_operations_evidence_chain.py
git commit -m "feat(operations): unify PostgreSQL runtime evidence"
```

### Task 2: 建立信号与告警当前 API

**Files:**
- Restore/adapt: `backend/app/services/watch_rule_service.py`
- Create: `backend/app/services/signal_application_service.py`
- Create: `backend/app/api/endpoints/signals.py`
- Create: `backend/app/api/endpoints/watch.py`
- Modify: `backend/app/api/api.py`
- Test: `backend/tests/test_signal_watch_current_api.py`

**Interfaces:**
- Produces: `/api/signals`、signal detail/acknowledge；`/api/watch/context`、alerts、rules、preview、evaluate。

- [x] **Step 1: 写 alert-only 门禁失败测试**

```python
def test_rule_preview_is_readonly_and_evaluate_never_orders(client, repository):
    before = repository.ledger_counts()
    preview = client.post("/api/watch/rules/rule-1/preview", headers=admin_headers()).json()
    assert preview["writes_performed"] is False
    evaluated = client.post("/api/watch/rules/rule-1/evaluate", headers=admin_headers()).json()
    assert evaluated["orders_created"] == 0
    after = repository.ledger_counts()
    assert after.orders == before.orders
    assert after.trades == before.trades
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_signal_watch_current_api.py -q`

Expected: FAIL，当前 endpoints 不存在。

- [x] **Step 3: 恢复四类版本化规则**

策略、指标、价格、异动规则使用严格字段/操作符 allowlist；更新创建新版本；
preview 零写入；evaluate 只写 alerts 和 in-app delivery，并去重。

- [x] **Step 4: 实现信号审计和确认**

确认只更新状态/确认人/时间；原 signal、payload、evidence、source IDs 保留。

- [x] **Step 5: 注册当前 API 并运行测试**

Run: `python -m pytest backend/tests/test_signal_watch_current_api.py backend/tests/test_operations_evidence_chain.py -q && python rebuild/verify_paper_continuity.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL"`

Expected: PASS；Paper ledger 无变化。

- [x] **Step 6: 提交**

```bash
git add backend/app/services/watch_rule_service.py backend/app/services/signal_application_service.py backend/app/api/endpoints/signals.py backend/app/api/endpoints/watch.py backend/app/api/api.py backend/tests/test_signal_watch_current_api.py
git commit -m "feat(signals): restore alert-only A-share signal audit"
```

### Task 3: 直接适配 BitPro 信号中心与盯盘

**Files:**
- Modify: `frontend/src/pages/SignalCenter.tsx`
- Modify: `frontend/src/pages/WatchMarket.tsx`
- Modify: `frontend/src/components/WatchDataCharts.tsx`
- Modify: `frontend/src/components/WatchKlineChart.tsx`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/types/operations.ts`
- Test: `frontend/tests/e2e/rebuild-signals-watch.spec.ts`
- Modify: `docs/pages/信号中心.md`
- Modify: `docs/pages/盯盘.md`

**Interfaces:**
- Consumes: `/api/signals*`、`/api/watch/*`。
- Produces: 独立信号审计页和盯盘工作台。

- [x] **Step 1: 写信号/盯盘职责失败 E2E**

```typescript
test('signal center audits and watch observes without order actions', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/signals')
  await expect(page.getByRole('heading', { name: '信号中心' })).toBeVisible()
  await expect(page.getByText('投递记录')).toBeVisible()
  await page.goto('/watch')
  for (const tab of ['策略信号','订单与成交','图表联动','规则','告警']) await expect(page.getByRole('tab', { name: tab })).toBeVisible()
  await expect(page.getByRole('button', { name: /下单|买入|卖出/ })).toHaveCount(0)
})
```

- [x] **Step 2: 运行失败 E2E**

Run: `npm --prefix frontend run test:e2e -- --grep "signal center audits"`

Expected: FAIL，页面仍为未适配或含币圈账户/下单动作。

- [x] **Step 3: 适配 SignalCenter**

保留 BitPro 筛选、信号详情、payload preview、通道和投递记录；替换为 A股 symbol、策略/Paper lineage、站内/log通知。真实 Bot 通道不在本合同启用。

- [x] **Step 4: 适配 WatchMarket**

保留 BitPro K线、买卖点、对象切换和高密度表格；账户选择改为 Paper 实例/股票，移除交易所私有账户和执行按钮。

- [x] **Step 5: 接入规则工作台**

预览和显式评估分离；确认弹窗写明“只生成告警，不下单、不改 Paper”。访客评估按钮禁用。

- [x] **Step 6: 文档与桌面/移动端验收**

Run: `npm --prefix frontend run test:e2e -- --grep "signal center audits" && npm --prefix frontend run build`

Expected: PASS；390px 可操作，无币圈字段。

- [x] **Step 7: 提交**

```bash
git add frontend/src/pages/SignalCenter.tsx frontend/src/pages/WatchMarket.tsx frontend/src/components/WatchDataCharts.tsx frontend/src/components/WatchKlineChart.tsx frontend/src/api/client.ts frontend/src/types/operations.ts frontend/tests/e2e/rebuild-signals-watch.spec.ts docs/pages/信号中心.md docs/pages/盯盘.md
git commit -m "feat(operations-ui): adapt BitPro signals and watch"
```

### Task 4: 建立 Monitor 当前 API 与 BitPro 监控页

**Files:**
- Create: `backend/app/services/monitor_application_service.py`
- Create: `backend/app/api/endpoints/monitor.py`
- Modify: `backend/app/api/api.py`
- Test: `backend/tests/test_monitor_current_api.py`
- Modify: `frontend/src/pages/Monitor.tsx`
- Test: `frontend/tests/e2e/rebuild-monitor.spec.ts`
- Modify: `docs/pages/监控.md`

**Interfaces:**
- Produces: `GET /api/monitor/summary`、strategies、data、risk、notifications；BitPro Monitor ViewModel。

- [ ] **Step 1: 写健康与生命周期分离失败测试**

```python
def test_stale_service_does_not_change_paper_lifecycle(service):
    view = service.summary(scope="business")
    instance = view.strategy_health[0]
    assert instance.lifecycle_status == "running"
    assert instance.health_state == "stale"
    assert view.overall_status == "warning"
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_monitor_current_api.py -q`

Expected: FAIL，Monitor Service 不存在。

- [ ] **Step 3: 实现 PG health 聚合**

读取 service health snapshots、Paper heartbeats/cycles/equity/drawdown/ledger difference、risk alerts 和 notification counts；response generation time 不刷新 evidence time。

- [ ] **Step 4: 适配 BitPro Monitor 页面**

保留组合 KPI、策略健康、告警弹窗、通知和数据状态；删除真实账户权益、加密策略和交易所连接状态。

- [ ] **Step 5: 运行 API/E2E/build**

Run: `python -m pytest backend/tests/test_monitor_current_api.py -q && npm --prefix frontend run test:e2e -- --grep "monitor separates lifecycle" && npm --prefix frontend run build`

Expected: PASS，失败加载不显示虚假 0。

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/monitor_application_service.py backend/app/api/endpoints/monitor.py backend/app/api/api.py backend/tests/test_monitor_current_api.py frontend/src/pages/Monitor.tsx frontend/tests/e2e/rebuild-monitor.spec.ts docs/pages/监控.md
git commit -m "feat(monitor): adapt BitPro health console to Paper evidence"
```

### Task 5: 建立交易日复盘当前 API 与 BitPro 复盘页

**Files:**
- Restore/adapt: `backend/app/services/daily_review_service.py`
- Create: `backend/app/services/review_application_service.py`
- Create: `backend/app/api/endpoints/review.py`
- Modify: `backend/app/api/api.py`
- Test: `backend/tests/test_review_current_api.py`
- Modify: `frontend/src/pages/ReviewDashboard.tsx`
- Test: `frontend/tests/e2e/rebuild-review.spec.ts`
- Modify: `docs/pages/复盘中心.md`

**Interfaces:**
- Produces: `/api/review/dates`、`/api/review/{trade_date}`、assemble、save、seal、object link；`DailyReviewView`。

- [ ] **Step 1: 写读取不组装与封存不可变失败测试**

```python
def test_review_get_is_readonly_and_sealed_review_is_immutable(client, repository):
    before = repository.write_count
    response = client.get("/api/review/2025-01-02", headers=admin_headers())
    assert response.status_code == 200
    assert repository.write_count == before
    sealed = response.json()["review"]
    if sealed and sealed["status"] == "sealed":
        assert client.put("/api/review/2025-01-02", json={"summary": "change"}, headers=admin_headers()).status_code == 400
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_review_current_api.py -q`

Expected: FAIL，Review Service/Router 不存在。

- [ ] **Step 3: 恢复交易日组装和封存**

市场、股票池、策略、风险、订单、成交、表现对象保留 source route/ID/hash；assemble 是显式 POST，save/seal 管理员限定。

- [ ] **Step 4: 适配 BitPro ReviewDashboard**

保留 KPI、排名、热力图、结论和筛选密度；将小时级币圈复盘替换为 A股交易日 Snapshot、证据时间线、总结和次日计划。

- [ ] **Step 5: 运行 API/E2E 与历史复盘验证**

Run: `python -m pytest backend/tests/test_review_current_api.py -q && npm --prefix frontend run test:e2e -- --grep "daily review"`

Expected: PASS；现有 1 份复盘可读取且未变化。

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/daily_review_service.py backend/app/services/review_application_service.py backend/app/api/endpoints/review.py backend/app/api/api.py backend/tests/test_review_current_api.py frontend/src/pages/ReviewDashboard.tsx frontend/tests/e2e/rebuild-review.spec.ts docs/pages/复盘中心.md
git commit -m "feat(review): adapt BitPro review to A-share trading days"
```

### Task 6: Wave 4 运行证据链验收

**Files:**
- Create: `frontend/tests/e2e/rebuild-operations.spec.ts`
- Modify: `scripts/check.sh`
- Modify: `docs/progress.md`
- Create: `docs/screenshots/rebuild-wave-4-capture.json`

**Interfaces:**
- Consumes: Watch/Signals/Monitor/Review API 和页面。
- Produces: Wave 5 可使用的统一通知、数据状态和复盘入口。

- [ ] **Step 1: 写跨页面对象链 E2E**

```typescript
test('signal order trade alert and review keep one Paper lineage', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/signals')
  const paperId = await page.getByTestId('signal-row').first().getAttribute('data-paper-instance-id')
  await page.getByTestId('signal-row').first().click()
  await expect(page.getByText(String(paperId))).toBeVisible()
  await page.goto('/monitor')
  await expect(page.locator(`[data-paper-instance-id="${paperId}"]`)).toBeVisible()
})
```

- [ ] **Step 2: 运行后端与页面矩阵**

Run: `python -m pytest backend/tests/test_operations_evidence_chain.py backend/tests/test_signal_watch_current_api.py backend/tests/test_monitor_current_api.py backend/tests/test_review_current_api.py -q && npm --prefix frontend run test:e2e -- --grep "signal|watch|monitor|review"`

Expected: PASS。

- [ ] **Step 3: 运行 safety/Paper 对账和全仓检查**

Run: `python rebuild/assert_safety.py --root . --format json && python rebuild/verify_paper_continuity.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL" && ./scripts/check.sh`

Expected: 全绿；61/47/23/428/681 不变。

- [ ] **Step 4: 更新截图、进度并提交**

```bash
git add frontend/tests/e2e/rebuild-operations.spec.ts scripts/check.sh docs/progress.md docs/screenshots/rebuild-wave-4-capture.json
git commit -m "docs(rebuild): accept operations evidence chain"
```
