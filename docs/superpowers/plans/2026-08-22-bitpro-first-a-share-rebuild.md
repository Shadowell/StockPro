# BitPro-first A股整仓重建实施总控计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在隔离 worktree 中把 BitPro 固定提交的完整应用底座重建为使用 PostgreSQL 和真实 A股语义的 StockPro，并在最终切换前证明 Paper 历史、页面标准和生产回滚边界完整。

**Architecture:** 以 BitPro `00517963e90f463e608289b0277fe598bd82d9bf` 的前后端应用为页面与交互底座，先静态封锁数字资产执行，再通过唯一 `/api/*` Application Service 和 PostgreSQL Repository 接回 StockPro 业务对象。当前 StockPro `main` 与生产保持运行，重建分支只连接隔离数据库，最终使用最新生产快照演练并经确认后切换。

**Tech Stack:** React 18、TypeScript、Vite、Tailwind、ECharts、Zustand、FastAPI、Python 3.11+、PostgreSQL、psycopg、Backtrader、APScheduler、Playwright、GitHub Actions、Nginx/systemd。

**Spec:** `docs/contracts/active-bitpro-first-a-share-rebuild.md`

## Global Constraints

- 固定 BitPro 来源必须是 `00517963e90f463e608289b0277fe598bd82d9bf`，不得读取其未提交工作区。
- StockPro 设计基线必须是 `99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440` 加设计提交
  `e204e9f41a9df26a0aefd77a7a6079a86265a234` 和计划提交
  `27f53cead43557760f5ce74ffc2a598078f9fcfa`。
- BitPro 项目规则禁止子代理，因此执行本计划时只能选择 `superpowers:executing-plans` 内联执行。
- 当前 StockPro `main`、生产 release、生产数据库和 GitHub Actions workflow 在最终切换确认前不得修改。
- 新分支只连接 `stockpro_bitpro_rebase_dev`，不得连接生产数据库执行写操作。
- PostgreSQL 是唯一运行事实源；禁止 SQLite 业务回退、双写和同义事实表。
- 全系统只提供当前 `/api/*`；禁止带版本号路径、旧入口、alias Router 和长期兼容层。
- 默认且唯一可执行范围是 A股 Paper；数字资产私有 API、实盘订阅、交易所账户和币圈后台任务必须不可达。
- 现有 15 个 Paper 实例及其权益、61 个订单、47 个成交、23 个持仓、428 个权益快照和 681 个事件不得归零或消失。
- 页面不得用 mock、seed、随机数或硬编码业务值填充最终验收。
- 每个一级页面必须更新 `docs/pages/` 合同，并以最终部署的真实数据截图验收。
- 每个代码切片完成后运行相关测试、`./scripts/check.sh`、真实浏览器检查和 Paper 对账，再创建独立提交。
- 不自动推送、合并或部署；执行到对应门禁时按 StockPro 仓库规则处理，最终生产切换必须再次取得用户确认。

---

## 阶段计划

| Wave | 计划文件 | 独立交付物 | 阻断门禁 |
| --- | --- | --- | --- |
| 0 | `2026-08-22-bitpro-rebuild-00-foundation-import.md` | 隔离 worktree、基线清单、BitPro 应用导入、安全封锁 | 未启动任何服务；静态扫描无数字资产执行入口 |
| 1 | `2026-08-22-bitpro-rebuild-01-shell-api-postgres.md` | BitPro MainLayout、认证、唯一 `/api/*`、PostgreSQL Repository | 无 SQLite、无旧 API、健康与权限合同通过 |
| 2 | `2026-08-22-bitpro-rebuild-02-research-workspaces.md` | 首页、行情、股票池、因子 | 真实 A股数据状态、桌面/移动端与页面文档通过 |
| 3 | `2026-08-22-bitpro-rebuild-03-mainline.md` | 策略、回测、模拟 | 策略→回测→Paper 全链路与历史连续性通过 |
| 4 | `2026-08-22-bitpro-rebuild-04-operations.md` | 盯盘、信号、监控、复盘 | 运行证据同源、告警不下单、通知与复盘通过 |
| 5 | `2026-08-22-bitpro-rebuild-05-data-ai-futures.md` | 数据、AI研发、期货隐藏预留 | Provider/质量/导入安全、AI门控、期货不可见 |
| 6 | `2026-08-22-bitpro-rebuild-06-acceptance-cutover.md` | 全量验收、最新快照演练、切换与回滚 | 用户最终确认、Actions、SHA、健康和真实截图 |

