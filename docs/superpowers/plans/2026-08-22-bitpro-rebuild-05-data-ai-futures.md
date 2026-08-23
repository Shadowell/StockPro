# BitPro-first 重建 Wave 5：数据、AI研发与期货预留实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 直接适配 BitPro 数据中心和 AI研发工作台，恢复 StockPro 的 PostgreSQL 数据可信度、同步、质量与扩展交换能力，并新增不暴露产品入口的传统金融 instrument/期货预留合同。

**Architecture:** `DataApplicationService` 负责数据集、快照、Provider、同步任务、质量与扩展交换；`AIApplicationService` 只消费封存证据并把候选送入当前策略验证/回测。统一 `InstrumentContract` 使用新增 PostgreSQL 定义表承载未来资产类型，但本 Wave 只回填股票/ETF/指数，不实现期货数据与执行。

**Tech Stack:** FastAPI、PostgreSQL、TuShare、AKShare、APScheduler、Qwen/DashScope、React、TypeScript、Playwright、openpyxl/CSV/JSON。

**Spec:** `docs/contracts/active-bitpro-first-a-share-rebuild.md`

## Global Constraints

- 页面 GET 不能触发 Provider、迁移、质量任务、同步或 AI 调用。
- TuShare 是稳定研究主源，AKShare 只能显式补充或整类回退；禁止静默逐行混源。
- 扩展 CSV/JSON/XLSX/HTTPS 只进入隔离暂存，不自动进入策略、因子、回测或 Paper。
- AI 未配置/失败/证据不足时明确失败，禁止 mock、随机或模板化结论。
- AI候选只可保存为待验证策略版本，不自动完整回测、不自动创建 Paper。
- 期货表/接口只为领域预留；导航、路由、同步、回测、Paper 和通道全部隐藏。
- Wave 4 continuity 和安全扫描必须继续全绿。

---

### Task 1: 建立数据可信度当前 API

**Files:**
- Restore/adapt: `backend/app/services/dataset_snapshot_service.py`
- Restore/adapt: `backend/app/services/data_hub_service.py`
- Restore/adapt: `backend/app/services/daily_reference_sync_service.py`
- Restore/adapt: `backend/app/services/tushare_catalog_service.py`
- Restore/adapt: `backend/app/services/extension_data_exchange_service.py`
- Create: `backend/app/services/data_application_service.py`
- Create: `backend/app/api/endpoints/data.py`
- Modify: `backend/app/repositories/protocols.py`
- Modify: `backend/app/repositories/postgres_repository.py`
- Modify: `backend/app/api/api.py`
- Test: `backend/tests/test_data_current_contract.py`
- Test: `backend/tests/test_data_readonly_contract.py`

**Interfaces:**
- Produces: `/api/data/status`、datasets、snapshots、providers、schedules、jobs、quality、exchange imports/exports/http imports。

- [x] **Step 1: 写读取/来源/扩展隔离失败测试**

```python
def test_data_gets_are_readonly_and_report_source_state(client, repositories):
    before = repositories.database.write_count
    response = client.get("/api/data/status", headers=admin_headers()).json()
    assert response["storage"] == "postgresql"
    assert response["provider_state"] in {"ready", "restricted", "unavailable"}
    assert repositories.database.write_count == before
    assert repositories.provider_calls == []

def test_extension_import_is_staged_only(client):
    response = upload_csv(client, "代码,分数\n600519,1.2\n")
    assert response["status"] == "staged"
    assert response["mapping_state"] == "staged_only"
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_data_current_contract.py backend/tests/test_data_readonly_contract.py -q`

Expected: FAIL，当前 Data Service/Router 不存在。

- [x] **Step 3: 恢复 PostgreSQL 数据服务**

保留数据定义、分区、封存快照、来源、watermark、调度、sync job/items、质量报告和迁移健康；
删除 BitPro 文件 Kline store 和 SQLite sync metadata 运行依赖。

- [x] **Step 4: 实现显式写操作**

同步、质量、封存、计划更新和扩展上传均为管理员 POST/PUT；每次写入 job/audit 证据；
相同范围并发任务返回 409。

- [x] **Step 5: 恢复安全扩展交换**

CSV/JSON/XLSX 限制 5MB/10000行/200列，公式拒绝，导出防公式注入；HTTPS 精确 allowlist、公共 DNS、禁止重定向。运行表保持独立 staged-only。

- [x] **Step 6: 运行 API、只读和安全测试**

Run: `python -m pytest backend/tests/test_data_current_contract.py backend/tests/test_data_readonly_contract.py -q && python rebuild/assert_safety.py --root . --format json`

Expected: PASS；GET 写入/Provider 调用为 0。

- [x] **Step 7: 提交**

