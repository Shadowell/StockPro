# BitPro-first 重建 Wave 6：最终验收、切换与回滚实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 证明新 StockPro 满足 BitPro 页面标准、A股领域门禁、唯一当前 API、PostgreSQL/Paper 连续性和数字资产零执行，在用户最终确认后通过 `main` 与 GitHub Actions 安全部署并完成生产验收。

**Architecture:** 使用机器可读 completion audit 汇总代码、API、数据库、页面、权限、性能、截图和安全证据。开发/隔离库与生产库分别建立自己的切换前 manifest；部署后只与同环境基线比较。应用 release 可回滚，数据库迁移只 additive，不执行数据回滚。

**Tech Stack:** pytest、Playwright、TypeScript、Python、PostgreSQL backup/restore、GitHub CLI、GitHub Actions、systemd、Nginx、curl。

**Spec:** `docs/contracts/active-bitpro-first-a-share-rebuild.md`

## Global Constraints

- Wave 0–5 全部提交和门禁必须通过。
- 子代理禁止；最终审计由当前会话本地执行。
- 最终截图必须来自真实部署或隔离真实数据环境，禁止 mock、request interception 和 DOM 注入。
- 本地 15 个 Paper 基线只与其来源数据库比较；生产使用单独的生产 pre-cutover manifest，禁止跨环境复制或补造数据。
- 最终确认前禁止合并 `main`、修改生产数据库、重启生产或部署。
- 最终确认后只允许 `main` 触发 GitHub Actions 部署，不允许 SSH/rsync 手工修补应用。
- 部署失败回滚应用 release；数据库只做 additive migration，不回滚或清空。

---

### Task 1: 实现机器可读完成审计器

**Files:**
- Create: `rebuild/audit_completion.py`
- Create: `rebuild/tests/test_completion_audit.py`
- Create: `rebuild/contracts/rebuild-requirements.json`
- Modify: `scripts/check.sh`

**Interfaces:**
- Consumes: source tree、OpenAPI、test results、baseline/continuity manifests、screenshot index。
- Produces: `CompletionAuditResult(passed, requirements, blockers, evidence)`、`.codex-artifacts/rebuild/completion-audit.json`。

- [ ] **Step 1: 写未满足需求不能通过的失败测试**

```python
def test_completion_audit_fails_when_any_requirement_lacks_evidence(tmp_path):
    requirements = [{"id": "API-001", "required": True}, {"id": "PAPER-001", "required": True}]
    evidence = {"API-001": {"status": "passed"}}
    result = audit(requirements, evidence)
    assert result.passed is False
    assert result.blockers == ["PAPER-001"]
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest rebuild/tests/test_completion_audit.py -q`

Expected: FAIL，审计器不存在。

- [ ] **Step 3: 定义逐条需求清单**

`rebuild-requirements.json` 至少包含：

```json
[
  {"id":"BASE-001","required":true,"description":"BitPro fixed source provenance"},
  {"id":"API-001","required":true,"description":"Only /api current contract"},
  {"id":"DB-001","required":true,"description":"PostgreSQL sole runtime truth"},
  {"id":"PAPER-001","required":true,"description":"Per-environment Paper continuity"},
  {"id":"SAFE-001","required":true,"description":"Zero private digital-asset execution"},
  {"id":"UI-001","required":true,"description":"BitPro page contracts desktop and mobile"},
  {"id":"ASHARE-001","required":true,"description":"A-share execution semantics"},
  {"id":"FUTURE-001","required":true,"description":"Futures reserved and hidden"},
  {"id":"DEPLOY-001","required":true,"description":"Actions SHA and production health"}
]
```

审计结果类型固定为：

```python
@dataclass(frozen=True)
class CompletionAuditResult:
    passed: bool
    requirements: tuple[dict[str, object], ...]
    blockers: tuple[str, ...]
    evidence: Mapping[str, Mapping[str, object]]
```

- [ ] **Step 4: 实现审计器**

