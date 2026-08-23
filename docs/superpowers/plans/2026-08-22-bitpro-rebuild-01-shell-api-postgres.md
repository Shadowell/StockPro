# BitPro-first 重建 Wave 1：Shell、当前 API 与 PostgreSQL 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让导入后的 BitPro 应用在无数字资产运行时、无 SQLite、无旧 API 的条件下启动，提供稳定 MainLayout、PostgreSQL 健康、管理员/访客认证和全部工作区的诚实未适配状态。

**Architecture:** 使用 `AppContext` 统一注入 PostgreSQL Repository 和服务，FastAPI 只注册 `/api/*` 当前路由。前端保留 BitPro AuthProvider、MainLayout 和导航节奏，但未完成领域适配的路由统一指向 `UnavailableWorkspace`，防止导入页面调用币圈接口。

**Tech Stack:** FastAPI、Pydantic Settings、psycopg/psycopg2、PostgreSQL、React Router、Axios、React、TypeScript、Vite、Playwright。

**Spec:** `docs/contracts/active-bitpro-first-a-share-rebuild.md`

## Global Constraints

- 执行前 Wave 0 安全扫描必须全 0。
- 只连接 `stockpro_bitpro_rebase_dev`；配置缺失时启动失败，不允许 SQLite fallback。
- 只注册 `/api/*`；源树、前端和测试不得出现运行时带版本号 API 路径。
- `/live-real`、链上、ARC、套利、数字资产账户和私有交易路由不得注册。
- 未适配页面必须显示明确状态，不得调用 Provider、数据库写操作或币圈 API。
- 子代理禁止；使用 `superpowers:executing-plans` 内联执行。

---

### Task 1: 收敛依赖与运行配置

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/core/config.py`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/playwright.config.ts`
- Test: `rebuild/tests/test_runtime_dependencies.py`

**Interfaces:**
- Consumes: Wave 0 导入的 BitPro manifests。
- Produces: `Settings.DATABASE_URL: str`、`Settings.RUNTIME_MODE == "ashare_paper"`、无数字资产私有 SDK 的安装集合。

- [x] **Step 1: 写依赖与配置失败测试**

```python
def test_runtime_dependencies_exclude_private_exchange_and_sqlite():
    requirements = Path("backend/requirements.txt").read_text().lower()
    assert "ccxt" not in requirements
    assert "aiosqlite" not in requirements
    assert "psycopg" in requirements

def test_settings_require_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///crypto.db")
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings()
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest rebuild/tests/test_runtime_dependencies.py -q`

Expected: FAIL，导入的 BitPro 依赖仍包含数字资产/SQLite 运行项或配置未拒绝 SQLite。

- [x] **Step 3: 实现当前运行配置**

```python
class Settings(BaseSettings):
    DATABASE_URL: str
    RUNTIME_MODE: Literal["ashare_paper"] = "ashare_paper"
    ENABLE_PROVIDER_FETCH: bool = False
    ENABLE_SCHEDULER: bool = False
    ENABLE_PAPER_RECOVERY: bool = False
    ENABLE_LIVE_TRADING: bool = False

    @field_validator("DATABASE_URL")
    @classmethod
    def postgres_only(cls, value: str) -> str:
        if not value.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("StockPro rebuild requires PostgreSQL")
        return value
```

`backend/requirements.txt` 保留 FastAPI、uvicorn、pydantic、psycopg、pandas、
TuShare、AKShare、Backtrader、APScheduler、httpx 和测试依赖；移除只服务数字资产私有执行的 SDK。

- [x] **Step 4: 固定前端 BitPro 基线并补 StockPro 测试依赖**

保留 BitPro React/Router/状态管理版本和 `packages/bitpro-ui`，补入 Playwright 与 StockPro bundle-budget 脚本所需开发依赖。运行：

`frontend/package.json` 同时定义：

```json
{
  "scripts": {
    "check": "tsc --noEmit",
    "test:e2e": "playwright test",
    "test:e2e:mock": "cross-env MOCK_API=true playwright test",
    "test:e2e:real": "cross-env MOCK_API=false E2E_REAL_BACKEND=1 playwright test",
    "check:bundle-budget": "node scripts/check-bundle-budget.mjs"
  }
}
```

Run: `npm --prefix frontend install --package-lock-only --ignore-scripts`

Expected: lockfile 更新；没有从绝对路径或工作区外引用依赖。

- [x] **Step 5: 运行测试和依赖安装检查**

Run: `python -m pytest rebuild/tests/test_runtime_dependencies.py -q && npm --prefix frontend ci --ignore-scripts --no-audit --no-fund`