## 总控执行顺序

### Task 1: 执行 Wave 0 并冻结导入基线

**Files:**
- Read: `docs/superpowers/plans/2026-08-22-bitpro-rebuild-00-foundation-import.md`
- Produce: 独立 worktree、导入提交、安全封锁提交、基线 JSON

**Interfaces:**
- Consumes: 当前计划分支提交 `27f53cead43557760f5ce74ffc2a598078f9fcfa`、BitPro 固定提交、只读 PostgreSQL。
- Produces: 后续 Wave 使用的 `codex/bitpro-a-share-rebase`、`RebuildBaseline` JSON、禁止执行扫描器。

- [ ] **Step 1: 逐项执行 Wave 0 计划并在每个提交后运行其门禁**

Run: `git log --oneline --decorate -5`

Expected: 至少包含独立的“导入 BitPro 应用底座”和“封锁数字资产运行时”两个提交。

- [ ] **Step 2: 确认 Wave 0 验收产物**

Run: `python rebuild/assert_safety.py --root . --format json`

Expected: JSON 中 `passed=true`、`registered_private_exchange_routes=0`、`active_sqlite_repository=0`、`active_versioned_api_routes=0`、`registered_crypto_jobs=0`；未注册的来源文件可列入 `quarantined_source_findings`，但不能从应用入口可达。

### Task 2: 执行 Wave 1 并建立唯一应用骨架

**Files:**
- Read: `docs/superpowers/plans/2026-08-22-bitpro-rebuild-01-shell-api-postgres.md`
- Produce: 可启动的 BitPro shell、认证、PostgreSQL 健康与当前 API

**Interfaces:**
- Consumes: Wave 0 安全底座与隔离数据库。
- Produces: `AppContext`, `PostgresRepository`, `/api/health`, `/api/auth/*` 和前端 `apiClient`。

- [ ] **Step 1: 逐项执行 Wave 1 的 TDD 任务**

Run: `pytest -q backend/tests/test_current_api_router.py backend/tests/test_postgres_repository_contract.py backend/tests/test_auth_contract.py`

Expected: PASS，且测试明确断言 SQLite 和带版本号 API 不可用。

- [ ] **Step 2: 验证页面骨架不被懒加载替换**

Run: `npm --prefix frontend run test:e2e -- --grep "shell remains mounted"`

Expected: PASS，侧栏 DOM 在页面切换和 Loading 期间保持同一节点。

### Task 3: 执行 Wave 2 并交付研究工作区

**Files:**
- Read: `docs/superpowers/plans/2026-08-22-bitpro-rebuild-02-research-workspaces.md`
- Produce: 首页、行情、股票池、因子及页面合同

**Interfaces:**
- Consumes: Wave 1 当前 API 与 PostgreSQL Repository。
- Produces: 市场、证券、股票池和因子 ViewModel，供策略与回测使用。

- [ ] **Step 1: 完成 Wave 2 所有页面切片**

Run: `npm --prefix frontend run test:e2e -- --grep "home|market|pool|factor"`

Expected: 桌面与 390px 合同通过，无 mock 数据和页面级横向溢出。

- [ ] **Step 2: 验证只读页面不写库、不调用 Provider**

Run: `pytest -q backend/tests/test_research_pages_readonly.py`

Expected: PASS，数据库写入和 Provider mock 调用均为 0。

### Task 4: 执行 Wave 3 并交付唯一主线