审计器不把“文件存在”当作通过；每项必须引用测试结果、运行输出、manifest hash、截图索引或生产状态。缺失/unknown 均阻断。

- [ ] **Step 5: 集成到 check.sh 的非生产部分**

本地检查执行审计器的 pre-deploy 模式，`DEPLOY-001` 标记 `pending_final_confirmation` 而不是伪装通过；退出码在其他必需项失败时非 0。

- [ ] **Step 6: 运行测试并提交**

```bash
python -m pytest rebuild/tests/test_completion_audit.py -q
git add rebuild/audit_completion.py rebuild/tests/test_completion_audit.py rebuild/contracts/rebuild-requirements.json scripts/check.sh
git commit -m "test(rebuild): require evidence-backed completion audit"
```

### Task 2: 完成 API、数据库和安全审计

**Files:**
- Create: `backend/tests/test_final_api_contract.py`
- Create: `backend/tests/test_final_database_contract.py`
- Create: `backend/tests/test_final_ashare_contract.py`
- Read: `.codex-artifacts/rebuild/baseline.json`

**Interfaces:**
- Produces: API/DB/A股/safety evidence JSON，供 completion audit 使用。

- [ ] **Step 1: 写唯一 API 全树测试**

```python
def test_openapi_contains_only_current_api(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths
    assert all(path.startswith("/api/") for path in paths)
    assert all("/api/v" not in path for path in paths)
```

- [ ] **Step 2: 写 PostgreSQL 唯一事实测试**

```python
def test_runtime_tree_has_no_sqlite_business_repository():
    runtime = runtime_source_text()
    assert "sqlite3.connect" not in runtime
    assert "local_db" not in runtime
    assert health().database == "postgresql"
```

- [ ] **Step 3: 写 A股语义矩阵测试**

覆盖交易日/午休、T+1、整手、清仓零股、涨跌停、停牌、ST、费用、无未来数据、
次日最早成交和容量；每项包含一个接受和一个拒绝样例。

- [ ] **Step 4: 运行完整后端与静态安全审计**

Run: `python -m pytest backend/tests -q && python rebuild/assert_safety.py --root . --format json`

Expected: 全部 PASS；安全阻断计数全 0。

- [ ] **Step 5: 运行隔离库 continuity**

Run: `python rebuild/verify_paper_continuity.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL" --output .codex-artifacts/rebuild/local-continuity.json`

Expected: 15/61/47/23/428/681 及每实例字段 PASS。

- [ ] **Step 6: 将证据喂给 completion audit 并提交测试**

```bash
python rebuild/audit_completion.py --mode pre-deploy --output .codex-artifacts/rebuild/completion-audit.json
git add backend/tests/test_final_api_contract.py backend/tests/test_final_database_contract.py backend/tests/test_final_ashare_contract.py
git commit -m "test(rebuild): verify API database and A-share contracts"
```

### Task 3: 完成全页面、权限和响应式矩阵

**Files:**
- Create: `frontend/tests/e2e/rebuild-final-route-matrix.spec.ts`
- Create: `frontend/tests/e2e/rebuild-final-state-matrix.spec.ts`
- Create: `frontend/tests/e2e/rebuild-final-permissions.spec.ts`
- Modify: `frontend/playwright.config.ts`

**Interfaces:**
- Consumes: 所有启用页面和当前 API。
- Produces: 1440px/390px、admin/guest、六种状态的 Playwright evidence。

- [ ] **Step 1: 写一级页面路由矩阵**

```typescript
const routes = ['/', '/market', '/pools', '/factors', '/strategy', '/backtest', '/paper', '/watch', '/signals', '/monitor', '/review', '/data', '/ai-lab']
for (const route of routes) {
  test(`${route} satisfies operator shell`, async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto(route)
    await expect(page.getByTestId('main-layout')).toBeVisible()
    await expect(page.locator('[data-operator-page]')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
  })
}
```

- [ ] **Step 2: 写状态矩阵**