Expected: PASS；安装完成。

- [x] **Step 6: 提交**

```bash
git add backend/requirements.txt backend/app/core/config.py frontend/package.json frontend/package-lock.json frontend/playwright.config.ts rebuild/tests/test_runtime_dependencies.py
git commit -m "build(rebuild): enforce A-share PostgreSQL runtime"
```

### Task 2: 建立唯一当前 API Router

**Files:**
- Create: `backend/app/api/api.py`
- Create: `backend/app/api/endpoints/health.py`
- Create: `backend/tests/test_current_api_router.py`
- Modify: `backend/app/main.py`
- Modify: `frontend/src/api/client.ts`
- Delete after consumer migration: `backend/app/api/v2/`

**Interfaces:**
- Consumes: `Settings`、后续 `AppContext`。
- Produces: `create_api_router(context: AppContext) -> APIRouter`、`GET /api/health`、`GET /api/health/storage`。

- [x] **Step 1: 写当前 API 失败测试**

```python
def test_only_current_api_is_registered(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health/storage").status_code == 200
    assert client.get("/api/v2/health").status_code == 404
    assert client.get("/api/v1/health").status_code == 404

def test_openapi_has_no_versioned_paths(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert all("/api/v" not in path for path in paths)
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_current_api_router.py -q`

Expected: FAIL，BitPro Router 仍注册带版本号路径。

- [x] **Step 3: 实现唯一 Router**

```python
def create_api_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    router.include_router(health.router, prefix="/health", tags=["health"])
    return router

def create_app(context: AppContext | None = None) -> FastAPI:
    app_context = context or build_app_context()
    app = FastAPI(title="StockPro")
    app.include_router(create_api_router(app_context), prefix="/api")
    return app
```

- [x] **Step 4: 删除旧 Router 并静态扫描消费者**

先用 `rg -n '/api/v|app\.api\.v2|api_router_v2' backend frontend tests` 列出消费者，
在同一提交中迁移健康消费者后删除 `backend/app/api/v2/`。不得添加 redirect。

- [x] **Step 5: 运行 Router 与安全测试**

Run: `python -m pytest backend/tests/test_current_api_router.py rebuild/tests/test_safety.py -q && python rebuild/assert_safety.py --root . --format json`

Expected: PASS；`active_versioned_api_routes=0`。

- [x] **Step 6: 提交**

```bash
git add backend/app/api backend/app/main.py backend/tests/test_current_api_router.py frontend/src/api/client.ts
git commit -m "feat(api): expose one current StockPro contract"
```

### Task 3: 恢复 PostgreSQL 基础设施并建立 Repository 协议

**Files:**
- Restore from StockPro baseline: `backend/app/db/postgres_db.py`
- Restore from StockPro baseline: `backend/app/db/postgres_migrations.py`
- Restore from StockPro baseline: `backend/postgres/migrations/`
- Create: `backend/app/repositories/protocols.py`
- Create: `backend/app/repositories/postgres_repository.py`
- Create: `backend/app/core/app_context.py`
- Test: `backend/tests/test_postgres_repository_contract.py`

**Interfaces:**
- Produces: `HealthRepository.storage_health() -> StorageHealth`、`AuthRepository`、`MarketRepository`、`StrategyRepository`、`BacktestRepository`、`PaperRepository` 等分域 Protocol；本 Wave 只实现健康与认证所需方法。
- Produces: `Repositories(health, auth)` 与 `AppContext(settings, repositories, clock)`；后续 Wave 在 `Repositories` 上增加领域接口。

- [x] **Step 1: 写 Repository 合同失败测试**

```python
def test_storage_health_reads_postgres_migrations(repository):
    health = repository.storage_health()
    assert health.database == "postgresql"
    assert health.applied_migrations == 37
    assert health.expected_migrations == 37
    assert health.status == "healthy"
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_postgres_repository_contract.py -q`

Expected: FAIL，Repository 不存在。

- [x] **Step 3: 从基线恢复明确文件**

在隔离 worktree 中执行：

```bash
git restore --source=99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440 -- \
  backend/app/db/postgres_db.py \
  backend/app/db/postgres_migrations.py \
  backend/postgres/migrations
```

不得恢复旧 API Router、页面或 Service。

- [x] **Step 4: 定义小而明确的 Protocol**

```python
@dataclass(frozen=True)
class StorageHealth:
    status: Literal["healthy", "error"]
    database: Literal["postgresql"]
    applied_migrations: int
    expected_migrations: int

class HealthRepository(Protocol):
    def storage_health(self) -> StorageHealth: ...
```

