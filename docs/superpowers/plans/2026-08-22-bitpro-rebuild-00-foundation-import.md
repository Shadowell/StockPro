# BitPro-first 重建 Wave 0：隔离导入与安全封锁实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建不影响 StockPro `main`/生产的隔离 worktree，记录 PostgreSQL/Paper 基线，机械导入 BitPro 固定应用代码，并在任何服务启动前证明数字资产执行、SQLite 和带版本号 API 均不可达。

**Architecture:** 先用只读脚本把仓库、数据库和 Paper 事实写入本地忽略目录，再从设计提交创建独立 worktree。导入脚本只同步固定 BitPro 提交中的应用目录；随后用静态安全扫描和显式配置封锁数字资产运行时，整个 Wave 不启动前后端服务。

**Tech Stack:** Git worktree、zsh、Python 3.11+、psycopg、pytest、git archive、rsync。

**Spec:** `docs/contracts/active-bitpro-first-a-share-rebuild.md`

## Global Constraints

- 必须使用 `superpowers:using-git-worktrees` 创建 worktree；BitPro 规则禁止子代理。
- 源 SHA 固定为 `2e4b90c3f83672cb9c3fc2e31b772f6c52efacb1`，StockPro 计划提交固定为
  `27f53cead43557760f5ce74ffc2a598078f9fcfa`。
- 只允许在 `/Users/jie.feng/Dev/Github/Private/StockPro-bitpro-a-share` 写入导入代码。
- 当前 StockPro 工作区中的 `.agents/`、`.claude-flow/`、`.cursor/`、`.zcode/`、`backend/.claude-flow/`、`frontend/.claude-flow/` 和 `frontend/scripts/qa_visual_pass.mjs` 不得加入提交。
- 本 Wave 禁止启动 uvicorn、Vite、scheduler、Provider、Paper recovery 或策略 worker。
- 本 Wave 禁止推送、合并、部署和生产数据库写入。

---

### Task 0: 创建隔离 worktree

**Files:**
- Runtime artifact: `/Users/jie.feng/Dev/Github/Private/StockPro-bitpro-a-share`

**Interfaces:**
- Consumes: 已提交全部设计与计划的 `codex/bitpro-a-share-rebuild-design` 最新 SHA。
- Produces: `codex/bitpro-a-share-rebase` 独立 worktree；后续 Task 全部在该目录执行。

- [x] **Step 1: 使用 using-git-worktrees skill 检查目标和分支**

Run: `test ! -e /Users/jie.feng/Dev/Github/Private/StockPro-bitpro-a-share && ! git show-ref --verify --quiet refs/heads/codex/bitpro-a-share-rebase`

Expected: exit 0，目标路径和分支都不存在。

- [x] **Step 2: 从计划分支最新提交创建 worktree**

```bash
REBUILD_PLAN_BASE_SHA=$(git rev-parse codex/bitpro-a-share-rebuild-design)
git worktree add -b codex/bitpro-a-share-rebase /Users/jie.feng/Dev/Github/Private/StockPro-bitpro-a-share "$REBUILD_PLAN_BASE_SHA"
cd /Users/jie.feng/Dev/Github/Private/StockPro-bitpro-a-share
```

Expected: `git branch --show-current` 返回 `codex/bitpro-a-share-rebase`；原 StockPro 工作区状态不变。

### Task 1: 创建可复核的 StockPro 数据连续性基线

**Files:**
- Create: `rebuild/capture_baseline.py`
- Create: `rebuild/verify_baseline.py`
- Create: `rebuild/tests/test_baseline.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `DATABASE_URL`、Git 仓库路径、`schema_migrations` 与现有业务表。
- Produces: `capture_baseline(database_url: str, repo_root: Path) -> RebuildBaseline`、`.codex-artifacts/rebuild/baseline.json`；后续 Wave 使用同一 JSON 对账。

- [x] **Step 1: 写失败测试，锁定基线 JSON 字段与只读 SQL**

```python
def test_capture_baseline_contains_required_continuity_fields(fake_repository, tmp_path):
    baseline = capture_baseline("postgresql://example", tmp_path, repository=fake_repository)
    assert baseline["schema_version"] == "stockpro-rebuild-baseline"
    assert baseline["paper"]["instance_count"] == 15
    assert baseline["paper"]["order_count"] == 61
    assert baseline["paper"]["trade_count"] == 47
    assert baseline["paper"]["position_count"] == 23
    assert baseline["paper"]["equity_sample_count"] == 428
    assert baseline["paper"]["event_count"] == 681
    assert baseline["paper"]["instances"][0]["instance_id"]
    assert fake_repository.executed_writes == []