每个 Owner 页面至少有独立用例覆盖 Loading、Empty、Partial、Stale、Error、Permission；
Mock 套件可拦截请求验证表现，真实套件不得拦截。

- [ ] **Step 3: 写访客权限矩阵**

访客可查看全部已启用页面；除配额内回测外，所有 POST/PUT/PATCH/DELETE 在 DOM 和 Axios 层拒绝。

- [ ] **Step 4: 运行 Mock 桌面/移动端矩阵**

Run: `npm --prefix frontend run test:e2e:mock`

Expected: 所有路由和状态用例 PASS，console error 为 0。

- [ ] **Step 5: 运行真实隔离数据库矩阵**

Run: `MOCK_API=false E2E_REAL_BACKEND=1 npm --prefix frontend run test:e2e:real`

Expected: 无 request interception；真实空/陈旧/可用状态与 API 一致。

- [ ] **Step 6: 提交**

```bash
git add frontend/tests/e2e/rebuild-final-route-matrix.spec.ts frontend/tests/e2e/rebuild-final-state-matrix.spec.ts frontend/tests/e2e/rebuild-final-permissions.spec.ts frontend/playwright.config.ts
git commit -m "test(ui): verify complete BitPro A-share page matrix"
```

### Task 4: 完成性能、错误边界和真实截图合同

**Files:**
- Create: `rebuild/capture_production_screenshots.py`
- Create: `rebuild/tests/test_screenshot_manifest.py`
- Create: `docs/screenshots/rebuild/capture-index.json`
- Modify: `docs/pages/*.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: 隔离真实数据环境、BitPro 28张手册/12张生产截图基线。
- Produces: 13个启用页面的桌面和移动端真实截图、性能结果和页面合同链接。

- [ ] **Step 1: 写截图 manifest 失败测试**

```python
def test_screenshot_manifest_requires_every_route_and_real_mode(manifest):
    assert set(manifest["routes"]) == set(REQUIRED_ROUTES)
    assert all(item["mock_api"] is False for item in manifest["captures"])
    assert all(item["deployed_sha"] for item in manifest["captures"])
    assert {item["viewport"] for item in manifest["captures"]} == {"1440x900", "390x844"}
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest rebuild/tests/test_screenshot_manifest.py -q`

Expected: FAIL，最终截图 manifest 尚不存在。

- [ ] **Step 3: 实现真实截图采集器**

采集器使用正常登录和页面导航；禁止 `page.route`、DOM 注入、临时 seed；每张图记录 URL、viewport、capture time、source_updated_at 和当前 SHA。

- [ ] **Step 4: 运行页面性能与错误边界检查**

Run: `python -m pytest tests/test_page_api_performance_static.py tests/test_page_navigation_performance_static.py tests/test_page_error_boundary_static.py -q && npm --prefix frontend run build`

Expected: PASS；bundle预算不弱于旧 StockPro。

- [ ] **Step 5: 在隔离环境采集截图**

Run: `python rebuild/capture_production_screenshots.py --base-url http://127.0.0.1:4444 --sha "$(git rev-parse HEAD)" --output docs/screenshots/rebuild`

Expected: capture-index 覆盖全部路由与两个 viewport，mock_api=false。

- [ ] **Step 6: 更新页面文档和 README**

每个页面文档的截图合同指向新截图；README 使用真实截图并声明 Paper 为模拟数据、无真实交易。

- [ ] **Step 7: 运行 manifest 测试并提交**

```bash
python -m pytest rebuild/tests/test_screenshot_manifest.py -q
git add rebuild/capture_production_screenshots.py rebuild/tests/test_screenshot_manifest.py docs/screenshots/rebuild docs/pages README.md
git commit -m "docs(ui): capture real BitPro A-share page evidence"
```

### Task 5: 使用最新数据库快照完成恢复与双应用演练

**Files:**
- Create: `rebuild/rehearse_database_restore.py`
- Create: `rebuild/tests/test_restore_rehearsal.py`
- Create runtime artifacts: `.codex-artifacts/rebuild/latest-source-manifest.json`, `latest-rebuild-manifest.json`, `old-app-smoke.json`