**Files:**
- Read: `docs/superpowers/plans/2026-08-22-bitpro-rebuild-03-mainline.md`
- Produce: 策略、回测、Paper 及连续性对账

**Interfaces:**
- Consumes: Wave 2 的封存数据、因子和股票池。
- Produces: 当前策略合同、回测证据、Paper ViewModel 和不可变 lineage。

- [ ] **Step 1: 完成策略与回测 TDD 任务**

Run: `pytest -q backend/tests/test_strategy_current_contract.py backend/tests/test_backtest_current_contract.py`

Expected: PASS；快速诊断不产生 Paper 晋级证据，完整回测保留门控。

- [ ] **Step 2: 完成 Paper 页面与历史对账**

Run: `python rebuild/verify_paper_continuity.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL"`

Expected: `passed=true`，15 个实例全部匹配且无权益、成交、持仓、曲线和事件归零。

### Task 5: 执行 Wave 4 并交付运行证据链

**Files:**
- Read: `docs/superpowers/plans/2026-08-22-bitpro-rebuild-04-operations.md`
- Produce: 盯盘、信号、监控、复盘

**Interfaces:**
- Consumes: Wave 3 Paper IDs、信号、订单、成交、风险和事件。
- Produces: 同源运行证据、告警确认、通知投递和交易日复盘。

- [ ] **Step 1: 完成 Wave 4 的 API 与页面合同**

Run: `pytest -q backend/tests/test_operations_evidence_chain.py && npm --prefix frontend run test:e2e -- --grep "watch|signal|monitor|review"`

Expected: PASS；规则评估 `orders_created=0`，所有对象回链同一 Paper ID。

### Task 6: 执行 Wave 5 并完成能力层

**Files:**
- Read: `docs/superpowers/plans/2026-08-22-bitpro-rebuild-05-data-ai-futures.md`
- Produce: 数据中心、AI研发、期货隐藏预留

**Interfaces:**
- Consumes: 当前 API、Provider 状态、封存快照和主线门控。
- Produces: 数据同步/质量/交换 ViewModel、AI候选、InstrumentContract。

- [ ] **Step 1: 完成数据和 AI 安全合同**

Run: `pytest -q backend/tests/test_data_ai_current_contract.py`

Expected: PASS；Provider 失败无 mock，AI 结果不能自动创建 Paper。

- [ ] **Step 2: 验证期货只预留、不暴露**

Run: `pytest -q backend/tests/test_futures_reservation.py && npm --prefix frontend run test:e2e -- --grep "futures remains hidden"`

Expected: InstrumentContract 接受 future 元数据，导航和路由中没有可见期货入口。

### Task 7: 执行 Wave 6 并完成最终验收

**Files:**
- Read: `docs/superpowers/plans/2026-08-22-bitpro-rebuild-06-acceptance-cutover.md`
- Produce: 全量测试、真实截图、最新数据库演练、切换证据

**Interfaces:**
- Consumes: Wave 0–5 全部通过的提交和最新生产快照。
- Produces: 可供用户批准的切换报告；批准后产生 `main`、Actions 和生产 SHA 证据。

- [ ] **Step 1: 执行全量本地和预览环境验收**

Run: `./scripts/check.sh && npm --prefix frontend run test:e2e:real`

Expected: 所有检查通过，页面合同、API、Paper 对账和数字资产零调用门禁均为绿色。

- [ ] **Step 2: 停止并请求最终切换确认**

Required output: 当前分支 SHA、测试汇总、Paper 对账、预览 URL、新旧截图索引、回滚 SHA 和数据库备份清单。

Expected: 在收到用户明确的最终切换确认前，不合并 `main`，不修改生产。

- [ ] **Step 3: 获批后执行 Actions 部署与生产验收**

Run: `gh run list --branch main --limit 1`，随后核对服务器 `last_deployed_sha`、systemd、Nginx、迁移和公网页面。

Expected: `main`、`origin/main`、Actions head SHA、服务器 SHA 完全一致，内外健康通过，真实生产截图来自该 SHA。