```

- [x] **Step 2: 运行测试并确认失败**

Run: `backend/venv/bin/python -m pytest rebuild/tests/test_baseline.py -q`

Expected: FAIL，提示 `capture_baseline` 模块不存在。

- [x] **Step 3: 实现只读基线采集器**

```python
@dataclass(frozen=True)
class RebuildBaseline:
    schema_version: str
    captured_at: str
    repository: dict[str, str]
    counts: dict[str, int]
    paper: dict[str, object]
    manifest_hash: str

def capture_baseline(database_url: str, repo_root: Path, repository: BaselineRepository | None = None) -> dict[str, object]:
    # 只执行 SELECT；实例明细固定包含 ID、策略版本、资金、计数、曲线首尾和运行起点。
    source = repository or PostgresBaselineRepository(database_url)
    payload = read_continuity_manifest(source, repo_root)
    payload["manifest_hash"] = canonical_hash(payload)
    return payload
```

采集 SQL 必须包含：`schema_migrations`、`strategy_versions`、`backtest_runs`、
`paper_instances`、`portfolios`、`orders`、`trades`、`positions`、
`paper_equity_snapshots`、`paper_instance_events` 和 `daily_reviews`。

- [x] **Step 4: 将生成目录加入忽略清单**

```gitignore
.codex-artifacts/rebuild/
```

- [x] **Step 5: 运行测试并采集当前真实基线**

Run: `backend/venv/bin/python -m pytest rebuild/tests/test_baseline.py -q && backend/venv/bin/python rebuild/capture_baseline.py --output .codex-artifacts/rebuild/baseline.json`

Expected: PASS；JSON 顶层包含 `repository`、`counts`、`paper`、`manifest_hash`，数据库计数与设计合同一致。

- [x] **Step 6: 提交基线工具**

```bash
git add .gitignore rebuild/capture_baseline.py rebuild/verify_baseline.py rebuild/tests/test_baseline.py
git commit -m "test(rebuild): capture immutable continuity baseline"
```

### Task 2: 验证固定来源并证明不读取脏工作区

**Files:**
- Create: `rebuild/verify_source.py`
- Create: `rebuild/tests/test_source_pin.py`

**Interfaces:**
- Consumes: BitPro repo、固定 SHA、StockPro 设计提交。
- Produces: `verify_source(repo: Path, expected_sha: str) -> SourceManifest`；确认当前目录已经是目标 worktree。

- [x] **Step 1: 写固定 SHA 和脏工作区排除测试**

```python
def test_source_manifest_uses_committed_tree_only(bitpro_repo):
    result = verify_source(bitpro_repo, "2e4b90c3f83672cb9c3fc2e31b772f6c52efacb1")
    assert result["head"] == "2e4b90c3f83672cb9c3fc2e31b772f6c52efacb1"
    assert result["archive_source"] == "git-object-database"
    assert "AGENTS.md" not in result["application_roots"]
    assert ".env" not in result["application_roots"]
```

- [x] **Step 2: 运行失败测试**

Run: `backend/venv/bin/python -m pytest rebuild/tests/test_source_pin.py -q`

Expected: FAIL，提示 `verify_bitpro_source` 不存在。

- [x] **Step 3: 实现来源验证器**

```python
APPLICATION_ROOTS = ("frontend", "backend", "packages", "scripts", "tests")

def verify_source(repo: Path, expected_sha: str) -> dict[str, object]:
    resolved = git(repo, "rev-parse", expected_sha).strip()
    if resolved != expected_sha:
        raise RuntimeError("BitPro source SHA mismatch")
    return {"head": resolved, "archive_source": "git-object-database", "application_roots": list(APPLICATION_ROOTS)}
