# BitPro-first 重建 Wave 2：研究工作区实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 BitPro 首页与行情交互骨架交付真实 A股首页、行情、股票池和因子工作区，并通过唯一 `/api/*` 与现有 PostgreSQL 快照/因子/股票池事实连接。

**Architecture:** `ResearchApplicationService` 组合市场、证券、因子和股票池 Repository，输出前端稳定 ViewModel。BitPro 页面组件保留布局和交互，币对、资金费率、链上字段替换成 A股指数、证券、市场宽度、涨跌停、板块、因子和股票池证据；页面读取全程 cache/PG-only。

**Tech Stack:** FastAPI、PostgreSQL、React、TypeScript、ECharts、Playwright、TuShare/AKShare 缓存（读取阶段不调用 Provider）。

**Spec:** `docs/contracts/active-bitpro-first-a-share-rebuild.md`

## Global Constraints

- Wave 1 必须全绿；所有业务页面只调用当前 `/api/*`。
- 页面 GET 不得写库、调用 TuShare/AKShare、启动同步或创建快照。
- 涨跌停、宽度、板块、财务和热榜必须携带来源时间/交易日/状态；缺失保持 `null`。
- 股票池和因子下游只引用封存快照 ID，不复制硬编码证券列表。
- BitPro 页面结构优先直接保留，禁止退化为简化卡片页。
- 每个页面完成后更新对应 `docs/pages/*.md` 并通过 1440px/390px。

---

### Task 1: 定义传统金融 Instrument 与研究 ViewModel

**Files:**
- Create: `backend/app/domain/instruments/models.py`
- Create: `backend/app/domain/research/models.py`
- Modify: `backend/app/repositories/protocols.py`
- Create: `backend/tests/test_research_models.py`
- Create: `frontend/src/types/research.ts`

**Interfaces:**
- Produces: `InstrumentContract`, `MarketOverviewView`, `InstrumentDetailView`, `StockPoolView`, `FactorView`；Wave 2 页面和 Wave 3 主线共同使用。

- [x] **Step 1: 写模型失败测试**

```python
def test_stock_instrument_keeps_futures_fields_unavailable():
    item = InstrumentContract.stock(symbol="600519.SH", exchange="SSE", currency="CNY", tick_size=0.01, lot_size=100)
    assert item.asset_class == "stock"
    assert item.market == "CN"
    assert item.contract_multiplier is None
    assert item.margin_rate is None
    assert item.expiry_date is None
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_research_models.py -q`

Expected: FAIL，模型模块不存在。

- [x] **Step 3: 实现不可变领域模型**

```python
@dataclass(frozen=True)
class InstrumentContract:
    symbol: str
    name: str | None
    asset_class: Literal["stock", "etf", "index", "future"]
    market: Literal["CN", "US"]
    exchange: str
    currency: str
    tick_size: Decimal
    lot_size: int
    contract_multiplier: Decimal | None = None
    margin_rate: Decimal | None = None
    expiry_date: date | None = None
    last_trade_date: date | None = None
    settlement_type: str | None = None
    session_calendar: str | None = None
    shortable: bool = False

    @classmethod
    def stock(cls, symbol: str, exchange: str, currency: str, tick_size: Decimal, lot_size: int, name: str | None = None) -> "InstrumentContract":
        return cls(symbol=symbol, name=name, asset_class="stock", market="CN", exchange=exchange,
                   currency=currency, tick_size=tick_size, lot_size=lot_size,
                   session_calendar="CN_A_SHARE", shortable=False)
```

`MarketOverviewView` 必须包含 `indices`、`breadth`、`turnover`、`limit_ecology`、
`sector_flows`、`source_label`、`source_updated_at`、`trade_date`、`data_status`。

- [x] **Step 4: 定义前后端同名字段**

`frontend/src/types/research.ts` 使用相同 snake_case API 字段，不在 client 中做多套兼容映射。

- [x] **Step 5: 运行测试和类型检查**