后续领域 Protocol 放在同一文件但按对象分组；不得提供通用 `execute_sql()` 给页面 Service。

- [x] **Step 5: 实现 AppContext**

```python
@dataclass(frozen=True)
class Repositories:
    health: HealthRepository
    auth: AuthRepository

@dataclass(frozen=True)
class AppContext:
    settings: Settings
    repositories: Repositories
    clock: Callable[[], datetime]

def build_app_context() -> AppContext:
    database = PostgresDatabase(settings.DATABASE_URL)
    repository = PostgresRepository(database)
    repositories = Repositories(health=repository, auth=repository)
    return AppContext(settings=settings, repositories=repositories, clock=utc_now)
```

- [x] **Step 6: 运行测试与存储健康**

Run: `python -m pytest backend/tests/test_postgres_repository_contract.py backend/tests/test_current_api_router.py -q`

Expected: PASS；隔离数据库迁移数为 37。

- [x] **Step 7: 提交**

```bash
git add backend/app/db backend/app/repositories backend/app/core/app_context.py backend/postgres/migrations backend/tests/test_postgres_repository_contract.py
git commit -m "feat(storage): restore PostgreSQL repository foundation"
```

### Task 4: 迁移认证到 PostgreSQL 当前合同

**Files:**
- Restore/adapt: `backend/app/core/admin_auth.py`
- Create: `backend/app/domain/auth/models.py`
- Create: `backend/app/api/endpoints/auth.py`
- Create: `backend/app/services/auth_service.py`
- Modify: `backend/app/repositories/protocols.py`
- Modify: `backend/app/repositories/postgres_repository.py`
- Test: `backend/tests/test_auth_contract.py`
- Modify: `frontend/src/auth/AuthProvider.tsx`
- Modify: `frontend/src/pages/Login.tsx`

**Interfaces:**
- Produces: `POST /api/auth/admin/login`、`POST /api/auth/guest/login`、`GET /api/auth/me`、`AuthProfile`。
- Consumes: 现有 PostgreSQL auth sessions、guest codes、MCP token scopes。

- [x] **Step 1: 写管理员/访客/未登录失败测试**

```python
def test_current_auth_contract(client):
    admin = client.post("/api/auth/admin/login", json={"username": "admin", "password": "secret"})
    assert admin.status_code == 200
    token = admin.json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["role"] == "admin"
    assert client.get("/api/market/overview").status_code == 401
```

- [x] **Step 2: 运行失败测试**

Run: `python -m pytest backend/tests/test_auth_contract.py -q`

Expected: FAIL，认证路由尚未注册或仍依赖 SQLite。

- [x] **Step 3: 实现 AuthService 与 Repository 方法**

```python
@dataclass(frozen=True)
class AuthToken:
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int

@dataclass(frozen=True)
class AuthProfile:
    role: Literal["admin", "guest"]
    username: str | None
    permissions: tuple[str, ...]
    session_id: str

class AuthService:
    def login_admin(self, username: str, password: str) -> AuthToken: ...
    def login_guest(self, code: str) -> AuthToken: ...
    def resolve(self, token: str) -> AuthProfile: ...
```

Token、session 和 guest quota 只读写现有 PostgreSQL 表；明文邀请码和 token 不落库。

- [x] **Step 4: 注册受保护 Router**

`create_api_router()` 建立一个带 `require_authenticated` dependency 的业务 Router；健康和登录保持公共。

- [x] **Step 5: 迁移 BitPro AuthProvider**

前端只调用 `/api/auth/admin/login`、`/api/auth/guest/login`、`/api/auth/me`；
访客写操作继续由 DOM 守卫和 Axios interceptor 双重拒绝。

- [x] **Step 6: 运行后端和前端认证测试**

Run: `python -m pytest backend/tests/test_auth_contract.py -q && npm --prefix frontend run build`

Expected: PASS；构建中无旧 API 字符串。

- [x] **Step 7: 提交**

```bash
git add backend/app/core/admin_auth.py backend/app/domain/auth/models.py backend/app/api/endpoints/auth.py backend/app/services/auth_service.py backend/app/repositories frontend/src/auth frontend/src/pages/Login.tsx backend/tests/test_auth_contract.py
git commit -m "feat(auth): use PostgreSQL current authentication contract"
```

### Task 5: 建立 BitPro MainLayout 与诚实工作区骨架

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/MainLayout.tsx`
- Create: `frontend/src/pages/rebuild/UnavailableWorkspace.tsx`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/types/index.ts`
- Create: `frontend/tests/e2e/rebuild-shell.spec.ts`
- Modify: `frontend/playwright.config.ts`