```

- [x] **Step 4: 验证当前执行目录和分支**

```bash
test "$(pwd)" = "/Users/jie.feng/Dev/Github/Private/StockPro-bitpro-a-share"
test "$(git branch --show-current)" = "codex/bitpro-a-share-rebase"
```

Expected: 两个检查均 exit 0。

- [x] **Step 5: 运行来源测试并提交**

```bash
backend/venv/bin/python -m pytest rebuild/tests/test_source_pin.py -q
git add rebuild/verify_source.py rebuild/tests/test_source_pin.py
git commit -m "build(rebuild): pin BitPro source snapshot"
```

### Task 3: 机械导入 BitPro 应用目录

**Files:**
- Create: `rebuild/import_bitpro_baseline.sh`
- Create: `rebuild/tests/test_import_contract.py`
- Replace mechanically: `frontend/`, `backend/`, `packages/`, `scripts/`, `tests/`
- Create mechanically: `docs/reference/bitpro-baseline/pages/`
- Create mechanically: `docs/reference/bitpro-baseline/screenshots/`
- Create mechanically: `docs/reference/bitpro-baseline/product-manual/`
- Create: `docs/reference/bitpro-baseline/source.json`
- Preserve: `AGENTS.md`, `LICENSE`, `.github/`, `deploy/`, `docs/contracts/`, `docs/spec.md`, `docs/progress.md`

**Interfaces:**
- Consumes: `BITPRO_SOURCE_REPO`, `BITPRO_SOURCE_SHA`, validated target worktree.
- Produces: application directories whose tracked content matches the fixed BitPro archive, plus StockPro governance files.

- [x] **Step 1: 写导入 allowlist/denylist 失败测试**

```python
def test_import_contract_keeps_governance_and_excludes_runtime_data(import_manifest):
    assert import_manifest["copied_roots"] == ["backend", "frontend", "packages", "scripts", "tests"]
    assert ".github" in import_manifest["preserved_roots"]
    assert "deploy" in import_manifest["preserved_roots"]
    assert "data" in import_manifest["excluded_roots"]
    assert ".env" in import_manifest["excluded_patterns"]
    assert import_manifest["reference_paths"] == ["docs/pages", "docs/screenshots", "docs/product_manual"]
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest rebuild/tests/test_import_contract.py -q`

Expected: FAIL，导入脚本/manifest 不存在。

- [x] **Step 3: 实现机械导入脚本**

脚本必须先验证 `pwd` 精确等于目标 worktree，再创建 `mktemp -d`，使用：

```bash
git -C "$BITPRO_SOURCE_REPO" archive "$BITPRO_SOURCE_SHA" | tar -x -C "$IMPORT_TEMP_DIR"
```

然后只对五个显式根执行：

```bash
rsync -a --delete --exclude=venv/ --exclude=__pycache__/ "$IMPORT_TEMP_DIR/backend/" "$TARGET_ROOT/backend/"
rsync -a --delete --exclude=node_modules/ --exclude=dist/ "$IMPORT_TEMP_DIR/frontend/" "$TARGET_ROOT/frontend/"
rsync -a --delete "$IMPORT_TEMP_DIR/packages/" "$TARGET_ROOT/packages/"
rsync -a --delete "$IMPORT_TEMP_DIR/scripts/" "$TARGET_ROOT/scripts/"
rsync -a --delete "$IMPORT_TEMP_DIR/tests/" "$TARGET_ROOT/tests/"
```

BitPro 的页面设计与截图合同不覆盖 StockPro 当前文档，而是固定复制到：

```bash
rsync -a --delete "$IMPORT_TEMP_DIR/docs/pages/" "$TARGET_ROOT/docs/reference/bitpro-baseline/pages/"
rsync -a --delete "$IMPORT_TEMP_DIR/docs/screenshots/" "$TARGET_ROOT/docs/reference/bitpro-baseline/screenshots/"
rsync -a --delete "$IMPORT_TEMP_DIR/docs/product_manual/" "$TARGET_ROOT/docs/reference/bitpro-baseline/product-manual/"
```

`source.json` 记录 BitPro repo、固定 SHA、导入时间和三类 reference path。

脚本不得同步 `.github`、`deploy`、`data`、根文档、环境文件或 BitPro 工作区文件。

- [x] **Step 4: 运行导入测试和 dry-run manifest**

Run: `python -m pytest rebuild/tests/test_import_contract.py -q && ./rebuild/import_bitpro_baseline.sh --dry-run --manifest .codex-artifacts/rebuild/import.json`

Expected: PASS；manifest 的 source SHA 精确匹配，写入范围仅为五个应用根。

- [x] **Step 5: 执行机械导入并检查范围**

Run: `./rebuild/import_bitpro_baseline.sh --apply --manifest .codex-artifacts/rebuild/import.json && git status --short`

Expected: 只有五个应用根发生大规模变更并新增 `docs/reference/bitpro-baseline`；`AGENTS.md`、`LICENSE`、`.github/`、`deploy/` 和设计合同未变化。

- [x] **Step 6: 提交纯导入快照**

```bash
git add backend frontend packages scripts tests docs/reference/bitpro-baseline
git commit -m "chore(rebuild): import pinned BitPro application baseline"
```

此提交不运行服务；允许应用暂时不可启动。

### Task 4: 建立数字资产与 SQLite 静态封锁器

**Files:**
- Create: `rebuild/assert_safety.py`
- Create: `rebuild/tests/test_safety.py`
- Create: `backend/app/core/rebuild_safety.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/MainLayout.tsx`

**Interfaces:**
- Consumes: BitPro 导入后的路由、配置和模块树。
- Produces: `RebuildSafetyReport`、`assert_safe_to_start(root: Path) -> None`；后续启动脚本必须调用。

- [x] **Step 1: 写 fail-closed 测试**

```python
def test_safety_report_blocks_registered_private_exchange_and_sqlite_runtime(tmp_path):
    (tmp_path / "backend/app/main.py").parent.mkdir(parents=True)
    (tmp_path / "backend/app/main.py").write_text("client.get_account(); sqlite3.connect('crypto.db')")
    report = scan_rebuild_safety(tmp_path)
    assert report.passed is False
    assert report.registered_private_exchange_routes == 1
    assert report.active_sqlite_repository == 1