Run: `python -m pytest backend/tests/test_research_models.py -q && npm --prefix frontend run check`

Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add backend/app/domain/instruments backend/app/domain/research backend/app/repositories/protocols.py backend/tests/test_research_models.py frontend/src/types/research.ts
git commit -m "feat(research): define traditional market view models"
```

### Task 2: 建立市场与证券当前 API

**Files:**
- Restore/adapt from StockPro baseline: `backend/app/services/market_service.py`
- Restore/adapt: `backend/app/services/market_research_service.py`
- Create: `backend/app/services/research_application_service.py`
- Create: `backend/app/api/endpoints/market.py`
- Modify: `backend/app/repositories/postgres_repository.py`
- Modify: `backend/app/api/api.py`
- Test: `backend/tests/test_market_current_api.py`
- Test: `backend/tests/test_research_pages_readonly.py`

**Interfaces:**
- Produces: `GET /api/market/overview`、`GET /api/market/instruments`、`GET /api/market/instruments/{symbol}`、`GET /api/market/instruments/{symbol}/daily`、`GET /api/market/instruments/{symbol}/intraday`、`GET /api/market/instruments/{symbol}/order-book`、`GET/POST/DELETE /api/market/watchlist`。

- [x] **Step 1: 写真实形状和只读失败测试**

```python
def test_market_overview_keeps_missing_metrics_null(client, repositories):
    repositories.market.overview.return_value = MarketOverviewView(
        indices=[], breadth=None, turnover=None, limit_ecology=None,
        sector_flows=[], source_label="PostgreSQL market cache",
        source_updated_at=None, trade_date=None, data_status="empty")
    payload = client.get("/api/market/overview", headers=admin_headers()).json()
    assert payload["breadth"] is None
    assert payload["data_status"] == "empty"
    assert repositories.database.executed_writes == []
    assert repositories.provider_calls == []
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_market_current_api.py backend/tests/test_research_pages_readonly.py -q`

Expected: FAIL，当前市场 Service/Router 尚未存在。

- [x] **Step 3: 从 StockPro 基线恢复算法并包入 Application Service**

只恢复市场计算与查询所需文件，不恢复旧 Router。`ResearchApplicationService` 方法固定为：

```python
class ResearchApplicationService:
    def market_overview(self) -> MarketOverviewView: ...
    def search_instruments(self, query: str, asset_class: str | None, limit: int) -> list[InstrumentContract]: ...
    def instrument_detail(self, symbol: str) -> InstrumentDetailView: ...