**Interfaces:**
- Consumes: `/api/auth/*`、`/api/health`。
- Produces: approved navigation, stable Outlet shell, `apiClient` with `/api` base, route-level unavailable ViewModel。

- [x] **Step 1: 写 shell E2E 失败测试**

```typescript
test('shell remains mounted and only approved A-share routes are visible', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/')
  const shell = page.getByTestId('main-layout')
  await expect(shell).toBeVisible()
  for (const label of ['首页','行情','股票池','因子','策略','回测','模拟','盯盘','信号','监控','复盘','数据','AI研发']) {
    await expect(page.getByRole('navigation').getByText(label, { exact: true })).toBeVisible()
  }
  for (const hidden of ['实盘','链上','ARC','套利','期货']) {
    await expect(page.getByRole('navigation').getByText(hidden, { exact: true })).toHaveCount(0)
  }
  await page.getByRole('link', { name: '策略' }).click()
  await expect(shell).toBeVisible()
})
```

- [x] **Step 2: 运行失败 E2E**

Run: `npm --prefix frontend run test:e2e -- --grep "shell remains mounted"`

Expected: FAIL，导入路由仍包含 BitPro 数字资产页面或 shell 缺稳定 test id。

- [x] **Step 3: 实现唯一前端 API client**

```typescript
export const apiClient = axios.create({ baseURL: '/api', timeout: 30_000 })
```

拦截器只处理当前认证合同；源码不得包含带版本号 API 前缀。

- [x] **Step 4: 实现批准导航和占位页面**

```typescript
type WorkspaceState = {
  title: string
  description: string
  ownerRoute: string
  status: 'adapting'
}
```

所有尚未完成页面路由指向 `UnavailableWorkspace`，显示“正在接入 A股 PostgreSQL 数据”，
不发业务请求。`/paper` 替代 BitPro `/live`，不注册 `/live-real`。

- [x] **Step 5: 确保 Suspense 只包 Outlet**

MainLayout 常驻侧栏、顶部状态和错误边界；懒加载 fallback 只能替换内容 Outlet。

- [x] **Step 6: 运行构建、E2E 和静态安全扫描**

Run: `npm --prefix frontend run build && npm --prefix frontend run test:e2e -- --grep "shell remains mounted" && python rebuild/assert_safety.py --root . --format json`

Expected: PASS；无隐藏数字资产入口，安全计数全 0。

- [x] **Step 7: 提交**

```bash
git add frontend/src/App.tsx frontend/src/components/MainLayout.tsx frontend/src/pages/rebuild frontend/src/api/client.ts frontend/src/types/index.ts frontend/tests/e2e/rebuild-shell.spec.ts frontend/playwright.config.ts
git commit -m "feat(ui): establish BitPro A-share operator shell"
```

### Task 6: Wave 1 完整验证与文档

**Files:**
- Modify: `scripts/check.sh`
- Modify: `docs/pages/登录门禁.md`
- Modify: `docs/pages/首页.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: Wave 1 当前 API、认证、Repository 和 shell。
- Produces: 后续页面可依赖的稳定应用骨架与验证入口。

- [ ] **Step 1: 把 Wave 1 检查加入统一入口**

`scripts/check.sh` 顺序固定为：安全扫描、Python编译、后端测试、前端依赖检查、类型检查、lint、构建、bundle预算、Mock shell E2E。

- [ ] **Step 2: 更新页面合同**

登录与首页文档记录 BitPro 首屏结构、当前数据源、未适配状态、错误状态和截图合同；
不宣称首页业务模块已完成。

- [ ] **Step 3: 运行完整 Wave 1 验证**

Run: `./scripts/check.sh`

Expected: 全绿；lint 零错误；安全扫描全 0；未启动 Provider、scheduler、Paper recovery。

- [ ] **Step 4: 记录 Paper 基线复核**

Run: `python rebuild/verify_baseline.py --baseline .codex-artifacts/rebuild/baseline.json --database "$DATABASE_URL" --read-only`

Expected: PASS；Wave 1 没有业务表计数变化。

- [ ] **Step 5: 提交**

```bash
git add scripts/check.sh docs/pages/登录门禁.md docs/pages/首页.md docs/progress.md
git commit -m "docs(rebuild): accept current API operator shell"
```

Wave 1 完成后，应用可以启动，但除认证、健康和 shell 外的页面仍保持诚实未适配状态。