def test_safety_report_blocks_active_versioned_api_paths(tmp_path):
    (tmp_path / "frontend/src/api/client.ts").parent.mkdir(parents=True)
    (tmp_path / "frontend/src/api/client.ts").write_text("axios.get('/api/v2/market')")
    assert scan_rebuild_safety(tmp_path).active_versioned_api_routes == 1
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest rebuild/tests/test_safety.py -q`

Expected: FAIL，安全扫描器不存在。

- [x] **Step 3: 实现扫描报告**

```python
@dataclass(frozen=True)
class RebuildSafetyReport:
    passed: bool
    registered_private_exchange_routes: int
    active_sqlite_repository: int
    active_versioned_api_routes: int
    registered_live_routes: int
    registered_crypto_jobs: int
    quarantined_source_findings: int
    findings: tuple[dict[str, object], ...]
```

扫描只覆盖运行源码和配置，排除测试、文档和固定来源说明。禁止模式至少包括：
私有账户/下单客户端、`sqlite3.connect`、BitPro local DB import、带版本号 API、
`/live-real` 注册、资金费率/清算/链上/跨所 scheduler 注册。

- [x] **Step 4: 在启动前调用安全门禁**

```python
def create_app() -> FastAPI:
    assert_safe_to_start(Path(__file__).resolve().parents[2])
    app = FastAPI(title="StockPro")
    register_current_api(app)
    return app
```

配置默认值必须为：

```python
ENABLE_PRIVATE_EXCHANGE_API = False
ENABLE_CRYPTO_BACKGROUND_JOBS = False
ENABLE_LIVE_TRADING = False
DATABASE_BACKEND = "postgresql"
```

- [x] **Step 5: 移除不可注册路由和导航**

`frontend/src/App.tsx` 不得注册数字资产实盘、链上、ARC 和套利页面；
`MainLayout` 不得显示这些入口。保留 `/paper`、`/watch`、`/signals`、`/monitor`、`/review` 的占位路由，内容明确为 A股适配未完成。

- [x] **Step 6: 运行安全测试与全树扫描**

Run: `python -m pytest rebuild/tests/test_safety.py -q && python rebuild/assert_safety.py --root . --format json`

Expected: 测试 PASS；五类可达阻断计数全部为 0。BitPro 未注册来源文件可计入 `quarantined_source_findings`，但 `passed` 仍须基于应用可达面为 true。

- [x] **Step 7: 提交安全封锁**

```bash
git add rebuild/assert_safety.py rebuild/tests/test_safety.py backend/app/core/rebuild_safety.py backend/app/core/config.py backend/app/main.py frontend/src/App.tsx frontend/src/components/MainLayout.tsx
git commit -m "feat(rebuild): fail closed before A-share adaptation"
```

### Task 5: Wave 0 完成审计

**Files:**
- Modify: `docs/project/progress.md`（若 BitPro 导入后采用该路径）或 `docs/progress.md`（保留 StockPro 路径）
- Read: `.codex-artifacts/rebuild/baseline.json`
- Read: `.codex-artifacts/rebuild/import.json`

**Interfaces:**
- Consumes: Wave 0 的四个提交与两个 manifest。
- Produces: Wave 1 可依赖的固定导入/安全证据。

- [x] **Step 1: 检查提交和未提交边界**

Run: `git log --oneline --decorate -6 && git status --short`

Expected: 业务变更只在目标 worktree；无环境文件、数据库、日志和当前 StockPro 工具目录进入提交。

- [x] **Step 2: 复核原 StockPro 工作区和生产分支未变化**

Run: `git -C /Users/jie.feng/Dev/Github/Private/StockPro status --short --branch && git -C /Users/jie.feng/Dev/Github/Private/StockPro rev-parse main origin/main`

Expected: 原工作区仍在设计分支或 `main` 的已知状态；`main` 与 `origin/main` 未因 Wave 0 更新。

- [x] **Step 3: 更新进度文档并运行文档检查**

记录固定 SHA、导入根、两个 manifest hash、安全扫描结果和“服务从未启动”。

Run: `git diff --check`

Expected: 无空白错误。

- [x] **Step 4: 提交 Wave 0 验收记录**

```bash
git add docs/progress.md docs/contracts/active-bitpro-first-a-share-rebuild.md
git commit -m "docs(rebuild): record foundation import acceptance"
```

Wave 0 完成后停止，进入 Wave 1 前先确认安全扫描仍为全 0。