```

- [x] **Step 4: 实现 PG-only Repository 查询**

从 `all_stocks_realtime`、指数缓存、市场证据快照、日线/分时/盘口/财务缓存读取；
查询必须限定返回数并保留 `source_updated_at`。写 watchlist 只保存 symbol/note，不复制价格。

- [x] **Step 5: 注册当前 API 并删除重复消费者**

前端只调用上述路径；不存在 `/stocks/*`、旧 market alias 或版本路径。所有符号规范化集中在领域层。

- [x] **Step 6: 运行 API、只读和安全测试**

Run: `python -m pytest backend/tests/test_market_current_api.py backend/tests/test_research_pages_readonly.py rebuild/tests/test_safety.py -q`

Expected: PASS；GET 请求写入数和 Provider 调用数为 0。

- [x] **Step 7: 提交**

```bash
git add backend/app/services/market_service.py backend/app/services/market_research_service.py backend/app/services/research_application_service.py backend/app/api/endpoints/market.py backend/app/repositories backend/app/api/api.py backend/tests/test_market_current_api.py backend/tests/test_research_pages_readonly.py
git commit -m "feat(market): expose current A-share research API"
```

### Task 3: 直接适配 BitPro 首页

**Files:**
- Modify: `frontend/src/pages/Home.tsx`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/tests/e2e/rebuild-home.spec.ts`
- Modify: `docs/pages/首页.md`

**Interfaces:**
- Consumes: `GET /api/market/overview`。
- Produces: BitPro 首页布局的 A股首页。

- [x] **Step 1: 写首页 E2E 失败测试**

```typescript
test('home keeps BitPro density with A-share facts', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/')
  for (const heading of ['主要指数','市场宽度','涨停生态','板块资金','主线状态']) {
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
  }
  await expect(page.getByText(/BTC|ETH|资金费率|永续/)).toHaveCount(0)
})
```

- [x] **Step 2: 运行失败 E2E**

Run: `npm --prefix frontend run test:e2e -- --grep "home keeps BitPro density"`

Expected: FAIL，页面仍为未适配状态。

- [x] **Step 3: 保留 BitPro Home 结构并替换数据绑定**

保留首屏模块顺序、卡片尺寸、榜单、loading/error skeleton 和移动端折叠；
移除资金费率、新币、加密涨幅榜，替换成 API 已提供的 A股模块。

- [x] **Step 4: 实现每块独立状态**

核心 overview 失败时首页显示错误；可选 sector/limit 数据缺失只影响自身模块，不能把 null 显示为 0。

- [x] **Step 5: 更新页面合同并运行桌面/移动端**

Run: `npm --prefix frontend run test:e2e -- --grep "home keeps BitPro density"`

Expected: 1440px 与 390px PASS，无横向溢出。

- [x] **Step 6: 提交**

```bash
git add frontend/src/pages/Home.tsx frontend/src/api/client.ts frontend/tests/e2e/rebuild-home.spec.ts docs/pages/首页.md
git commit -m "feat(home): adapt BitPro dashboard to A-share evidence"
```

### Task 4: 直接适配 BitPro 行情页

**Files:**
- Modify: `frontend/src/pages/Market.tsx`
- Modify: `frontend/src/components/KlineChart.tsx`
- Modify: `frontend/src/components/OrderBookChart.tsx`
- Modify: `frontend/src/components/SymbolSearch.tsx`
- Create: `frontend/src/components/MarketWatchlist.tsx`
- Test: `frontend/tests/e2e/rebuild-market.spec.ts`
- Modify: `docs/pages/行情.md`

**Interfaces:**
- Consumes: market instrument/search/chart/order-book/watchlist APIs。
- Produces: 股票/ETF/指数的 BitPro 行情工作台。

- [x] **Step 1: 写搜索、图表和空态失败测试**

```typescript
test('market switches among stock ETF and index without crypto controls', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/market')
  await page.getByLabel('证券搜索').fill('600519')
  await page.getByRole('option', { name: /贵州茅台/ }).click()
  await expect(page.getByTestId('kline-chart')).toBeVisible()
  await expect(page.getByText('100股')).toBeVisible()
  await expect(page.getByText(/合约|永续|资金费率/)).toHaveCount(0)
})
```

- [x] **Step 2: 运行失败 E2E**

Run: `npm --prefix frontend run test:e2e -- --grep "market switches"`

Expected: FAIL，BitPro CryptoSelect/合约控制仍存在。

- [x] **Step 3: 替换 instrument selector**

`SymbolSearch` 按 `asset_class` 显示股票/ETF/指数；保留 BitPro 搜索弹层、键盘导航和最近对象。

- [x] **Step 4: 适配 K线、盘口和证据栏**

K线显示研究截止日、复权口径；盘口使用未复权可交易价。缓存冲突时显示冲突面板，
不合成统一价格。指数无盘口时显示明确不可用。

- [x] **Step 5: 接入自选与指数二级页**

自选只保存代码/备注；指数复用指数缓存。所有 tab 通过 URL 保存状态。

- [x] **Step 6: 更新文档并运行真实/Mock E2E**

Run: `npm --prefix frontend run test:e2e -- --grep "market switches" && npm --prefix frontend run build`

Expected: PASS，无币圈字段和假数据。

- [x] **Step 7: 提交**

```bash
git add frontend/src/pages/Market.tsx frontend/src/components/KlineChart.tsx frontend/src/components/OrderBookChart.tsx frontend/src/components/SymbolSearch.tsx frontend/src/components/MarketWatchlist.tsx frontend/tests/e2e/rebuild-market.spec.ts docs/pages/行情.md
git commit -m "feat(market): adapt BitPro terminal to A-share instruments"
```

### Task 5: 迁移股票池当前 API 与页面

**Files:**
- Restore/adapt: `backend/app/services/stock_pool_service.py`
- Create: `backend/app/api/endpoints/pools.py`
- Modify: `backend/app/repositories/protocols.py`
- Modify: `backend/app/repositories/postgres_repository.py`
- Create: `frontend/src/pages/StockPools.tsx`
- Test: `backend/tests/test_pool_current_api.py`
- Test: `frontend/tests/e2e/rebuild-pools.spec.ts`
- Create/Modify: `docs/pages/股票池.md`

**Interfaces:**
- Produces: `/api/pools`、`/api/pools/{id}/generate`、`/api/pools/{id}/snapshots`、`/api/pool-snapshots`；`StockPoolSnapshotView` 供 Wave 3 回测使用。

- [x] **Step 1: 写版本化规则与封存失败测试**

```python
def test_pool_snapshot_never_copies_unsealed_members(client):
    created = client.post("/api/pools", json=valid_rule(), headers=admin_headers()).json()
    generated = client.post(f"/api/pools/{created['id']}/generate", json={"trade_date": "2025-01-02"}, headers=admin_headers()).json()
    sealed = client.post(f"/api/pools/{created['id']}/snapshots", json={"generation_id": generated["id"]}, headers=admin_headers()).json()
    assert sealed["status"] == "sealed"
    assert sealed["manifest_hash"]
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_pool_current_api.py -q`

Expected: FAIL，当前 pools API 不存在。

- [x] **Step 3: 恢复 StockPoolService 并注册当前路径**

保留 PostgreSQL 规则版本、生成记录、成员 evidence/hash、快照不可变和 AND/OR 筛选；
删除旧路径/旧 Router。

- [x] **Step 4: 用 BitPro Strategy/Data 节奏构建股票池页面**

页面必须包含目录、筛选器、生成、成员、证据和封存，不简化为跳转卡片。

- [x] **Step 5: 运行 API/E2E 并更新文档**

Run: `python -m pytest backend/tests/test_pool_current_api.py -q && npm --prefix frontend run test:e2e -- --grep "stock pool"`

Expected: PASS；页面读取不生成成员或快照。

- [x] **Step 6: 提交**

```bash
git add backend/app/services/stock_pool_service.py backend/app/api/endpoints/pools.py backend/app/repositories frontend/src/pages/StockPools.tsx backend/tests/test_pool_current_api.py frontend/tests/e2e/rebuild-pools.spec.ts docs/pages/股票池.md
git commit -m "feat(pools): restore immutable A-share stock pools"
```

### Task 6: 迁移因子当前 API 与 BitPro FactorLab 页面

**Files:**
- Restore/adapt: `backend/app/services/factor_research_service.py`
- Restore/adapt: `backend/app/services/factor_sync_service.py`
- Create: `backend/app/api/endpoints/factors.py`
- Modify: `backend/app/repositories/protocols.py`
- Modify: `backend/app/repositories/postgres_repository.py`
- Modify: `frontend/src/pages/FactorLab.tsx`
- Test: `backend/tests/test_factor_current_api.py`
- Test: `frontend/tests/e2e/rebuild-factors.spec.ts`
- Modify: `docs/pages/因子库.md`

**Interfaces:**
- Produces: `/api/factors`、versions、runs、metrics、correlations、snapshots、values；`FactorSnapshotView` 供 Wave 3 使用。

- [x] **Step 1: 写不可变版本与缺失指标失败测试**

```python
def test_factor_metrics_keep_pending_values_null(client):
    payload = client.get("/api/factors/momentum_20d/metrics", headers=admin_headers()).json()
    pending = next(item for item in payload["items"] if item["metric_code"] == "rank_ic")
    assert pending["metric_value"] is None
    assert pending["pending_reason"]
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_factor_current_api.py -q`

Expected: FAIL，Factor 当前 API 不存在。

- [x] **Step 3: 恢复 PostgreSQL Factor Service**

保留定义、版本、计算、诊断、成熟指标、相关性、快照和封存边界；
BitPro SQLite FactorLab repository 不作为运行实现。

- [x] **Step 4: 适配 BitPro FactorLab 页面**

保留目录、详情、运行记录、单因子、多因子、相关性和值浏览；绑定当前 API，
页面不得把目录存在表述成因子已验证。

- [x] **Step 5: 运行 API、页面和只读测试**

Run: `python -m pytest backend/tests/test_factor_current_api.py backend/tests/test_research_pages_readonly.py -q && npm --prefix frontend run test:e2e -- --grep "factor lab"`

Expected: PASS；GET 不写库，pending 保持 null。

- [x] **Step 6: 提交**

```bash
git add backend/app/services/factor_research_service.py backend/app/services/factor_sync_service.py backend/app/api/endpoints/factors.py backend/app/repositories frontend/src/pages/FactorLab.tsx backend/tests/test_factor_current_api.py frontend/tests/e2e/rebuild-factors.spec.ts docs/pages/因子库.md
git commit -m "feat(factors): connect BitPro FactorLab to PostgreSQL"
```

### Task 7: Wave 2 研究工作区验收

**Files:**
- Modify: `scripts/check.sh`
- Modify: `docs/progress.md`
- Create: `docs/screenshots/rebuild-wave-2-capture.json`

**Interfaces:**
- Consumes: 首页、行情、股票池、因子全部当前 API 和页面。
- Produces: Wave 3 可使用的封存数据/因子/股票池合同与页面验收证据。

- [ ] **Step 1: 运行全量研究 API 测试**

Run: `python -m pytest backend/tests/test_market_current_api.py backend/tests/test_pool_current_api.py backend/tests/test_factor_current_api.py backend/tests/test_research_pages_readonly.py -q`

Expected: PASS。

- [ ] **Step 2: 运行桌面和移动端页面矩阵**

Run: `npm --prefix frontend run test:e2e -- --grep "home|market|stock pool|factor lab"`

Expected: 所有页面 1440px/390px PASS，无横向溢出、无币圈文案、无 console error。

- [ ] **Step 3: 真实隔离数据库浏览器验收**

使用 `MOCK_API=false`，检查真实 source/trade_date/freshness/empty/error，不执行同步、生成或封存。

- [ ] **Step 4: 运行安全与 Paper 对账**

Run: `python rebuild/assert_safety.py --root . --format json && python rebuild/verify_baseline.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL" --read-only`

Expected: 安全计数全 0；Paper 基线无变化。

- [ ] **Step 5: 更新截图索引与进度并提交**

```bash
git add scripts/check.sh docs/progress.md docs/screenshots/rebuild-wave-2-capture.json
git commit -m "docs(rebuild): accept A-share research workspaces"
```