```bash
git add backend/app/services/dataset_snapshot_service.py backend/app/services/data_hub_service.py backend/app/services/daily_reference_sync_service.py backend/app/services/tushare_catalog_service.py backend/app/services/extension_data_exchange_service.py backend/app/services/data_application_service.py backend/app/api/endpoints/data.py backend/app/repositories backend/app/api/api.py backend/tests/test_data_current_contract.py backend/tests/test_data_readonly_contract.py
git commit -m "feat(data): restore PostgreSQL data trust contract"
```

### Task 2: 直接适配 BitPro 数据中心

**Files:**
- Modify: `frontend/src/pages/DataManager.tsx`
- Create: `frontend/src/pages/data/ExtensionExchangePanel.tsx`
- Create: `frontend/src/pages/data/QualityPanel.tsx`
- Create: `frontend/src/types/data.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/tests/e2e/rebuild-data.spec.ts`
- Modify: `docs/pages/数据中心.md`

**Interfaces:**
- Consumes: `/api/data/*`。
- Produces: BitPro 数据总览、覆盖、任务、数据源、质量、导入导出工作区。

- [x] **Step 1: 写数据状态和写操作失败 E2E**

```typescript
test('data center separates cache snapshot provider and staged exchange', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/data')
  for (const tab of ['总览','研究数据','行情覆盖','同步任务','数据源','质量','导入导出']) {
    await expect(page.getByRole('tab', { name: tab })).toBeVisible()
  }
  await expect(page.getByText('封存研究快照')).toBeVisible()
  await page.getByRole('tab', { name: '导入导出' }).click()
  await expect(page.getByText('仅暂存 · 未映射')).toBeVisible()
})
```

- [x] **Step 2: 运行失败 E2E**

Run: `npm --prefix frontend run test:e2e -- --grep "data center separates"`

Expected: FAIL，BitPro DataManager 仍显示文件 K线/币对语义或缺工作区。

- [x] **Step 3: 保留 BitPro DataManager 信息密度**

保留总览 KPI、覆盖表、任务详情、计划弹窗、symbol维护和错误状态；
替换为 A股数据集、封存快照、TuShare/AKShare目录、质量与扩展交换。

- [x] **Step 4: 管理员/访客边界**

访客可查看状态、覆盖、任务、来源和导出；同步、封存、质量执行、上传、删除和计划修改按钮禁用并由 client 拒绝。

- [x] **Step 5: 更新页面合同并运行桌面/移动端**

Run: `npm --prefix frontend run test:e2e -- --grep "data center separates" && npm --prefix frontend run build`

Expected: PASS；大表可横向滚动但页面根无溢出。

- [x] **Step 6: 提交**

```bash
git add frontend/src/pages/DataManager.tsx frontend/src/pages/data frontend/src/types/data.ts frontend/src/api/client.ts frontend/tests/e2e/rebuild-data.spec.ts docs/pages/数据中心.md
git commit -m "feat(data-ui): adapt BitPro data manager to A-share trust"
```

### Task 3: 建立 AI 当前合同与验证门控

**Files:**
- Restore/adapt: `backend/app/services/agent/`
- Create: `backend/app/services/ai_application_service.py`
- Create: `backend/app/api/endpoints/ai.py`
- Modify: `backend/app/api/api.py`
- Modify: `backend/app/repositories/protocols.py`
- Modify: `backend/app/repositories/postgres_repository.py`
- Test: `backend/tests/test_ai_current_contract.py`

**Interfaces:**
- Produces: `/api/ai/config`、tasks、start/stop、iterations、promote-candidate；promote 只创建/暴露已验证 StrategyVersion，不创建 Paper。

- [x] **Step 1: 写无模型/无证据/禁止自动Paper失败测试**

```python
def test_ai_failure_has_no_mock_and_no_paper(service, repositories):
    service.model_client.available = False
    result = service.start_task(valid_goal())
    assert result.status == "failed"
    assert "未配置" in result.error_message
    assert repositories.strategy.created == []
    assert repositories.paper.created == []

def test_promote_candidate_only_exposes_valid_strategy(service, repositories):
    candidate = service.promote_candidate(valid_iteration_id())
    assert candidate.validation_status == "valid"
    assert repositories.paper.created == []
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_ai_current_contract.py -q`

Expected: FAIL，AI Application Service 不存在或导入 BitPro AI 仍依赖币圈/交易所状态。

- [x] **Step 3: 适配 Planner/Strategist/Backtester/Evaluator**

Planner 固定 A股研究输入；Strategist 生成当前策略合同；AST 验证；Backtester 只跑 quick；
Evaluator 只用回测指标判定，LLM 失败使用明确 deterministic evaluation 并标注，不生成市场预测。