**Interfaces:**
- Consumes: 最新源数据库只读备份、新系统迁移、旧 StockPro checkout。
- Produces: 独立恢复数据库、迁移前后 manifest、旧应用兼容证据。

- [ ] **Step 1: 写跨环境 manifest 隔离测试**

```python
def test_manifests_are_compared_only_with_same_environment():
    with pytest.raises(EnvironmentMismatch):
        compare_manifest(local_manifest(environment="dev"), production_manifest(environment="production"))
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest rebuild/tests/test_restore_rehearsal.py -q`

Expected: FAIL，恢复演练工具不存在。

- [ ] **Step 3: 实现最新快照演练**

工具执行：只读 capture source manifest → 现有备份服务生成备份 → 恢复到显式临时数据库 → 应用全部 additive migrations → capture rebuild manifest → 同环境比较。

禁止使用生产数据库名、`DROP DATABASE` 未验证变量、宽泛 glob 或默认连接；临时数据库名称必须以 `stockpro_rebuild_rehearsal_` 开头并显式校验。

- [ ] **Step 4: 启动新应用只读 smoke**

在标准本地端口启动新前后端，禁用 scheduler/provider/recovery/worker；运行 route matrix 和 continuity。

- [ ] **Step 5: 启动旧 StockPro 只读 smoke**

从 `99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440` 创建临时只读 checkout，指向同一恢复数据库，禁用全部写服务；验证健康、策略列表、回测列表和 Paper 列表可读。

- [ ] **Step 6: 销毁显式临时数据库并保留 manifest**

只删除已验证前缀的 rehearsal 数据库；备份、manifest 和日志保留在 `.codex-artifacts/rebuild/`。

- [ ] **Step 7: 运行测试并提交工具**

```bash
python -m pytest rebuild/tests/test_restore_rehearsal.py -q
git add rebuild/rehearse_database_restore.py rebuild/tests/test_restore_rehearsal.py
git commit -m "test(storage): rehearse additive rebuild migrations"
```

### Task 6: 生成切换前验收报告并请求最终确认

**Files:**
- Modify: `docs/contracts/active-bitpro-first-a-share-rebuild.md`
- Modify: `docs/progress.md`
- Create: `docs/qa/bitpro-first-rebuild-cutover-readiness.md`

**Interfaces:**
- Consumes: completion audit、测试汇总、截图索引、最新恢复演练、Paper continuity、回滚 SHA。
- Produces: 用户最终切换确认所需的完整证据。

- [ ] **Step 1: 运行 pre-deploy completion audit**

Run: `python rebuild/audit_completion.py --mode pre-deploy --output .codex-artifacts/rebuild/completion-audit.json`

Expected: 除 `DEPLOY-001=pending_final_confirmation` 外所有 required 项 passed；若有其他 blocker，停止并修复。

- [ ] **Step 2: 写切换就绪报告**

报告必须列出：分支 SHA、BitPro 来源 SHA、StockPro 基线、提交序列、全测试数量、
页面矩阵、截图索引、开发 continuity、最新恢复演练、生产 pre-cutover 采集命令、
旧应用兼容 smoke、回滚 SHA、已知限制和期货隐藏状态。

- [ ] **Step 3: 运行文档检查并提交**

```bash
git diff --check
git add docs/contracts/active-bitpro-first-a-share-rebuild.md docs/progress.md docs/qa/bitpro-first-rebuild-cutover-readiness.md
git commit -m "docs(rebuild): request final production cutover"
```

- [ ] **Step 4: 停止并请求用户最终切换确认**

明确询问是否允许：推送分支、创建 PR、合并 `main`、由 Actions 部署并运行生产 additive migrations。

Expected: 未收到明确确认时保持分支和预览状态，不执行任何生产动作。

### Task 7: 获批后通过 PR 合并和 Actions 部署

**Files:**
- Modify only if required by final check: `.github/workflows/deploy.yml`
- Runtime evidence: GitHub PR、Actions run、服务器 SHA、生产 manifests

**Interfaces:**
- Consumes: 用户最终确认和无 blocker 的 pre-deploy audit。
- Produces: `main` merge SHA、部署 run、生产应用和 post-cutover manifest。

- [ ] **Step 1: 采集生产 pre-cutover manifest**

通过生产后端只读命令/SSH 读取迁移、策略、回测、Paper、账本、信号和复盘，写入本地 `.codex-artifacts/rebuild/production-pre-cutover.json`；不得把本地15实例基线用于生产比较。

- [ ] **Step 2: 推送分支并创建 PR**

```bash
git push -u origin codex/bitpro-a-share-rebase
gh pr create --base main --head codex/bitpro-a-share-rebase --title "feat: rebuild StockPro on BitPro A-share foundation" --body-file docs/qa/bitpro-first-rebuild-cutover-readiness.md
```

- [ ] **Step 3: 等待必需检查与可合并状态**

Run: `gh pr checks --watch`

Expected: 全部 required checks success；PR mergeable。

- [ ] **Step 4: 合并 PR 并同步本地 main**

```bash
gh pr merge --merge --delete-branch
git -C /Users/jie.feng/Dev/Github/Private/StockPro fetch origin
git -C /Users/jie.feng/Dev/Github/Private/StockPro switch main
git -C /Users/jie.feng/Dev/Github/Private/StockPro pull --ff-only origin main
```

- [ ] **Step 5: 等待 main 部署 Actions**

Run: `gh run list --branch main --limit 1`，确认 head SHA 等于 merge SHA，然后 `gh run watch <run-id> --exit-status`。

Expected: success；部署脚本记录相同 SHA。

- [ ] **Step 6: 采集 production post-cutover manifest**

使用与 pre-cutover 完全相同的只读查询生成 post manifest；比较同环境数据。Additive instrument migration可增加迁移/定义表，不得减少或改写已有业务记录。

- [ ] **Step 7: 验证服务和公网页面**

核对 `stockpro-backend`、Nginx、内外 `/api/health`、storage migrations、首页、行情、策略、回测、模拟、信号、数据和 AI研发；生产真实浏览器无 request interception。

- [ ] **Step 8: 运行 post-deploy completion audit**

Run: `python rebuild/audit_completion.py --mode post-deploy --production-manifest .codex-artifacts/rebuild/production-post-cutover.json --output .codex-artifacts/rebuild/completion-audit-final.json`

Expected: 所有 required 项 including `DEPLOY-001` passed。

### Task 8: 失败回滚或成功关闭合同

**Files:**
- Modify: `docs/contracts/active-bitpro-first-a-share-rebuild.md`
- Modify: `docs/progress.md`
- Modify: `docs/qa/bitpro-first-rebuild-cutover-readiness.md`

**Interfaces:**
- Consumes: Actions/生产验收结果。
- Produces: 回滚证据或完成合同。

- [ ] **Step 1A: 如果部署/健康/manifest 失败，停止并回滚应用 release**

使用现有部署系统的上一 release/SHA 回滚入口；不执行数据库 down migration、不清空新增表。

Expected: 旧应用健康恢复；生产数据与 pre-cutover manifest 一致；合同保持进行中并记录 blocker。

- [ ] **Step 1B: 如果全部通过，更新合同为完成**

记录 merge SHA、Actions run、部署 SHA、迁移数、服务状态、production manifest hash、截图索引和 final audit hash。

- [ ] **Step 2: 运行文档检查并提交最终记录**

```bash
git diff --check
git add docs/contracts/active-bitpro-first-a-share-rebuild.md docs/progress.md docs/qa/bitpro-first-rebuild-cutover-readiness.md
git commit -m "docs(rebuild): close BitPro-first A-share migration"
```

- [ ] **Step 3: 推送最终文档并验证记录 SHA**

按同一 PR/main/Actions 路径交付最终文档，核对服务器最终 SHA 后才能向用户报告完成。