- [x] **Step 4: 清除数字资产 AI 依赖**

不读取 OKX position、funding、Kairos/SuperPnL 数字资产预测、Orbit/星球发帖；
模型仅消费 StockPro 封存证据。

- [x] **Step 5: 注册当前 API 并运行测试**

Run: `python -m pytest backend/tests/test_ai_current_contract.py -q && python rebuild/assert_safety.py --root . --format json`

Expected: PASS；私有交易所调用为 0。

- [x] **Step 6: 提交**

```bash
git add backend/app/services/agent backend/app/services/ai_application_service.py backend/app/api/endpoints/ai.py backend/app/api/api.py backend/app/repositories backend/tests/test_ai_current_contract.py
git commit -m "feat(ai): adapt BitPro research agents to A-share evidence"
```

### Task 4: 直接适配 BitPro AI研发工作台

**Files:**
- Modify: `frontend/src/pages/AILab.tsx`
- Modify: `frontend/src/pages/aiLab/AutoAgentPanel.tsx`
- Modify: `frontend/src/pages/aiLab/ResearchWorkbench.tsx`
- Remove from product route: `frontend/src/pages/aiLab/OrbitPostPanel.tsx`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/types/ai.ts`
- Test: `frontend/tests/e2e/rebuild-ai.spec.ts`
- Modify: `docs/pages/人工智能研发.md`

**Interfaces:**
- Consumes: `/api/ai/*`、策略/回测当前合同。
- Produces: 自动研究、策略研发、现有策略优化三个 BitPro 工作区。

- [x] **Step 1: 写 AI 页面边界失败 E2E**

```typescript
test('AI lab keeps BitPro workbench but cannot auto Paper', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/ai-lab')
  for (const tab of ['自动研究','策略研发','现有策略优化']) await expect(page.getByRole('tab', { name: tab })).toBeVisible()
  await expect(page.getByText(/星球|Orbit|OKX持仓|自动实盘/)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /启动.*Paper|自动模拟/ })).toHaveCount(0)
})
```

- [x] **Step 2: 运行失败 E2E**

Run: `npm --prefix frontend run test:e2e -- --grep "AI lab keeps BitPro"`

Expected: FAIL，导入页面仍有数字资产模块或自动执行入口。

- [x] **Step 3: 适配三个工作区**

保留 BitPro 任务配置、迭代时间线、日志、评分、候选保存和优化对比；
目标、快照、Universe、股票池、因子和日期全部使用 A股字段。

- [x] **Step 4: 诚实模型状态**

未配置模型时显示错误与配置入口；不显示示例输出。候选保存按钮说明仍需完整回测门控。

- [x] **Step 5: 更新文档并运行 E2E/build**

Run: `npm --prefix frontend run test:e2e -- --grep "AI lab keeps BitPro" && npm --prefix frontend run build`

Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add frontend/src/pages/AILab.tsx frontend/src/pages/aiLab/AutoAgentPanel.tsx frontend/src/pages/aiLab/ResearchWorkbench.tsx frontend/src/api/client.ts frontend/src/types/ai.ts frontend/tests/e2e/rebuild-ai.spec.ts docs/pages/人工智能研发.md
git rm frontend/src/pages/aiLab/OrbitPostPanel.tsx
git commit -m "feat(ai-ui): adapt BitPro AI workbench to A-share research"
```

### Task 5: 新增期货领域预留但保持产品隐藏

**Files:**
- Create: `backend/postgres/migrations/202608220001_instrument_contract.sql`
- Modify: `backend/app/domain/instruments/models.py`
- Create: `backend/app/domain/instruments/adapters.py`
- Create: `backend/tests/test_futures_reservation.py`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/MainLayout.tsx`
- Test: `frontend/tests/e2e/rebuild-futures-hidden.spec.ts`

**Interfaces:**
- Produces: `InstrumentAdapter` Protocol、`AshareCashAdapter`；只声明 `CnFuturesCtpAdapter` 和 `UsFuturesBrokerAdapter` 接口，不提供实现或路由。

- [x] **Step 1: 写表结构和隐藏入口失败测试**

```python
def test_future_contract_accepts_real_metadata_without_defaults():
    future = InstrumentContract(
        symbol="IF2609.CFFEX", name="沪深300股指期货2609", asset_class="future",
        market="CN", exchange="CFFEX", currency="CNY", tick_size=0.2, lot_size=1,
        contract_multiplier=300, margin_rate=None, expiry_date=date(2026, 9, 18),
        last_trade_date=date(2026, 9, 18), settlement_type="cash",
        session_calendar="CFFEX_INDEX_FUTURE", shortable=True)
    assert future.margin_rate is None
```

```typescript
test('futures remains hidden until a separate contract ships', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/')
  await expect(page.getByRole('navigation').getByText('期货', { exact: true })).toHaveCount(0)
  await page.goto('/futures')
  await expect(page).toHaveURL('/')
})
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_futures_reservation.py -q && npm --prefix frontend run test:e2e -- --grep "futures remains hidden"`

Expected: FAIL，instrument schema/hidden route 合同尚未实现。

- [x] **Step 3: 添加 additive instrument 表**

迁移创建 `instrument_definitions`，字段与设计合同一致；唯一键为 `(market, exchange, symbol)`；
当前证券通过显式 backfill 映射 stock/ETF/index，期货字段保持 null。迁移不得修改现有证券/行情表。

- [x] **Step 4: 定义 adapter Protocol**

```python
@dataclass(frozen=True)
class TradingSession:
    start: time
    end: time

@dataclass(frozen=True)
class TradingCalendar:
    code: str
    timezone: str
    sessions: tuple[TradingSession, ...]

@dataclass(frozen=True)
class ExecutionRules:
    lot_size: int
    t_plus_days: int
    shortable: bool
    price_limit_required: bool

class InstrumentAdapter(Protocol):
    asset_class: str
    def calendar(self, instrument: InstrumentContract) -> TradingCalendar: ...
    def execution_rules(self, instrument: InstrumentContract) -> ExecutionRules: ...

class CnFuturesCtpAdapter(InstrumentAdapter, Protocol):
    asset_class: Literal["future"]
    market: Literal["CN"]

class UsFuturesBrokerAdapter(InstrumentAdapter, Protocol):
    asset_class: Literal["future"]
    market: Literal["US"]
```

本 Wave 只实例化 `AshareCashAdapter`；期货 Protocol 无 provider、credential、network 方法实现。

- [x] **Step 5: 隐藏所有期货入口**

不注册 `/futures` 页面和 API；导航无期货；访问路径回首页。测试不得通过 feature flag 临时打开。

- [x] **Step 6: 运行迁移、模型、页面和安全测试**

Run: `python -m pytest backend/tests/test_futures_reservation.py -q && npm --prefix frontend run test:e2e -- --grep "futures remains hidden" && python rebuild/assert_safety.py --root . --format json`

Expected: PASS，迁移数为 38，数字资产/实盘/期货执行计数为 0。

- [x] **Step 7: 提交**

```bash
git add backend/postgres/migrations/202608220001_instrument_contract.sql backend/app/domain/instruments backend/tests/test_futures_reservation.py frontend/src/App.tsx frontend/src/components/MainLayout.tsx frontend/tests/e2e/rebuild-futures-hidden.spec.ts
git commit -m "feat(instruments): reserve hidden futures domain contract"
```

### Task 6: Wave 5 能力层验收

**Files:**
- Create: `backend/tests/test_data_ai_current_contract.py`
- Create: `frontend/tests/e2e/rebuild-capabilities.spec.ts`
- Modify: `scripts/check.sh`
- Modify: `docs/progress.md`
- Create: `docs/screenshots/rebuild-wave-5-capture.json`

**Interfaces:**
- Consumes: Data、AI、instrument reservation。
- Produces: Wave 6 使用的最终功能集合和 capability manifest。

- [ ] **Step 1: 写 capability manifest 测试**

```python
def test_capabilities_report_enabled_and_hidden_domains(client):
    payload = client.get("/api/capabilities", headers=admin_headers()).json()
    assert payload["enabled"] == ["stock", "etf", "index"]
    assert payload["reserved"] == ["future"]
    assert payload["live_trading"] is False
    assert payload["database"] == "postgresql"
```

- [ ] **Step 2: 运行全量 Data/AI/Futures 测试**

Run: `python -m pytest backend/tests/test_data_current_contract.py backend/tests/test_data_readonly_contract.py backend/tests/test_ai_current_contract.py backend/tests/test_futures_reservation.py backend/tests/test_data_ai_current_contract.py -q`

Expected: PASS。

- [ ] **Step 3: 运行页面、build、安全和 continuity**

Run: `npm --prefix frontend run test:e2e -- --grep "data center|AI lab|futures remains hidden" && npm --prefix frontend run build && python rebuild/assert_safety.py --root . --format json && python rebuild/verify_paper_continuity.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL"`

Expected: 全绿；Paper 连续；期货隐藏。

- [ ] **Step 4: 更新截图、进度并提交**

```bash
git add backend/tests/test_data_ai_current_contract.py frontend/tests/e2e/rebuild-capabilities.spec.ts scripts/check.sh docs/progress.md docs/screenshots/rebuild-wave-5-capture.json
git commit -m "docs(rebuild): accept data AI and instrument capabilities"
```
