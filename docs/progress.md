# Progress Log

## BitPro 原代码直接移植重置（2026-08-26）

- 用户否决了 `116f543f` 的“页面映射 + A 股重写”结果：它不是所要求的
  BitPro 原代码主体，不再作为当前实现基础，只保留为生产回滚点。
- 新分支 `codex/bitpro-direct-port` 从当前 `origin/main` 建立；提交 `8f269c09`
  使用 BitPro 固定源 `2e4b90c3` 直接覆盖 `backend/frontend/packages/scripts/tests`。
  五个根目录 checksum 对比零差异，BitPro 前端原样 build/lint 通过。
- 第二个切片只做启动安全封锁：BitPro 页面、组件和业务源文件继续原位保留；
  StockPro 当前后端入口不导入 SQLite、交易所、下单、调度器、WebSocket 或策略引擎，
  并移除 `/live-real` 实盘入口。安全扫描五类 active 计数均为 0，76 个 BitPro
  数字资产源文件等待在原位逐项改为 A 股实现。
- 安全后端只启动 `4445` 的 health/auth 读取端点，前端保持 BitPro 原导航和工作台结构。
  下一步从行情与数据层开始，在这份原代码上将字段、API 和数据源换为 A 股。
- 行情第一个纵向切片已在 BitPro 原 `Market.tsx` / `SymbolSearch.tsx` / `MarketDomainService`
  与 `/api/v2/market` 合同上完成：不换页面，后端直读 PostgreSQL A 股证券、报价和日线，
  前端将合约/现货、USDT、资金费率和币种搜索原位换为股票/ETF/指数、人民币、
  T+1/100 股整手和 A 股代码搜索。真实接口返回 5,000 个证券、`600519.SH` 报价与日线。
  浏览器保持 BitPro 原 K 线/盘口/成交布局，写请求 0、API 5xx 0、console errors 0。
- 策略目录切片已在 BitPro 原 `Strategy.tsx`、`StrategyDomainService` 和
  `/api/v2/strategies` 上完成只读接入：PostgreSQL 128 个版本按名称取最新后展示 78 个 A 股策略，
  BitPro 原分页、搜索、卡片和详情交互保留；现货/合约、马丁/做市、USDT 资金档改为
  股票/ETF、动量趋势/均值回归/多因子/事件驱动和人民币资金档。未完成不可变版本写入前，
  新建/编辑/删除和 AI 写策略按钮不展示，真实浏览器读取写请求 0、API 5xx 0、console errors 0。
- 回测历史切片已在 BitPro 原 `Backtest.tsx`、`backtestSupport.tsx` 和
  `/api/v2/backtest` 合同上完成：直读 PostgreSQL `backtest_runs/trades/daily_equity`，将原始 A 股比例指标
  转成 BitPro 页面 ViewModel，并保留原实例表、排序、筛选、对比和详情结构。当前真实页显示
  20 条历史（18 完成/2 失败），详情可读 27 笔成交和 102 个权益点；基准改为沪深300，
  现货/合约改为股票/ETF，资金改为 CNY。异步创建任务尚未接通前不展示创建入口。
- 模拟盘切片已直接接入 BitPro 原 `/live` `InstanceDashboard` / `InstanceMonitor`：
  `/api/v2/live/instances|dashboard|events|equity_curve|trades` 只读适配层映射 PostgreSQL
  22 个 Paper 实例、现金账本、持仓、成交、事件和权益曲线，没有引入另一套 Paper 页。
  实例页筛选改为股票/ETF、A 股策略类型、1D 和人民币资金档；详情的账户/收益单位改为 CNY，
  仓位风控改为现金、T+1、涨跌停和整手语义。未完成生命周期写入前整页只读，Paper 详情不再连接币圈 WebSocket。
- BitPro 原首页 `MarketUniversePanel` / `NativeDataPanel` 已切到 A 股口径：新增
  `/api/v2/system/health` 和 `/api/v2/market/native-sentiment`，从 PostgreSQL 读取证券数、涨跌家数、
  成交额、平均涨跌、日线记录数和交易日水位。原 OKX/USDT/BTC/资金费率数据请求与 WebSocket
  已停用，榜单和大盘情绪结构保留并改为 A 股成交额/涨幅/跌幅榜和市场广度。

## BitPro 逐文件复刻对账（2026-08-26）

### 生产交付

- 功能分支 `8c2537b4` 已通过 merge commit `88427d40` 进入 `main`；GitHub Actions
  `Deploy StockPro` run `32879473170` 成功，部署记录 SHA 与 `main` 一致。
- 生产应用 39/39 migrations，systemd/Nginx 均 active，内网和公网 `/api/health`、
  `/api/health/storage`、HTTPS 首页全绿。此轮生产业务计数仍为 0，未把隔离库的
  22 个 Paper 实例迁入生产，也未伪造数据。
- 生产 HTTPS 经真实管理员登录后的 13 路由 × 桌面/390px 只读 canary 全部通过：
  page errors 0、API 5xx 0、横向溢出 0。
- post-deploy production manifest、canary、final completion audit SHA-256 分别为
  `854d60709b976fa8ef0f5f015dce4c36899336d495e3106315c53124e7ecc920`、
  `a0ed5669e435d0fa68276f635b7de1a9351b603e5126b3c717ef028f3cf45511`、
  `7e58b064709be76552017cde23297f06a46cd6282c61611ee2a21a4b1c4b8937`；10 项要求全部 passed。

- 新增机器可执行的前端 parity 审计；对固定 BitPro SHA `2e4b90c3` 的 78 个
  TypeScript/TSX/CSS 源文件逐项核对。当前结果为 41 个字节级一致、37 个固定源哈希的
  A 股适配、0 个未分类，审计产物纳入 completion gate `PARITY-001`。
- 12 个不再保持同路径的 BitPro 源文件以逐字 `.disabled` 参考副本保存；活动产品通过
  manifest 将其映射到 A 股行情、股票池、数据、策略、模拟盘与 AI 工作台，不把隔离副本
  计作功能完成证明。
- 旧 `/live`、`/trading`、`/arbitrage`、`/onchain`、`/orderflow`、`/arc` 深链分别解析到
  A 股模拟盘、策略、数据、行情和 AI Owner 页面；`/live-real` 继续明确不可用，侧栏不显示
  实盘、链上、ARC、套利或期货入口。
- focused Python 6 项、TypeScript、零告警 lint、生产构建、25 项 Mock Playwright 全绿；
  前后端已干净重启，`4444`/`4445` 监听且 `/api/health` 返回 `rebuild_safe`。
- 隔离库全仓门禁已通过：107 个 Python 测试、25 个 Mock E2E、bundle budget、依赖审计、
  39 个迁移、0 条期货记录；Paper 22 实例/165 单/108 成交/49 持仓/970 权益/2013 事件
  连续性通过。真实管理员登录后的 13 路由 × 桌面/390px 验收 2 项通过，API 5xx 与页面异常均为 0。
- 首轮全仓检查发现同步导入导致首屏 JS 超预算，恢复 BitPro 路由级 lazy loading 后首屏从
  658.0 KiB 降到 355.9 KiB，主包从 391.7 KiB 降到 83.6 KiB。
- 当前提交已重拍 13 路由 × 2 viewport 共 26 张真实截图；采集器要求每页离开骨架和
  “正在加载/读取中”状态，并隔离每个页面避免图表/定时器污染。清单显示控制台错误 0、
  业务写请求 0，人工抽检主页、策略和回测均为真实数据或诚实状态。
- 仍未完成：生产部署与 deployed SHA 验收；本目标尚未关闭，也未推送或部署。

## 运营闭环恢复 + 7策略晋级模拟盘（2026-08-25）

本轮在 BitPro-first 重建底座上恢复生产级运营能力，并完成首轮 A 股策略研究晋级。

### 运营层恢复
- 移植 `KlineSyncService`（按交易日全市场拉取）与 `DailyReferenceSyncService`
  （日终链：交易日历门禁→日线同步→快照封存→辅助分区→Universe→因子计划→行情证据，
  PG advisory lock 防并发，`dataset_orchestration_runs` 全量留痕）。
- 新增 `AshareSchedulerService`（APScheduler，Asia/Shanghai）：盘后 17:30 日终链、
  每小时 Paper 兜底推进、每日三次运营心跳；经 FastAPI lifespan 挂载，
  `ENABLE_SCHEDULER` 显式开关。
- 修复两处高延迟隧道性能缺陷：批量写入统一 page_size=2000；sync_metadata 刷新从
  逐标的 2 次 RTT 改为聚合批量（全市场单日写入 2.6 小时 → 30 秒）。
- 补齐 2025-01~2025-07 共 103 个交易日的全市场日线缺口（TuShare 按日回填）。

### Qlib 数据模块
- `QlibExportService`：已发布日线分区 → 标准 Qlib bin 布局
  （calendars/instruments/features，NaN 表达缺失，增量刷新）。
- 503 交易日 × 5,550 标的导出验证通过；`/api/data/qlib/status|export` 端点
  与数据中心「Qlib导出」页签；日终链成功后自动增量刷新。

### 前端补齐
- 设置中心全部端点落地（notify/飞书 webhook/LLM 模型配置与连通性测试/
  MCP Agent Token（SHA-256 存储、明文仅返回一次）/访客邀请码管理）；
  新增迁移 `202608240001_settings_and_agent_tokens.sql`。
- 监控页新增「日终调度」面板（任务注册状态、盘后 cron、日线水位、管理员手动触发）。
- 登录页管理员登录 Tab 前置并设为默认模式。
- client.ts 删除 7 个无引用的币圈 API 块（约 210 行）。

### 大扫除
- 删除 40+ 个 import 即崩的隔离文件（exchange/strategies/workers/local_db/
  旧 scheduler_service/agent 包等）与根目录三套平行遗产。
- 防回归测试改为断言彻底移除（而非隔离）；安全扫描 0 活跃命中。

### 策略研究与晋级
- 新研究 12 个 Strategy API v1 策略 + 3 个参数变体（动量/趋势/均值回归/低波动/
  量价/多因子/布林/隔日反转/新高/小市值因子等方向），全部通过 AST 沙箱验证。
- 建立「全市场流动性 Top500」股票池（快照 #9）、研究协议 v3（训练/验证/样本外
  三段 + 容量/回撤/夏普阈值，封存不可变）与因子快照 #8（94 因子）。
- **7 个策略通过全部 11 项晋级门禁并上线模拟盘**（快照 #35 全参考数据绑定）：

| 策略 | 方向 | 完整回测 | 门禁 |
| --- | --- | --- | --- |
| 连板晋级隔日T | 打板 | +56.8% 夏普4.33 回撤9.0% | 全过 |
| 多因子风险预算 | 多因子 | +65.0% 夏普3.15 回撤15.9% | 全过 |
| 均值回归 三日超跌反弹 | 均值回归 | +46.7% 夏普3.07 回撤14.3% | 全过 |
| 高度板隔日T | 打板 | +35.5% 夏普2.72 回撤13.3% | 全过 |
| 首板放量隔日T | 打板/量能 | +31.1% 夏普2.87 回撤9.3% | 全过 |
| 尾盘强势 | 日内强势 | +77.7% 夏普5.00 回撤10.8% | 全过 |
| 隔日T超跌 低开高走反抽 | 日内反转 | +12.0% 夏普0.91 回撤13.6% | 全过 |

- 约 15 个候选被门禁真实拒绝（多数卡在训练段风控），拒绝证据逐段留档
  `backtest_protocol_evaluations`。参数变体研究入库供后续窗口复用。

### 已知边界
- 模拟盘当前为封存快照回放模式（recorded_replay）；实时盘中行情接入不在本轮范围。
- `rebuild/tests` 部分验收测试依赖重建期环境，本轮验证以 `backend/tests`（61 项全绿）
  + 前端 tsc/build 为准。
- 生产部署未触发：工作在 `codex/ashare-operations-restore` 分支，合并 main 前需
  完成与最新 main 的集成验证。

---

## 文档全量整治（2026-08-24）

- 修正 6 处错误健康路径 `/api/health/health` → `/api/health`（README、deployment、
  api、SCRIPTS_USAGE、technical_architecture、todo）；历史 progress/合同中的旧记录保留不改。
- 重写 `README.md`：快速开始前置、验证去重、隔离库为默认数据库口径、工作区表直链
  `docs/pages/` 页面合同；`README.en.md` 同步（13 工作区侧栏、隔离库黄金路径）。
- 重写 `docs/api.md`：接口域表对照 `backend/app/api/api.py` 重新生成，删除不存在的
  workflow/stocks/charts/data-hub/data-dev/acceptance 域与访客码管理端点；MCP 头改为
  实际默认 `X-BitPro-MCP-Token`；Paper 生命周期补 `/advance`。
- 根目录清理：删除 `README.zh-CN.md` 存根；Electron/优化总结/AKShare 笔记移入
  `docs/archive/` 并附索引说明。
- `docs/index.md` 重建：新增页面合同区、修正 active 合同指向 `contracts/active.md`、
  移除失效的 `frontend/README.md` 链接。
- 修复 GitHub 不识别的 `{#isolation-database}` 自定义锚点，3 处入站链接改用自然锚点
  `#7-隔离库`；`todo.md` 封存为历史快照并加显著 banner；strategies README 路由改为
  `POST /api/strategies`；登录门禁页删除 Wave 占位措辞；AGENTS.md 验证节补隔离库前置。
- 验证：自研链接检查脚本扫描 269 个内部链接 0 死链；`git diff --check` 通过；
  纯文档变更，未触碰代码与服务。

## DX worktree clarification docs (#7)（2026-08-24）

- README 新增「仓库布局」：产品树为 worktree `StockPro-bitpro-a-share`（`main`）；
  主目录 `StockPro` 的 `codex/bitpro-a-share-rebuild-design` 设计分支仅作归档，
  不再用于日常开发或开 PR，动手前先 `git worktree list` 确认所在树。
- 纯文档变更；验证为 `git diff --check`。

## DX isolation DB and A-share run_demo (#18, #19)（2026-08-24）

- 新增一键脚本 `scripts/setup_isolation_db.sh`：Docker Compose profile `isolation`
  或 SQL/`provision_isolation_db.py` 创建 `stockpro_bitpro_rebase_dev`。
- `scripts/check.sh` 在 `DATABASE_URL` 缺失或非隔离时退出，并指向该 setup 命令与
  `docs/deployment.md#isolation-database`。也可从 `backend/.env` 读取 URL。
- `scripts/run_demo.py` 改为 A 股 Paper：`AShareSpotBroker`、`600000.SH`、CNY
  现金账本、T+1、100 股；可选 `--list-instances` 只读列出隔离库 Paper。不再使用
  SQLite `crypto_data.db`、Kairos、BTC/USDT、OKX。
- 未改 BitPro，未加产品页。下一步：Eva 跑 setup 后重跑 `/api/health`、
  `/api/health/storage` 与 `./scripts/check.sh`。

## Shell nav and workbench state machine (#14, #11)（2026-08-23）

- 前端壳层继续使用 BitPro IA：首页 / 行情 / 股票池 / 因子 / 策略 / 回测 / 模拟 / 盯盘 /
  信号 / 监控 / 复盘 / 数据 / AI研发。期货预留仍回首页；实盘、套利、链上、ARC、旧交易页
  深链改为明确不可用状态，并指向模拟盘现金账本或首页。
- 侧栏和 `App.tsx` 不注册 `live-real` / `onchain` / `arbitrage` / `arc`；未知路由由
  `UnknownWorkspace` 解析。加载 / 错误 / 权限 / 不可用态复用 `@bitpro/ui`。
- 壳层文案改为 A股口径：代码.市场、交易日历、模拟盘/现金账本；设置中心不再发放
  `live_diagnostic`。
- #11：`frontend` 包名改为 `stockpro-frontend`；删除未路由的 Arbitrage / Onchain / Arc /
  liveTrading / Trading / WatchMarket 页面。
- 本地验证：`tsc` / lint 0 warning / production build / bundle budget、rebuild safety
  `active=0 quarantined=54`、mock Playwright shell/home/market/paper/futures/capabilities/
  final-state-matrix 全部通过。`./scripts/check.sh` 因本环境缺少隔离库 `DATABASE_URL`
  与 backend venv 未跑全量。

## Backend P0 #13/#9/#10：A股现货 Paper broker（2026-08-23）

- 抽出 `AShareSpotBroker`：`code.market`、交易日历、T+1、100 股整手、现金账本。
- Paper 成交费用与 `AShareBacktestEngine` 对齐（佣金 + 印花税 + 过户费）。
- Paper 拒绝涨停买、跌停卖、停牌和非交易日。不开启实盘。

## Backend P0 #8/#12：移出加密交易所与 OKX 脚本（2026-08-23）

- 将 OKX/Binance 实盘交易所、合约 Paper/Broker、funding/arb/`contract_*` 策略
  以及 `sync_okx_universe.py` / `okx_orbit_publisher.js` 移到
  `archive/bitpro-crypto/`，不在默认产品树中。
- `strategy_registry` 不再注册加密策略；OKX/funding/contract key 会被拒绝。
- 不开启实盘，不修改 BitPro。下一步是 #13 A股现货 Paper broker。

## BitPro-first A股整仓迁移完成（2026-08-23）

- PR #4 合并应用重建，merge SHA `4c7fe5194cae7abf6c07a8be005bbfb573b032d8`。首次自动部署
  run `32647022871` 在服务器同步前因失效的 frontend precheck 失败，生产旧版本保持健康。
- PR #5 删除不存在脚本的 workflow 引用；merge/生产 SHA
  `381ec5429114a52af71aae7948834a3f6538f366`，GitHub Actions run `32647137727` 成功。
- 生产数据库仅执行 additive 37→38 migration；策略、回测、Paper、订单、成交、持仓、权益、
  事件、复盘、信号和告警 pre/post 计数均为 0，无减少或改写。
- systemd、Nginx、内外 `/api/health` 和 storage health 全绿；公网 8 个关键路由正常管理员登录
  canary 通过，无 request interception、console errors 0，耗时 1.86–2.58 秒。
- Post-deploy completion audit 的九项 required 全部 passed；final audit SHA-256
  `188d9f9bbfd0e6f855615441f8325a6f41e188cd692b86845364271bff868b1c`。合同关闭。

## PR #4 合并前部署探针修复（2026-08-23）

- 快速 pre-landing review 发现 `deploy/deploy.sh` 内外健康检查仍使用旧
  `/api/health/health`，会使新应用部署在健康门禁阶段失败。
- 已统一为当前 `/api/health` 并新增部署合同测试；`bash -n`、84 Python、24 Mock E2E、
  build/lint/bundle/audit 和 completion audit 全绿。修复提交后更新 PR，不绕过远端流程。

## 生产切换：数据库凭据无中断轮换（2026-08-23）

- 获得最终迁移授权后，创建 `stockpro_rebuild_app` 并继承旧对象所有者权限；服务器 `.env`
  原子切换到新角色，真实连接验证为 `stockpro_rebuild_app|stockpro_prod`。
- GitHub Actions workflow_dispatch run `32646230741` 强制重部署当前 main/旧 SHA，2 分钟成功；
  systemd、Nginx、内外健康通过，`pg_stat_activity` 只见新角色活动连接。
- 旧 `stockpro_app` 已设为 `NOLOGIN` 并更换随机密码，早期暴露凭据失效；没有把密码写入
  仓库、日志或报告。生产业务代码仍是旧基线，下一步推送重建分支并创建 PR。

## BitPro-first Wave 6：Pre-deploy 最终验收完成（2026-08-23）

- 机器 completion audit 的 BASE/API/DB/PAPER/SAFE/UI/ASHARE/FUTURE 全部 passed；唯一 pending
  为 `DEPLOY-001=pending_final_confirmation`。
- 最终全仓入口通过 83 个 Python、24 个完整 Mock Playwright、真实 13 路由 × 双 viewport、
  TypeScript、零告警 lint、生产构建、bundle budget、0 dependency vulnerabilities 和安全扫描。
- 26 张真实隔离截图使用正常管理员登录、无拦截/DOM 注入/写请求，console errors 0；Watch
  single-flight 后双冷读约 16.6 秒，Signals 专用查询约 1.6 秒。
- 最新 `stockpro_dev` 恢复到受限临时库并应用 37→38 migrations，所有 Paper/策略/回测/复盘
  连续；固定旧 SHA 进程在 PG 强制只读下，健康/策略/回测/Paper HTTP 200；临时资源已清理。
- 切换就绪报告写入 `docs/qa/bitpro-first-rebuild-cutover-readiness.md`；其后的生产执行和
  验收结果记录在本文件顶部“BitPro-first A股整仓迁移完成”。

## BitPro-first Wave 5：数据、AI 与 Instrument 能力验收（2026-08-23）

- 新增 `/api/capabilities`：enabled stock/ETF/index、reserved future、PostgreSQL、A股 Paper
  runtime、live=false、futures routes=false、private broker=false；全部为当前无版本 API。
- `scripts/check.sh` 纳入 DataManager、AI Lab、期货隐藏和 capability shell。最终通过 67 个
  Python 测试、19 个 Shell/研究/主线/运行/能力 E2E、类型、零告警 lint、生产构建、bundle
  budget、0 dependency vulnerabilities、diff whitespace 和五类安全扫描。
- 内联审阅把 AI 模型 HTTP 调用移入线程池，避免阻塞 FastAPI 事件循环；配置模型路径仍只
  创建验证策略 + quick replay，不创建完整回测或 Paper。
- 真实 Data/AI 页面 desktop/390px：GET 写入 0、Provider/模型调用 0、console errors 0、
  页面级溢出 0。隔离库 38 migrations、5,550 stock、0 ETF、4 index、0 future；Paper
  15/61/47/23/428/681 连续性最终通过。Wave 5 未合并、推送或部署。

## BitPro-first Wave 5：隐藏期货领域预留（2026-08-23）

- 新增第 38 个 additive migration `instrument_definitions`，唯一键为 market/exchange/symbol，
  支持 stock/ETF/index/future 的真实元数据字段；非期货记录由 CHECK 禁止填写期货字段。
- 隔离库显式回填 5,550 个现有股票和 4 个指数；当前权威 security_master/行情缓存没有 ETF
  记录，因此 ETF 为零而不是伪造。期货记录为 0，所有期货元数据保持等待真实数据源。
- 新增 `InstrumentAdapter`、`AshareCashAdapter`、CN/US Futures Protocol；只实例化 A股现金
  适配器。期货 Protocol 没有 Provider、credential、network 或 execution 实现。
- `/futures` 不注册并回首页，导航无期货；模型/隐藏入口/安全测试通过。迁移修正真实
  `SH_/SZ_/BJ_` 代码格式后重放，新表之外未改原证券/行情表，Paper 前后连续性通过。

## BitPro-first Wave 5：A股 AI 研发工作台（2026-08-23）

- `/ai-lab` 已重塑为自动研究、策略研发、现有策略优化三工作区；保留任务配置、任务/迭代、
  策略代码、quick 指标、评分和验证候选保存，不含发帖或数字资产模块。
- 研究表单显式要求 dataset/universe/股票池/因子 snapshot ID 与日期；模型状态来自真实
  `/api/ai/config`。当前真实状态 unavailable，页面明确不生成 mock、随机或模板结论。
- 保存候选常驻提示“不运行完整回测、不创建 Paper”；不存在自动实盘、自动模拟或启动
  Paper 按钮。访客不允许创建/启动任务。
- Mock 边界 E2E、类型/lint/build通过；真实桌面/390px 三页签、unavailable 状态可见，
  HTTP 写入/模型调用 0、console errors 0、无页面级溢出，Paper continuity 通过。

## BitPro-first Wave 5：A股 AI 研发当前合同（2026-08-23）

- 新增当前 `/api/ai/config|tasks|start|stop|iterations promote-candidate` 与 PostgreSQL
  `agent_tasks/agent_iterations` Repository；不注册旧 AI/交易所/发帖入口。
- 未配置 DashScope/Qwen 时 start 明确 failed“模型未配置”，不生成 mock、随机或模板输出。
  配置后只向模型发送 A股当前策略合同、目标和封存 dataset/universe/pool/factor manifest。
- 模型候选必须通过当前 AST 验证后保存为 StrategyVersion，只运行 quick replay；Evaluator
  只用 quick 指标做 deterministic score 并标注，不产生市场预测或晋级资格。
- promote-candidate 只接受 validation_status=valid 的已有版本；响应固定
  `paper_created=false`、`full_backtest_created=false`。无模型、配置模型快照和 promote 门禁
  3 项测试、安全扫描和编译通过，私有交易所调用 0。

## BitPro-first Wave 5：A股数据中心（2026-08-23）

- `/data` 已恢复 BitPro 七工作区：总览、研究数据、行情覆盖、同步任务、数据源、质量、导入
  导出；真实显示 10 数据集、686,840 发布记录、28 封存快照和 restricted Provider。
- 数据集表展示主源/整类回退/分区/记录/Watermark，来源授权展示 permission/cache/export
  policy；质量和任务保留完整错误/状态证据，缺失值不造 0。
- 导入导出页常驻“仅暂存 · 未映射”边界，管理员可选择 CSV/JSON/XLSX；访客不显示上传。
  页面加载没有 Provider、同步、质量、迁移、封存或扩展写入。
- Mock 七区 E2E、类型、零告警 lint、生产构建通过。真实桌面/390px 七标签可见，GET 写入 0、
  console errors 0、根页面无溢出，Paper continuity 通过。

## BitPro-first Wave 5：PostgreSQL 数据可信度 API（2026-08-23）

- 新增当前 `/api/data/*` status/datasets/snapshots/providers/schedules/jobs/quality/exchange；GET
  只读 PostgreSQL，不调用 Provider。隔离运行时 Provider 状态明确为 restricted。
- 真实状态为 10 datasets、211 published partitions、686,840 rows、28 sealed snapshots、
  42 sync jobs、47 quality issues、21 source entitlements、0 staged imports；读取写入/Provider
  调用均为 0。
- 扩展 CSV/JSON/XLSX 限制 5MB/10,000 行/200 列，拒绝公式前缀，只写独立 staged
  imports/records 并返回 `mapping_state=staged_only`、`execution_eligible=false`；导出防公式
  注入。HTTPS 仅允许精确 allowlist + 公共 DNS + 禁止重定向。没有真实导入验收数据。
- 同步/质量 POST 只创建 pending 审计 job，受控 worker 未启用时不暗示任务已执行；同范围
  pending/running 返回 409。计划更新、扩展上传、HTTP 导入均管理员限定；访客只读。
  数据只读/暂存/XLSX/公式与 HTTPS 安全测试、编译和安全扫描通过。

## BitPro-first Wave 4：运行证据链完整验收（2026-08-23）

- Signal → order/trade/risk/alert → Monitor → Review 全部使用同一 `paper_instance_id` 与 source
  object ID；跨页 E2E 固定信号行 Paper ID 在 Monitor 中仍对应同一实例。
- `scripts/check.sh` 已纳入信号、盯盘、监控、复盘和跨页 lineage。最终全量通过 57 个
  Python 测试、15 个 Shell/研究/主线/运行 E2E、类型、零告警 lint、生产构建、bundle
  budget、0 dependency vulnerabilities、diff whitespace 和安全扫描。
- 真实隔离浏览器验收四页 desktop/390px，console errors 0、页面级溢出 0；没有点击规则
  evaluate、信号/告警确认、复盘写动作或 Paper action，截图索引写入 Wave 4 capture。
- Paper 15/61/47/23/428/681 最终连续性无差异；sealed 复盘三表仍为 1/14/14。Wave 4
  未合并、推送或部署。下一步进入 Wave 5 数据、AI 与隐藏期货预留。

## BitPro-first Wave 4：A股交易日复盘（2026-08-23）

- 新增当前 `/api/review` dates/list/get/assemble/save/seal/object resolve；GET 对缺失日期返回
  missing 空态，对已有复盘只读 stored items/metrics，不隐式组装。
- 显式 assemble 只从市场/股票池/策略/风险/订单/成交/Paper 权益对象构造 source ID、route、
  evidence hash；save/seal 管理员限定，PostgreSQL trigger 保证 sealed 父子证据不可修改。
- BitPro 复盘页适配为 A股交易日 Snapshot、量化指标、复盘结论/次日计划和证据时间线；
  sealed 输入只读，missing 日期明确提供显式组装入口。
- 真实读取既有 `2025-01-02` sealed 复盘：14 items、14 metrics；页面前后 daily review
  三表保持 1/14/14，HTTP 写请求 0、console errors 0、390px 无溢出，Paper continuity 通过。

## BitPro-first Wave 4：Paper 证据监控台（2026-08-23）

- 新增当前 `/api/monitor/summary|strategies|data|risk|notifications`，基于 PostgreSQL 最新
  health snapshots、Paper heartbeat/cycle/equity/ledger difference、alerts 和 deliveries。
- Monitor ViewModel 明确分开 `lifecycle_status` 与 `health_state`；真实 14 个 running 实例中
  stale/exhausted 等健康判断只影响 overall health，不写回 Paper 生命周期。
- BitPro 监控页恢复整体 KPI、服务健康、策略健康表、数据状态、风险告警和通知；缺失证据
  显示 missing/`—`，响应生成时间不覆盖证据时间，无真实账户或交易所连接字段。
- API/健康分离测试、Mock E2E、类型/lint 和真实隔离页通过。真实页面展示 15 行策略健康，
  API 200、console errors 0、390px 无页面级溢出；Paper continuity 无差异。

## BitPro-first Wave 4：信号中心与证据盯盘（2026-08-23）

- `/signals` 已接入 79 条真实信号和 97 条 alert/投递证据，保留 BitPro 高密度 KPI、筛选、
  审计表和详情抽屉；每行携带 signal/strategy/Paper ID，管理员只可确认 new 信号。
- `/watch` 已接入 15 个 Paper、79 信号、61 订单、47 成交和 93 个活动告警，按策略信号、
  订单与成交、图表联动、规则、告警五个标签组织；没有买入、卖出或下单按钮。
- 规则 preview 与 evaluate 分离，评估确认文案明确“只生成告警，不下单、不改 Paper”；真实
  验收没有点击评估。访客不显示评估入口。
- Mock 职责 E2E、类型、零告警 lint、生产构建通过。真实桌面/390px 页面 API 200、console
  errors 0、无横向溢出，截图人工检查通过；最终 Paper continuity 无差异。

## BitPro-first Wave 4：当前信号与 Alert-only 盯盘 API（2026-08-23）

- 新增唯一当前 `/api/signals*` 与 `/api/watch/*`，覆盖信号目录/详情/确认、统一运行上下文、
  告警确认、规则目录/创建新版本/preview/evaluate；没有旧路由或实盘执行端点。
- 恢复 strategy/indicator/price/abnormal 四类规则及字段/操作符 allowlist。规则更新只创建
  新版本；preview 零写入；evaluate 只允许幂等新增 alert 与 in_app delivery，响应强制
  `orders_created=0`，并保留命中 signal 的 Paper ID。
- 信号确认只把 `new` 更新为 `confirmed` 并保留 payload/evidence/source/Paper lineage；访客
  只能读取，信号/告警确认、规则创建/版本和 evaluate 均为管理员动作。
- 真实隔离库读取 79 个信号和 1 条非系统最新规则，preview `writes_performed=false`；没有在
  真实库执行 evaluate。API/同源链测试、安全扫描和 Paper continuity 全部通过。

## BitPro-first Wave 4：统一 PostgreSQL 运行证据模型（2026-08-23）

- 新增 Operations domain、`PostgresOperationsRepository` 和 `OperationsApplicationService`，
  直接复用 Paper 账本聚合，统一 signal/order/trade/position/risk/runtime event/alert 的
  `paper_instance_id` 与 source ID，不建立第二套运行事实。
- 真实隔离库 audit 视图读取 15 实例、79 信号、61 订单、47 成交、23 持仓，以及各最多
  200 条风险/运行事件和 97 条告警；scope=business 继续排除 acceptance/seed 证据。
- 公共 Signal/Alert ViewModel 删除历史 API/迁移字段；读取不恢复、不推进、不确认、不写告警。
  同源链回归测试、安全扫描和 Paper 15/61/47/23/428/681 连续性通过。

## BitPro-first Wave 3：策略 → 回测 → 模拟主线验收（2026-08-23）

- 新增跨页 E2E 固定“策略卡 → 回测控制台 → 仅模拟 Paper”为唯一执行主线；导航继续不注册
  实盘、链上、ARC、套利或期货，公共路由继续只使用当前 `/api/*`。
- `scripts/check.sh` 纳入策略、回测、Paper 和主线测试。最终全量通过 53 个 Python 测试、
  11 个 Shell/研究/主线 Playwright、TypeScript、零告警 lint、生产构建、bundle budget、
  0 个生产依赖漏洞、diff whitespace 和五类安全扫描。
- 内联完成提交前审阅并修复两个重要边界：create/lifecycle 响应统一补充当前 Paper ViewModel，
  避免操作成功后详情崩溃；回测晋级候选读取失败时不再阻断历史 Paper 账本展示。新增后端
  回归测试和前端降级 E2E，最终门禁重新全量通过。
- 真实隔离库只读打开策略、回测、Paper 列表与详情，截图索引写入
  `docs/screenshots/rebuild-wave-3-capture.json`；15/61/47/23/428/681 连续性最终无差异。
- Wave 3 没有执行 Paper advance/recover/reset，没有生命周期写操作，没有 Provider 调用，
  没有合并、推送或部署。下一步进入 Wave 4 的盯盘、信号、监控、复盘辅助工作区。

## BitPro-first Wave 3：A股模拟盘控制台（2026-08-23）

- `/paper` 已从适配空态切换为 BitPro 高密度 InstanceDashboard：15 个历史实例卡片、状态
  分段、名称/ID 搜索、权益/收益/PnL/成交/持仓/心跳和管理员创建入口。
- 详情按连续操作台组织账户曲线、当前持仓、成交与事件、风控状态、诊断日志和固定输入；
  证券代码转换为标准 A股展示，人民币和 100 股/T+1/只做多语义明确，无数字资产字段。
- 创建向导只列出 full + paper_eligible 回测并传递全部封存 lineage；生命周期 start/pause/
  resume/stop 使用确认弹窗，访客不渲染写按钮。真实验收只读，未触发生命周期动作。
- Mock E2E 覆盖 15 卡、详情五区、禁用币圈字段和暂停确认；类型、零告警 lint 通过。
  真实隔离库桌面/390px 显示 15 卡、14 running / 1 stopped、47 成交、23 持仓；详情五区
  可见，console errors 0、无横向溢出，截图人工检查通过。
- 真实页面验收前后的 Paper continuity 保持 15/61/47/23/428/681；页面轮询仅 GET，未
  recover、advance、configure、clear、archive 或 reset。

## BitPro-first Wave 3：PostgreSQL Paper 当前 API（2026-08-23）

- 恢复现有 Paper 状态机、固定输入、exactly-once cycle、风险、订单、成交、现金账本、持仓、
  净值与事件语义；新增 `PostgresPaperRepository`、`PaperApplicationService` 和唯一当前
  `/api/paper/*`，没有旧版本入口或实盘路由。
- GET 列表、详情、事件和 K 线只读，不隐式 recover/advance；创建、推进和 start/pause/resume/
  stop 都要求管理员且只作用显式实例 ID。公共 ViewModel 删除旧 API/迁移字段，缺失指标保持
  null；没有净值快照时只使用 Portfolio 账本明确记录的现金。
- 完整审计视图显示全部 15 个历史实例；`scope=business` 过滤 3 条 acceptance 记录后显示
  12 个用户实例。真实详情读取成功，当前状态为 14 running / 1 stopped。
- 连续性校验在真实读取前后均通过：15 实例、61 订单、47 成交、23 持仓、428 净值点、
  681 事件及逐实例 lineage/首尾权益均未回退。安全扫描五类活动风险保持 0，聚焦测试通过。
- 隔离库补齐既有 `stockpro_app` 角色对 `stockpro_bitpro_rebase_dev` 的表/序列权限，解决只读
  manifest 无权访问 `schema_migrations`；源库和生产库未修改。本地通过 SSH 隧道连接隔离库。

## BitPro-first Wave 3：当前不可变策略合同（2026-08-23）

- 恢复 StockPro AST allowlist、隔离 worker、运行限额、validation/replay/intents/custom records
  与不可变 `strategy_versions`；`app.domain.strategy` 改为显式无副作用入口，不加载 SQLite。
- 新增 `PostgresStrategyRepository`、`StrategyApplicationService` 和当前 `/api/strategies*`，
  覆盖目录、详情、子版本、代码验证和 quick-run。公共 response 删除 API 版本/迁移命名；
  历史合同字段仅在 `include_audit=true` 的只读 metadata 中出现，禁止更新。
- quick-run 强制 `promotion_status=not_evaluated`，不能生成 Paper 晋级资格；创建/子版本/quick
  run 管理员限定，验证使用同一 AST 语义。
- 真实隔离库读取 63 个策略目录项、67 个不可变版本；默认详情无历史合同字段，审计详情
  可读，当前代码验证通过且不返回 api_version。六张策略/Paper 表前后计数不变，Provider
  imports 0；15 项合同/安全测试通过。

## BitPro-first Wave 3：策略中心（2026-08-23）

- 用当前 PostgreSQL 策略目录替换导入 Crypto Strategy 页面，保留 BitPro 卡片密度、搜索、
  状态筛选、12 条分页、详情抽屉、代码验证、子版本和回测入口。
- 详情明确 CN_A_SHARE、T+1、100股、只做多，以及 pool/factor/dataset/cost 封存输入；
  未绑定显示“未绑定”，不从当前页面补写 lineage。quick-run/代码有效不可晋级提示常驻。
- Mock E2E、类型/lint/build通过。真实隔离库首屏 12 卡、63 个目录项，抽屉展示实际
  `A股多股动量模板` 与当前代码状态；桌面/390px console errors 0、六张策略/Paper 表
  业务写入 0，截图人工检查通过。

## BitPro-first Wave 3：A股回测证据 API（2026-08-23）

- 恢复 A股日线撮合、T+1、整手、涨跌停、停牌、成本、容量、无未来数据、完整研究协议、
  异步 job、matrix 和 Walk-forward 服务；Reference service 改为明确运行时延迟加载，GET
  不导入/调用 Provider。
- 新增 `PostgresBacktestRepository`、`BacktestApplicationService` 与当前 `/api/backtest/*`，
  覆盖 configuration、79 个历史 runs、metrics/series/orders/trades/positions/logs、compare、
  35 个 jobs、cancel/retry、matrix 和 Walk-forward。
- 公共 configuration 移除 strategy API/migration 版本命名；quick 强制 not_evaluated，matrix
  全 cells 强制 not_evaluated，Walk-forward folds 强制 promotion_eligible=false；full 保留完整
  promotion checks。
- 真实隔离库读取 79 runs 与 35 jobs，八张 backtest/Paper 表前后计数不变，Provider imports 0、
  public version names 0；当前无 active job 时 recovery 返回 0，jobs/runs 状态分布前后相同；
  回测门控测试与安全扫描通过。

## BitPro-first Wave 3：回测控制台（2026-08-23）

- 用 A股 Evidence Workbench 替换导入 Crypto Backtest 页面，保留 BitPro KPI、历史表、状态
  筛选、任务队列、创建向导、详情按需 tab、matrix 与 Walk-forward 入口。
- 创建向导明确 strategy/dataset/universe/cost 必选，pool/factor/protocol 显式绑定；常驻显示
  T+1、100股、只做多、快速预检不可晋级。页面打开不创建 job/run。
- 真实隔离库页面显示 79 runs、76 success、50 full、35 jobs；桌面历史表与 390px 向导
  console errors 0，七张 backtest/Paper 表前后不变。Mock E2E、类型/lint/build通过，
  截图人工检查通过。

## BitPro-first Wave 2：传统金融研究模型（2026-08-23）

- 新增不可变 `InstrumentContract`，当前支持 stock/ETF/index，并为 future 保留乘数、保证金、
  到期、最后交易日和结算字段；A股股票默认 CN/SSE-SZSE 语义、CNY、100 股手数、
  `CN_A_SHARE` 日历且不可卖空，期货字段保持 `null`。
- 新增首页、证券详情、股票池和因子稳定 ViewModel；市场总览固定包含 indices、breadth、
  turnover、limit_ecology、sector_flows、来源、更新时间、交易日和 data_status，缺失块保持
  `None/null`。
- 前后端研究类型统一使用当前 API 的 snake_case 字段，不建立 camelCase/旧字段双合同。
  三项领域测试、前端类型检查与安全扫描通过。

## BitPro-first Wave 2：A股市场当前 API（2026-08-23）

- 新增 `ResearchApplicationService` 与当前 `/api/market/*`：overview、证券搜索/详情、日线、
  分时、盘口和自选。删除临时 workspace overview，`/stocks/*` 与带版本号路径继续 404。
- `PostgresRepository` 只读组合 `market_indices_realtime`、`all_stocks_realtime`、最新 published
  market evidence/metrics、sector evidence 与 `stock_history`；搜索集中规范化 SH/SZ/BJ、
  股票/ETF/指数、tick size、lot size 和统一 `600519.SH` 形式。
- 分时和盘口在隔离库没有缓存时返回 `data_status=empty`、空数组、null 来源和明确原因，
  不合成价格。自选写入只保存 owner、规范化 symbol 和 note，不复制 price。
- 真实隔离库验收读取 4 个指数、上涨 2505、涨停 54 和贵州茅台 `600519.SH`；日线读取
  PostgreSQL，分时/盘口诚实空态，自选为空。九张市场/Paper 表前后计数一致，业务写入 0，
  进程未导入 TuShare/AKShare。聚焦 API/只读/安全测试 18 项与前端类型检查通过。

## BitPro-first Wave 2：真实 A股首页（2026-08-23）

- 直接保留 BitPro Home 的 `Market Command` 操作台节奏，把 Crypto 市场面板替换为五个
  A股模块：主要指数、市场宽度、涨停生态、板块资金和策略→回测→模拟主线状态。
- 首页只调用 `/api/market/overview`；Loading/error/empty/partial/stale/fresh 独立呈现，
  Decimal 使用字符串合同并由展示层显式验证转换，null 显示 `—`。真实环境曾暴露 Mock
  number 掩盖的 `toFixed` 错误，现已用字符串 fixture 锁定真实 API 形状。
- 真实隔离库桌面/390px 验收展示 4 个指数、上涨 2,505、下跌 2,860、涨停 54、跌停 13、
  最高板 3、交易日 2026-08-21 和 `partial`；sector evidence 为空时保持板块资金不可用。
- Mock 首页 2 项 E2E、类型、lint、构建通过；真实桌面/窄屏无横向溢出、console errors 0，
  页面无 BTC、ETH、资金费率、永续或数字资产控制。

## BitPro-first Wave 2：A股行情终端（2026-08-23）

- 用 A股终端替换导入的 Crypto Market：保留 BitPro 顶部工具区、搜索弹层、行情概览、
  K线、盘口、自选和证据 tabs；全部/股票/ETF/指数筛选与 symbol/tab 均写入 URL。
- 证券搜索支持代码/名称、键盘上下/Enter/Escape；详情显示规范化 symbol、asset class、
  100股 lot、CNY、tick size 与 freshness。KlineChart 对 A股显示股/CNY 单位，不再使用
  USDT；OrderBook 标题使用 CNY/委托股数。
- 自选组件只提交 symbol/note；指数禁止加入。日线、分时、盘口分别绑定当前 API，缺失
  分时/盘口保持明确空态，不由 close 或随机深度补齐。
- Mock E2E 与构建通过。真实隔离库 `600519.SH` 显示贵州茅台、1,272.96、3 根真实日线、
  stale 行情、盘口 empty 和 PostgreSQL 证据；桌面/390px、console errors 0，截图人工检查通过。

## BitPro-first Wave 2：不可变股票池（2026-08-23）

- 恢复 StockPro `StockPoolService` 的规则版本、封存输入绑定、成员 evidence/hash、generation
  与 snapshot 语义；Factor/Reference/Provider 依赖改为显式生成动作时延迟加载，应用启动和
  页面 GET 不导入 TuShare/AKShare。
- 新增当前 pools API 和 `PostgresPoolRepository`；创建、生成、封存要求管理员，目录、详情、
  members 与 snapshots 可读。不存在 v2 路径或旧 Router。
- 股票池页面保留 BitPro 目录/详情双栏与高密度证据表，包含规则 config、显式生成绑定表单、
  成员与 evidence hash、sealed manifest；页面加载不自动生成或封存。
- 真实隔离库读取 6 个池、6 个 generation、68 个成员和 5 个 sealed snapshot，六张表前后
  计数不变、Provider imports 0。真实 immutability trigger 拒绝 sealed snapshot 更新并回滚。
- API/安全聚焦测试、Mock E2E、类型/lint/build通过；真实桌面/390px console errors 0、
  业务写入 0，截图人工检查通过。

## BitPro-first Wave 2：PostgreSQL 因子库（2026-08-23）

- 新增 `PostgresFactorRepository` 和当前 factors API，覆盖目录、版本/校验/计算、metrics、
  values、runs、correlations、snapshots 与 snapshot values；写动作管理员限定。
- 重构 `FactorResearchService`：证券代码与交易日规范化留在因子模块，Reference service 仅在
  明确封存输入动作时延迟加载；读取目录/指标不导入 TuShare/AKShare。旧 provider/SQLite
  `factor_sync_service` 未进入当前运行面。
- FactorLab 页面保留 BitPro 目录/详情、KPI、指标诊断、运行、相关性、快照和值浏览，计算
  表单要求显式 dataset/universe snapshot；exploratory 与代码 valid 不显示为“已验证”。
- 真实隔离库读取 100 因子、100 runs、3 snapshots、55 correlations；选中
  `dollar_volume_20d`，pending metrics 224。八张因子表前后计数不变、Provider imports 0。
- API/只读/安全测试、Mock E2E、类型/lint/build通过；真实桌面/390px console errors 0、
  业务写入 0，截图人工检查通过。

## BitPro-first Wave 2：研究工作区完整验收（2026-08-23）

- 首页、行情、股票池和因子全部从 `UnavailableWorkspace` 替换为 BitPro 高密度操作台，
  统一经当前 `/api/*` → Application/Repository → `stockpro_bitpro_rebase_dev`；GET 不写库、
  不调用 Provider，不存在币圈入口或版本化 API。
- 统一 `scripts/check.sh` 已加入 shell + home + market + stock pool + factor lab Mock 矩阵；
  页面各自覆盖桌面和 390px，无横向溢出、console error 或 mock/真实形状漂移。
- 真实只读验收覆盖 market 9 张、pool 6 张、factor 8 张业务表，页面/API 前后计数不变；
  sealed pool trigger 保持不可变，因子 pending 保持 null，分时/盘口/板块证据缺失保持 empty。
- 截图索引写入 `docs/screenshots/rebuild-wave-2-capture.json`，明确这些是本地隔离证据、
  不是生产截图；图片本身留在 Git 忽略目录。
- 安全扫描五类计数全 0，Paper manifest 继续通过。Wave 2 未启动 Provider、scheduler、
  Paper recovery 或策略 worker，未创建验收业务记录。
- 最终统一入口通过 45 项 Python 测试、前端类型、0 lint warning/error、生产构建、bundle
  budget、0 dependency vulnerabilities 和 7/7 Shell/研究 E2E；安全隔离遗留文件 56 个，
  全部不在当前可达面。

## 重建基线 SHA 现场纠正（2026-08-22）

- Wave 1 开始前验证发现设计草稿中的 `bff8e05…` 不是当前仓库的 Git 对象，不能作为
  PostgreSQL 基础文件的恢复来源。现场证据确认设计提交 `e204e9f` 的父提交、`main`
  和 `origin/main` 均为 `99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440`。
- 合同、总控计划、Wave 1 恢复命令和 Wave 6 回滚演练已统一固定到真实 SHA
  `99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440`；设计/计划提交分别固定为
  `e204e9f41a9df26a0aefd77a7a6079a86265a234` 和
  `27f53cead43557760f5ce74ffc2a598078f9fcfa`。本修正不涉及代码、数据库或运行服务。

## BitPro-first Wave 1：A股 PostgreSQL 运行依赖收敛（2026-08-22）

- 后端运行依赖已从 BitPro 的 requirements-base/Kairos 链脱离，移除 ccxt、aiosqlite、
  Kairos 与 torch；保留 FastAPI、PostgreSQL、TuShare、AKShare、Backtrader、APScheduler、
  HTTP、Agent 和验证依赖。隔离 venv 安装通过。
- `Settings` 现在强制 `DATABASE_URL` 存在且为 PostgreSQL，运行模式固定为
  `ashare_paper`；Provider fetch、scheduler、Paper recovery、私有交易所、币圈后台任务
  和实盘默认全部关闭。缺失 URL 或 SQLite URL 的配置测试均硬失败。
- 前端保留导入的 React/Vite/Router 版本与根目录 `@bitpro/ui` 包，新增 TypeScript 检查、
  Playwright mock/real 脚本和 bundle budget；lockfile 不包含工作区外绝对路径。
- `app.core` 不再在包导入时实例化配置或加载 BitPro error 模块，静态安全扫描无需数据库
  凭据。当前 21 项 rebuild 测试、类型检查、零 warning lint、生产构建、bundle budget
  和五类安全扫描通过；没有启动长运行服务。

## BitPro-first Wave 1：唯一当前 API Router（2026-08-22）

- 后端已建立 `create_api_router(context)`，当前只注册 `/api/health` 与
  `/api/health/storage`；OpenAPI 恢复标准 `/openapi.json`，所有路径均无版本号。
- `/api/health/storage` 支持注入 Repository context；Repository 尚未接入时诚实返回
  PostgreSQL `unconfigured`，不尝试连接、不执行迁移、不回退 SQLite。
- 已删除导入的 `backend/app/api/v2/` 26 个 Router 文件和直接依赖 SQLite 的旧
  `backend/app/api/public.py`。没有 redirect、alias 或兼容入口；旧路径测试明确返回 404。
- 当前 API Router 与安全门禁 12 项测试通过，当前入口/API/client/App 静态扫描没有
  `app.api.v2`、`api_router_v2` 或版本化 API 字符串，五类安全计数继续全 0。

## BitPro-first Wave 1：PostgreSQL Repository 与隔离数据库（2026-08-23）

- 已从真实 StockPro 基线 `99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440` 精确恢复
  `PostgresDatabase`、migration runner 和 37 个迁移文件；未恢复旧 API、Service 或页面。
- 新增分域 Repository Protocol、`PostgresRepository.storage_health()` 与 `AppContext`。
  当前 Repository 只用 `SELECT` 读取迁移数，不向页面暴露通用 SQL，也不自动运行迁移。
- 经用户继续授权后，通过 `ssh stockpro` 的 PostgreSQL 管理员路径创建专用数据库
  `stockpro_bitpro_rebase_dev`，从 `stockpro_dev` 做服务器本机一致性逻辑复制。源库未写入，
  目标业务表、分区、索引、序列和非扩展函数已归现有应用账号管理。
- 隔离库对账为 37 个迁移、67 个策略版本、79 个回测、15 个 Paper 实例、61 个订单、
  47 个成交、23 个持仓、428 个权益快照、681 个事件和 1 份复盘；Paper manifest 连续性
  回验通过。真实 `/api/health/storage` 返回 PostgreSQL `healthy`、37/37、无写入。
- Repository/Router/安全门禁 14 项聚焦测试通过；安全扫描把 AppContext、Repository 和
  PostgreSQL 文件纳入真实可达面后，五类阻断计数仍为 0。

## BitPro-first Wave 1：PostgreSQL 当前认证合同（2026-08-23）

- 新增唯一 `/api/auth/admin/login`、`/api/auth/guest/login`、`/api/auth/me` 和
  `/api/auth/logout`。管理员使用环境密钥与常量时间比较；Bearer token 使用 HMAC-SHA256
  签名、有效期和随机 session ID，同时下发 HttpOnly、SameSite=Strict Cookie。
- 访客邀请码只以 SHA-256 查询 PostgreSQL，token 不包含明文邀请码；每次解析按 code ID
  复核未撤销和有效期。登录成功/失败写 `auth_audit_events`，事件不包含密码、邀请码或 token。
- 当前业务 Router 统一使用 `require_authenticated`；未登录访问
  `/api/market/overview` 返回 401。登录按来源 IP 在进程内限制为 15 分钟 10 次失败，超过
  返回 429；API 输入有明确长度上限，错误信息不区分账号或密码。
- 修复 `app.domain` 与 `app.services` 根包的 BitPro 隐式导入副作用，认证加载不再触发
  funding、交易所、ccxt 或 SQLite。对应 auth domain/service/core 全部加入安全可达面扫描。
- 真实隔离库管理员登录、Cookie 会话、`/api/auth/me`、退出与一条审计追加通过；前端
  AuthProvider 显式丢弃响应 token，不写 localStorage/sessionStorage。聚焦测试 20 项通过。
- 供应链非强制升级到 Axios 1.19、ECharts 6.1 和 React Router 7.18 后，生产依赖
  `npm audit --omit=dev` 为 0 vulnerability；TypeScript、构建和 lint 通过。
- 安全待办：此前终端诊断曾暴露数据库连接串，相关数据库账号必须在任何 push、部署或
  对外共享前轮换；本切片未擅自修改原 StockPro/生产凭据。

## BitPro-first Wave 1：BitPro A股操作台骨架（2026-08-23）

- 把内联空态抽为 `UnavailableWorkspace`，所有尚未适配工作区统一显示 Owner route、
  未注册业务服务、PostgreSQL 数据边界和“正在接入 A股 PostgreSQL 数据”；页面不发业务
  请求、不展示 mock 行情，也不启动 Provider、策略或 Paper recovery。
- MainLayout 保持常驻，当前导航完整包含首页、行情、股票池、因子、策略、回测、模拟、
  盯盘、信号、监控、复盘、数据和 AI研发；不注册实盘、链上、ARC、套利或期货。
  `/paper` 是唯一模拟入口，因子统一为 `/factors`。
- 前端导出唯一 `apiClient`，base URL 为 `/api`；Vite 默认端口/代理恢复为 4444→4445，
  Playwright 使用隔离 4454 端口，避免误测原 StockPro 进程。
- Shell E2E 在桌面与 390×844 窄屏各通过一项：侧栏跨路由保持同一 DOM、批准导航可见、
  禁止入口不存在、窄屏无横向溢出。实际截图已人工检查，保持 BitPro 紧凑暗色层级与诚实空态。

## BitPro-first Wave 1：完整验收（2026-08-23）

- `scripts/check.sh` 现在强制拒绝非 `stockpro_bitpro_rebase_dev` URL，并按固定顺序执行
  安全扫描、Python 编译、当前后端/rebuild 测试、前端冻结安装、类型、lint、生产构建、
  bundle budget、生产依赖审计、Mock Shell E2E 和 whitespace 检查。
- 全量入口通过：34 项 Python 测试、前端 0 lint warning/error、生产构建、首屏 306.6 KiB
  raw / 97.4 KiB gzip、0 dependency vulnerabilities、2 项桌面/窄屏 E2E 全绿；五类
  安全阻断计数全部为 0，56 个遗留文件保持不可达隔离。
- 修复旧环境 CORS 的非 JSON 列表兼容：使用 Pydantic `NoDecode` 后由字段 allowlist 解析，
  仍只接受配置的明确 origin；缺失/非 PostgreSQL DATABASE_URL 继续 fail-fast。
- 4444/4445 已完成隔离 worktree 的干净重启：前端 cwd 指向 worktree frontend，后端 cwd
  指向 worktree backend，后端只连接隔离库；健康为 rebuild-safe，存储为 PostgreSQL 37/37。
- 真实浏览器链路通过管理员登录 → HttpOnly session → MainLayout → 退出，console errors 为 0；
  登录页和 HTML title 已全部改为 StockPro/A股文案。桌面登录页与真实 shell 截图已人工检查。
- Paper manifest 再次通过，策略版本、回测、15 个 Paper 实例、订单、成交、持仓、权益
  曲线和事件均未回退。Wave 1 没有启动 Provider、scheduler、Paper recovery 或策略 worker。
- 新建长期页面事实入口 `docs/pages/登录门禁.md` 和 `docs/pages/首页.md`；二者明确区分
  Wave 1 shell 证据与 Wave 2 尚未完成的真实首页业务。

## BitPro-first Wave 0：隔离基线门禁完成（2026-08-22）

- 已从计划提交 `27f53ce` 创建独立 worktree
  `/Users/jie.feng/Dev/Github/Private/StockPro-bitpro-a-share` 和分支
  `codex/bitpro-a-share-rebase`；原 StockPro 工作区、`main` 与生产均未改动。
- 隔离环境基线检查通过：前端生产构建和 bundle budget 通过，lint 为 0 error（保留
  既有 Fast Refresh warning），后端 424 项测试与 Python 编译通过。
- 新增只读 PostgreSQL/Paper 连续性采集与校验器。连接强制启用只读事务，只接受
  `SELECT`；基线清单使用规范化 SHA-256 防篡改，并对 Paper 计数下降和实例 ID 丢失
  执行硬失败。
- 当前本地基线已写入 Git 忽略目录 `.codex-artifacts/rebuild/baseline.json`：37 个迁移、
  67 个策略版本、79 个回测、15 个 Paper 实例、61 个 Paper 订单、47 个 Paper 成交、
  23 个 Paper 持仓、428 个权益快照、681 个运行事件；清单哈希为
  `3646d2181a72907520e5b7ba820b39c2fe62a8cb2a5e2e3fd8158073a7a110f2`。
- 基线工具 5 项测试和真实数据库即时回验通过。下一步只验证 BitPro 固定提交来源，
  尚未导入 BitPro 应用代码，也未启动任何服务、worker 或调度器。
- BitPro 来源验证门禁已通过：只从 Git 对象库解析完整提交
  `00517963e90f463e608289b0277fe598bd82d9bf`，并确认该提交包含 frontend、backend、
  packages、scripts 和 tests 五个应用根。当前 BitPro 脏工作区、`.env` 和根治理文件
  均不属于导入来源；来源验证 2 项测试通过。
- 已通过 allowlist 导入工具把固定 BitPro 提交的 backend、frontend、packages、scripts
  和 tests 五个应用根机械同步到隔离分支，并把页面设计、截图和产品手册复制到
  `docs/reference/bitpro-baseline/`；共形成 888 个固定来源路径的纯导入快照。
- 导入前后的 AGENTS、LICENSE、`.github`、deploy、StockPro 合同、规格与进度文件保持
  不变；暂存检查未发现 `.env`、虚拟环境、node_modules、数据库或日志。BitPro 来源本身
  的既有行尾空格保留在纯导入提交中，后续只在实际适配文件上清理。
- 导入工具提交为 `4a07b41`，固定应用快照提交为 `f84fc53`。截至此处没有启动
  uvicorn、Vite、scheduler、Provider、Paper recovery 或策略 worker；应用尚不具备
  安全启动条件，下一步必须先完成数字资产、SQLite 和带版本号 API 静态封锁。
- 第一启动前安全封锁已完成。当前后端入口只注册 `/api/health` 与 `/api/auth/me`，
  OpenAPI 位于 `/api/openapi.json`；前端 API 与 WebSocket 基址均已切换到唯一当前
  `/api/*` 合同，不保留 `/api/v1`、`/api/v2` 或公共版本化入口。
- 配置默认关闭私有交易所、币圈后台任务和实盘，数据库后端固定为 PostgreSQL。
  启动入口不导入 SQLite、交易所、策略引擎、scheduler、实时行情或 BitPro Router。
- 前端保留首页、行情、策略、回测、模拟、盯盘、信号、监控、复盘、数据、因子和
  AI研发导航；实盘、链上、套利和 ARC 不注册。所有当前页面均为真实的 A股适配空态，
  不读取旧币圈模块、不显示 mock 行情，也不暗示 Paper 已恢复运行。
- 安全门禁 8 项测试通过；全树扫描五类可达阻断计数均为 0，69 个 BitPro 遗留文件
  仅计为不可达来源。前端生产构建与零 warning lint 通过，17 项 rebuild 测试、Python
  编译和真实 PostgreSQL 连续性回验通过；整个 Wave 仍未启动任何长运行服务。
- Wave 0 最终审计通过：基线 manifest hash 为
  `3646d2181a72907520e5b7ba820b39c2fe62a8cb2a5e2e3fd8158073a7a110f2`，导入
  manifest 文件 SHA-256 为 `d47948eb5ccc235100a16f37d3680ef3bd744b7c26d9d6ca2dbd5c9d38a94c57`，
  安全报告文件 SHA-256 为 `dabbdd279750f4108257f658de224f6412b4f6e97f2090706d35a503c681e427`。
- 原 StockPro 工作区仍在 `codex/bitpro-a-share-rebuild-design`，用户既有未跟踪工具目录
  保持原状；`main` 与 `origin/main` 均为
  `99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440`。4444/4445 的既有进程 cwd 指向原
  StockPro frontend/backend，不属于重建 worktree；本 Wave 没有启动、重启或接管它们。
- Wave 0 提交链为 `dd5b1ba`（连续性基线）、`911553f`（固定来源）、`4a07b41`
  （导入工具）、`f84fc53`（纯应用快照）、`9ae2869`（导入记录）和 `5a7056b`
  （fail-closed 安全封锁）。未推送、未合并、未部署；Wave 1 开始前必须再次执行安全扫描。

## BitPro-first A股整仓重建设计获批（2026-08-22）

- 用户批准采用 BitPro-first B2 路线：从 BitPro 固定提交
  `00517963e90f463e608289b0277fe598bd82d9bf` 导入完整应用底座，在任何服务启动前隔离
  数字资产实盘、私有 API、策略 seed、SQLite 和后台任务，再接入 StockPro PostgreSQL
  与 A股领域。
- 用户批准恢复 BitPro 完整操作台导航：行情、股票池、因子、策略、回测、模拟、盯盘、
  信号、监控、复盘、数据和 AI研发；期货与套利预留但隐藏，链上和 ARC 不进入产品。
- 用户批准唯一当前 API 原则：只提供 `/api/*`，不保留带版本号路径、旧入口、兼容
  Router 或长期双合同；历史版本字段只作为旧记录审计元数据。
- 当前 PostgreSQL 对账基线为 37 个迁移、67 个策略版本、79 个回测、15 个 Paper 实例、
  61 个 Paper 订单、47 个 Paper 成交、23 个持仓、428 个权益快照、681 个运行事件和
  1 份复盘。任何迁移切片无法证明这些记录连续时必须停止。
- 正式设计写入 `docs/contracts/active-bitpro-first-a-share-rebuild.md`。当前仅完成设计，
  尚未创建重建 worktree、复制 BitPro 源码、修改数据库或触发部署。
- 实施工作拆分为总控计划和 Wave 0–6 七个详细计划，位于
  `docs/superpowers/plans/2026-08-22-bitpro-*.md`。每个任务包含明确文件、接口、
  失败测试、通过条件和提交边界；由于 BitPro 规则禁止子代理，执行方式固定为当前会话
  使用 `executing-plans` 内联推进。

## Operator capability fusion final acceptance (2026-08-20)

- Completed all eight contract phases while preserving Strategy → Backtest →
  Paper as the only product mainline. Supporting capabilities have one Owner:
  Market owns indices/watchlist/depth, Watch owns alert-only rules, Data owns
  isolated exchange, and Dashboard/Paper link to the existing Review owner.
- Final verification passed 62/62 Mock browser tests, 424 backend tests,
  production build/bundle budget/Python compilation, focused real local flows
  and four production read-only browser smokes. The only lint output is the
  pre-existing Fast Refresh warning in `ResearchDeskContext.tsx` (zero errors).
- Production is deployed at SHA `1689c65e7542124adbd2b8b7e36d20feb16922f5`
  through Actions run `32377373771`; backend and Nginx are active, internal and
  public health pass, and PostgreSQL migrations are 37/37.
- Production truthfully has zero Watch rules, zero watchlist entries and zero
  staged extension imports. Its first-run checklist is action-required 2/4:
  admin security and PostgreSQL are ready; TuShare and sealed snapshots are not
  configured. No production fixtures were created to make the UI look ready.
- Local Paper continuity remained 15 instances / 24 orders / 18 trades / 7
  positions / 128 equity snapshots / 310 events. Existing unrelated untracked
  tool directories and `frontend/scripts/qa_visual_pass.mjs` remain untouched.
- ETF strategy/backtest/Paper semantics remain explicitly unsupported until a
  dedicated ETF dataset snapshot, Universe, cost model and Paper contract exist;
  no stock-only behavior is relabeled as ETF support.

## Fusion completion audit: Index and factor-owner corrections (2026-08-20)

- Requirement-by-requirement audit found two ownership gaps before completion:
  Market had a watchlist tab but index evidence existed only on Dashboard, and
  the factor-validation engine existed without a visible Backtest Owner entry.
- Added a Market `指数` tab that reuses the existing PostgreSQL market-overview
  cache, preserves state/source timestamp and leaves Dashboard as the summary.
  Added a Backtest `因子验证` action that routes to the existing Factor API UI;
  parameter matrix and persisted Walk-forward remain in Backtest.
- Mock acceptance now asserts eight Market workspaces, four index cards and the
  Backtest factor entry. No new index cache or factor engine was introduced.

## Review/Onboarding fusion: read-only readiness and unified review entry (2026-08-20)

- Added `/workflow/onboarding-readiness` as a read-only evidence endpoint. It
  separates required admin security, PostgreSQL migration, TuShare provider and
  sealed-snapshot readiness from later Strategy, Paper and Review progress.
  Every step links to its existing Owner page and reports
  `writes_performed=false`; it never syncs, migrates, repairs or creates data.
- Dashboard renders the first-run checklist and a unified Review link. Paper's
  operator header now exposes the same盘后复盘 route without moving review
  editing into the execution page or exposing Review as first-level navigation.
- Real local evidence reported 4/4 required steps ready with 37 migrations, 22
  dataset snapshots, 67 strategy versions, 15 Paper instances and one review;
  database counts were identical before and after the check. Real browser
  acceptance passed for the dashboard checklist and `/review` link.

## Data fusion: isolated CSV/JSON/XLSX exchange (2026-08-20)

- Added PostgreSQL `extension_data_imports` and `extension_data_records` as an
  isolated staging boundary. Uploads do not map into market, factor, strategy,
  backtest or Paper tables and can be explicitly deleted with cascading staged
  rows.
- CSV, object-array JSON and first-sheet XLSX share a 5MB / 10,000-row /
  200-column contract. Empty/duplicate headers and XLSX formulas fail before a
  database write. Every file and row receives a stable SHA-256 hash.
- Staged data exports to CSV, JSON or XLSX. Spreadsheet exports contain static
  values only, use Arial, a styled/frozen header and formula-injection escaping.
  The Data Owner page exposes upload, three exports, a staged-only status and a
  destructive-action confirmation; guests remain read-only.
- Real acceptance uploaded a two-column score CSV, read one staged row, exported
  all three formats, reopened XLSX as `代码|600519|1.2|Arial|0 formulas`, then
  deleted the import. Local migrations are 36/36 and Paper counts remained
  15 instances / 24 orders / 18 trades / 310 events.
- Added an explicit HTTPS connector with an exact-host allowlist, no redirects,
  public-DNS validation and the same 5MB parser limit. The default empty
  allowlist is visible in the UI and rejected `example.com` with HTTP 400 before
  any request. Source URLs are retained as staged provenance; migrations are
  now 37/37.

## Dashboard/Market fusion: PostgreSQL watchlist owner (2026-08-20)

- Audited existing ownership before adding UI: Dashboard already owns index,
  breadth, sentiment, turnover, limit ecology and sector-flow summaries; Market
  already owns sector/limit depth, news, calendar and stock research. The
  missing high-value reference capability was a persistent watchlist.
- Added `market_watchlist_entries` and Market APIs. Entries persist only owner,
  six-digit symbol and note; reads join `all_stocks_realtime` for name, price,
  change, amount, turnover, volume ratio, amplitude and quote timestamp. Empty
  reads never bootstrap a list.
- The new `自选` tab supports cached-stock search, explicit admin add, note
  update by idempotent upsert, refresh and delete. Guests remain read-only and
  missing quote evidence stays unavailable rather than retaining an add-time
  price.
- Real acceptance added and deleted `300308` (中际旭创), observed its existing
  cached quote and restored the list to an honest empty state. Local migrations
  are 35/35. Paper continuity remained 15 instances / 24 orders / 18 trades /
  7 positions / 128 equity snapshots / 310 events.

## Paper/Watch fusion: versioned alert-only watch rules (2026-08-20)

- Extended the existing `alert_rules`, `alerts` and `notification_deliveries`
  chain instead of adding a parallel signal engine. The additive migration
  stores a rule name, type, data purpose and last evaluation time while keeping
  all existing system rules and alert history intact.
- Added strategy-signal, indicator, price and abnormal-scan rules with strict
  field/operator allowlists, optional symbol scope and ALL/ANY evaluation.
  Updates create a new immutable version. Preview performs no writes; explicit
  evaluation can only append an alert and in-app delivery, and always reports
  `orders_created=0`.
- Watch now owns a `规则` workspace with an operator form, rule cards, separate
  preview/evaluate actions and a confirmation dialog that states the Paper and
  order boundary. Guests remain read-only through the existing client write
  guard. Cold Watch reads use a 30-second SSH-tunnel envelope rather than
  converting an 8-second connection wait into an empty rule list.
- Real acceptance created one acceptance-purpose price rule for `SH_688553`.
  Preview scanned 5,545 rows, matched one and wrote nothing; explicit evaluation
  created one alert and one in-app delivery with zero orders. Paper continuity
  remained 15 instances / 24 orders / 18 trades / 7 positions / 128 equity
  snapshots / 310 events before and after evaluation.
- TDD/API and browser evidence covers allowlists, ALL/ANY matching, data-purpose
  validation, CRUD/preview/evaluate contracts, Mock operator flow and a real
  PostgreSQL read-only preview. Local storage is healthy at 34/34 migrations.

## Backtest fusion: persisted asynchronous walk-forward execution (2026-08-20)

- Extended the existing `backtest_jobs` queue with `job_type=walk_forward` and
  a persisted JSON result; no parallel worker/queue was introduced. The schema
  migration is additive and local storage is healthy at 33/33 migrations.
- Each fold runs a capped training parameter grid (maximum 12 combinations and
  48 total diagnostic runs), selects the configured objective with direction-
  aware ordering, then executes the selected parameters on the immediately
  adjacent OOS window. Cancellation is checked before folds and inside every
  child BacktestWorkbench run.
- Walk-forward child runs use full-range A-share matching and evidence but carry
  `diagnostic_only=true`, no research protocol and a distinct input hash. They
  therefore skip protocol evaluation and Paper promotion entirely; ordinary
  full protocol runs retain the existing 11-gate path.
- The result persists fold windows, candidate/sub-run IDs, best parameters,
  IS/OOS objective values, OOS return, degradation, compounded OOS equity and
  consistency. Backtest task cards expose a dedicated OOS result dialog and
  state that an independent full protocol run is still required for Paper.
- Real bounded acceptance first rejected an incompatible factor snapshot before
  child-run creation. With pool snapshot 5 / factor snapshot 4 / dataset 10, a
  one-fold one-combination job completed successfully: OOS return 0.296%,
  consistency 100%, result version `walk-forward-execution.v1`. Its IS and OOS
  runs both ended `promotion_status=not_evaluated` with zero promotion checks.
- Real UI acceptance reads the persisted result. Run/job lists now share a
  30-second SSH-tunnel cold-read envelope; a 9-second delayed-list test failed
  before the fix and passes after it.
- Verification: local migration health 33/33; Mock browser suite 59/59; real
  bounded API and result-dialog acceptance passed; `./scripts/check.sh` passed
  production build, bundle budget, lint with the existing Fast Refresh warning
  only, 403 backend tests and Python compilation. Paper continuity remained 15
  instances / 18 trades / 7 positions / 128 equity snapshots / 310 events.

## Backtest fusion: sealed walk-forward fold preview (2026-08-20)

- Added a read-only `walk-forward-plan.v1` service and API. It reads distinct
  trading dates only from a sealed `daily_bars` snapshot, validates positive
  train/test/step lengths, and generates rolling folds whose OOS start is the
  next available trading day after the training end.
- The Backtest page exposes a dedicated preview dialog for snapshot, date range
  and train/test/step sessions. It renders every IS/OOS window and explicitly
  labels the result as not Paper-eligible; no optimizer, backtest run, protocol,
  database record or promotion evidence is created by preview.
- A real local preview over snapshot 23 used 486 available trading dates and
  produced 3 non-overlapping 252/63/63 folds. The endpoint returned the sealed
  dataset manifest hash and `promotion_eligible=false`.
- Real-browser acceptance exposed the ordinary 8-second configuration timeout;
  Backtest configuration now uses a 30-second SSH-tunnel cold-read envelope.
  A 9-second delayed configuration browser test failed before the change and
  passes after it.
- Production currently has zero sealed dataset snapshots. The preview action
  therefore renders a disabled `无封存快照` state with a clear prerequisite,
  while data-bearing environments keep the executable preview. Real E2E adapts
  to both truthful states instead of assuming production contains local fixtures.
- TDD: five fold/service contracts and two browser contracts cover insufficient
  ranges, unsealed snapshots, no-overlap semantics, rendering and cold reads.
- Verification: Mock browser suite 56/56; real API and browser preview passed;
  `./scripts/check.sh` passed the production build, bundle budget, lint with the
  existing Fast Refresh warning only, 397 backend tests and Python compilation.
  Paper continuity remained 15 instances / 18 trades / 7 positions / 128
  equity snapshots / 310 events.
- Empty-state follow-up verification raised the Mock suite to 57/57; the full
  repository check remains green with 397 backend tests. Production's zero-
  snapshot state is now directly covered, and local Paper continuity is
  unchanged.

## Strategy fusion: versioned AND/OR stock screening (2026-08-20)

- Extended the existing `screener` stock-pool rule instead of adding a parallel
  signal engine. Operators can combine open/high/low/close, volume, amount and
  percentage-change conditions with explicit ALL/AND or ANY/OR semantics.
- The service validates a strict field/operator allowlist, evaluates only the
  sealed selection-date bar and persists the normalized logic plus matched
  conditions in each member's evidence. Unsupported fields fail before any
  generation write; missing values do not pass a condition.
- The hidden stock-pool builder exposes an accessible condition editor while
  Strategy remains the product Owner through its `选股与输入` tab. Candidates
  still require generation and immutable pool sealing before full backtest.
- TDD evidence: three backend tests and one browser contract failed before the
  implementation; focused service tests now pass 27/27, and the real-backend
  condition-builder smoke passed without creating a pool or changing data.
- Verification: Mock browser suite 54/54; `./scripts/check.sh` passed the
  production build, bundle budget, lint with the existing Fast Refresh warning
  only, 392 backend tests and Python compilation. Paper continuity remained 15
  instances / 18 trades / 7 positions / 128 equity snapshots / 310 events.

## Strategy fusion: screening and research-input ownership (2026-08-20)

- Added an on-demand `选股与输入` tab to the Strategy centre. It owns the
  product entry points for basic-condition, factor and sector/event screening,
  immutable stock pools, factor research and sealed pool snapshots without
  copying the existing pool/factor engines into a second implementation.
- The tab reads business pool, sealed snapshot and factor-library counts only
  after the operator selects it. Strategy catalogue cold start therefore keeps
  its existing request budget; partial failures remain visible as unavailable
  counts and do not invent zero values.
- Every card states the gate into the mainline: candidates must be generated and
  sealed as a pool snapshot before a fixed Strategy API v1 version can enter a
  full backtest. Quick research still cannot create Paper evidence directly.
- A fail-first browser contract proved the tab and lazy requests were absent;
  focused Mock and real-backend browser acceptance now cover the six owner
  entries and hidden-route handoff.
- Verification: Mock browser suite 53/53; real-backend Strategy input-hub smoke
  passed; `./scripts/check.sh` passed the production build, bundle budget, lint
  with the existing Fast Refresh warning only, 389 backend tests and Python
  compilation. Paper continuity remained 15 instances / 18 trades / 7
  positions / 128 equity snapshots / 310 events after the clean restart.

## Operator capability fusion foundation started (2026-08-20)

- SP-014 closed after production SHA `029b2083111f03a5c14c987c821ed002b5a858fa`,
  Actions run `32362320989`, active backend/Nginx, 32/32 migrations and a clean
  production Strategy browser smoke.
- Activated `docs/contracts/active-operator-capability-fusion.md`: the only
  product mainline is Strategy → Backtest → Paper; Dashboard is the overview,
  while Market, Watch and Data are supporting workspaces. Existing experimental
  and safety routes remain registered while their capabilities are assigned to
  one Owner page each.
- Foundation slice starts with navigation and compatibility only. It does not
  change strategy formats, backtest execution, Paper state, providers, database
  schema or production data.
- The first Foundation increment is implemented: the seven visible links are
  grouped and ordered as 总览（首页）→ 主线（策略/回测/模拟）→ 补充（行情/盯盘/数据）.
  AI R&D remains available inside the Strategy catalogue; `/ai-lab` and all
  other hidden routes remain registered for compatibility. Fail-first browser
  assertions captured the previous four-group/eight-link layout before the
  navigation change.
- Real acceptance of the hidden Review route exposed two pre-existing cold-load
  defects and they were fixed in the same Foundation slice: optional market
  blocks now wait for the core review evidence, and the initial `?date=` value
  is honored instead of being replaced by the newest available date. Both
  behaviors have fail-first request-order/URL regression tests. The real sealed
  2025-01-02 review, resolved object links and seven-link navigation then passed.
- Verification: Mock browser suite 52/52; focused real navigation and sealed
  review tests passed; `./scripts/check.sh` passed production build, bundle
  budget, lint with the existing Fast Refresh warning only, 389 backend tests
  and Python compilation. Paper continuity remained 15 instances / 18 trades /
  7 positions / 128 equity snapshots / 310 events after clean restarts.

## SP-014 Gate 0 final local acceptance (2026-08-20)

- Restored AI R&D to the visible operator chain and restored the complete
  Strategy catalogue (`我的策略 / 策略广场 / 审计证据 / AI 研发`) without
  exposing pools, factors, monitor, review or live as first-level links.
- Real-browser acceptance found the Strategy catalogue still used the ordinary
  8-second page-read timeout. The SSH-tunnel-backed PostgreSQL path measured
  about 9-12 seconds per request (connection validation + SELECT + transaction
  cleanup), so the page showed a false timeout even though the API returned 53
  business strategies successfully. `getStrategies` now uses the established
  20-second cold-read envelope; a 9-second delayed-response browser regression
  test failed before the change and passes after it.
- Paper continuity was read back before and after clean local service restarts:
  all 15 instances preserved the same id, status, `started_at`, equity, trade
  count, position count, equity-snapshot count and event count. No migration,
  bootstrap, Paper recovery, realtime sync or strategy execution was triggered.
- Verification: focused backend contracts 37/37; Mock browser suite 50/50;
  real-backend Strategy browser acceptance passed with no page/console errors;
  `./scripts/check.sh` passed the production build, bundle budget, lint with the
  existing Fast Refresh warning only, 388 backend tests and Python compilation.
- External boundary remains explicit: no real `QWEN_API_KEY` is configured, so
  the live model call remains unavailable by design; deterministic and failure
  paths are covered, and no credential was borrowed from another project.
- The first production browser smoke then exposed one expected-but-noisy 404:
  an existing legacy strategy without an immutable version called
  `/strategy/{id}/versions/latest`. The optional lookup now returns `200 null`
  for an existing unversioned strategy while preserving 404 for a nonexistent
  strategy. A fail-first backend contract and the real Strategy browser test
  cover the behavior; the read remains provider-free and does not create a
  version. Paper continuity remained 15 instances / 18 trades / 7 positions /
  128 equity snapshots / 310 events after the subsequent clean restart.

## Form decision: restore AI R&D to the operator core chain (2026-08-18)

The parity contract's deliverables (strategy-page AI entry + `/ai-lab`) had been
buried by the later operator-trunk cut: `HIDDEN_NAV_IDS` hid AI 研发 along with
the experimental workspaces, and `SHOW_STRATEGY_EXTRAS` removed the strategy
page tabs and the "AI 写策略" button. The 2026-08-18 decision: the AI R&D
closed loop belongs to the core chain (data → strategy → backtest → paper →
AI R&D) and is restored; experimental workspaces (pools/factors/monitor/
review) and live stay menu-hidden with direct routes preserved.

- `docs/spec.md` §3: core chain table now includes AI 研发 `/ai-lab`; the
  menu-hidden list no longer contains it; decision recorded.
- `docs/contracts/active-bitpro-flow-parity.md`: goal 5 "12+1 nav invariant"
  replaced by the hybrid form decision; non-goals updated; decision blockquote
  added. This clears the conflict between the contract and the trunk cut.
- `frontend/src/components/Navigation.tsx`: removed `'ai-lab'` from
  `HIDDEN_NAV_IDS`; moved the item from the 系统 group to the 研发 group
  (after 回测). Sidebar order is now 首页/行情/策略/回测/AI研发/模拟/盯盘/数据.
- `frontend/src/pages/Strategy.tsx`: `SHOW_STRATEGY_EXTRAS = true` restores
  我的策略/策略广场/审计证据/AI研发 tabs and the "AI 写策略" + "规则生成"
  buttons (legacy `/strategy/auto-develop` endpoint still serves the
  deterministic template mode).
- `frontend/tests/e2e/app.spec.ts`: sidebar link list/count updated to the 8
  visible entries; strategy-catalogue test now asserts the tab counts
  (mine 1 / plaza 4 / audit 1), the visible AI研发 tab, and the visible
  "AI 写策略" button while keeping the acceptance-probe hidden.

Remaining blockers are non-navigation: `QWEN_API_KEY` is empty in
`backend/.env`, so the AI loop fails fast by design until a DashScope key is
configured; Goal 1/4 acceptance still needs that plus a real run recorded
here.

## Deployment merge follow-up: bound frontend dependency install (2026-08-18)

The merge itself reached `main`, but its production workflow stalled in
`Build Frontend`. The self-hosted runner log shows `npm ci` stopped while
issuing npm audit registry requests and never reached `npm run build`; the
server reboot later interrupted the job, leaving production on the previous
recorded SHA.

The deployment workflow now disables npm's non-build audit/fund requests for
the clean install and limits the complete frontend build step to 15 minutes.
Dependency resolution and the locked install remain enforced, while a future
network stall now terminates with a visible failure instead of occupying the
runner indefinitely.

## Concept leaders: visible sync path + em-delayed fallback (2026-08-17)

Problem: 板块龙头 panel always showed「该板块暂无龙头缓存」.
`concept_leaders_cache` had 0 rows — page reads are cache-only by contract,
and the only writer (`realtime_sync_service`, ENABLE_REALTIME_SYNC) is off by
default. Also, this machine's proxy/network blocks the eastmoney realtime
push2 cluster, so even manual syncs returned empty.

1. `POST /market/hot-concept/leaders/sync` (market.py): explicit write path
   syncing one concept (`?name=`) or the hot-concept top N (default 30);
   response reports synced/empty/failed plus the **source used per concept**.
   Page reads stay cache-only.
2. Leader fetch fallback chain: akshare realtime push2 →
   `_fetch_concept_leaders_em_delayed` (searchadapter name→BK-code +
   push2delay clist, direct connection, delayed ~15min, labelled
   `eastmoney-delayed`). Proxy-broken environments still get leaders.
3. Frontend (Market.tsx 板块龙头 panel): empty state gains a
   「同步龙头股」button (spinning state) that triggers the sync endpoint and
   refetches; client.ts adds `syncHotConceptLeaders`.

Verification: live chain via local `:4445` — sync 乳业 returned
`{"synced":["乳业"],"sources":{"乳业":"eastmoney-delayed"}}`; read-back
returns ranked leaders (金健米业 +10.05% …) with `data_status: fresh`;
`npx tsc -b --noEmit` clean. Seeded top-10 hot concepts afterwards.

## Backend performance fixes: PG pool + event-loop unblocking (2026-08-17)

Review-driven fixes, all verified against local `:4445` with real PG.

1. **P0-1 connection pool** (`postgres_db.py`): every query used to open a
   fresh `psycopg2.connect()` through the SSH tunnel. Added a
   `ThreadedConnectionPool` (1–16 conns) behind a `_PooledConnection` proxy
   that keeps both existing styles working: `with db.get_connection() as conn`
   (commit on success / rollback on error / return to pool) and bare
   `conn.close()` (returns to pool). Checkout runs a rollback liveness probe
   and discards tunnel-stale connections (up to 3 attempts). Pool closed on
   app shutdown (`main.py`). Unit tests in
   `backend/tests/test_postgres_connection_pool.py` (7 cases, no real DB).
2. **P0-2 event-loop blocking** (`api/endpoints/data.py`): ~25 async
   endpoints called sync DB/service code inline (quality issues, snapshots,
   daily-bars up to 1M rows, tushare probe/sync, job reads, symbol config,
   heal-missing, schedule runs). All wrapped in `run_in_threadpool` /
   `asyncio.to_thread`. `GET /data/kline/coverage` also stopped issuing the
   heavy coverage query twice per request. `market.py` already wrapped.
3. **P1-1 batch factor sync logs** (`factor_sync_service.py` +
   `postgres_db.save_factor_sync_logs`): success logs for synced factors are
   now one `execute_values` batch instead of one connection per factor ×3
   code paths; `records_count` now uses each factor's own count (was last
   factor's `len(df)` in path 1).
4. **check.sh venv** (`scripts/check.sh`): backend tests/compile now use
   `backend/venv/bin/python` when present, matching README's documented env.

Verification: full backend suite `398 passed, 8 failed` — the 8 failures
reproduce on clean `HEAD` (need real PG credentials / scheduler config), no
new failures. Live checks after restart: `/api/health/health` healthy;
authed `market/overview` 200 (5.3s cold → ~1ms cached), `data/status`,
`data/kline/coverage`, `data/datasets`, `data/sync/jobs` all 200.

Deferred (documented, not fixed): market-overview SQL-side aggregation
(per-exchange price-limit rules would be duplicated in SQL; 30s cache already
bounds cost) and ECharts `echarts/core` on-demand import (6 surfaces, needs
visual QA pass; bundle budget gate already enforces size).

## Data freshness: stop showing 7/7 or 8/7 as latest (2026-08-17)

User saw July 7 / August 7 while today is 2026-08-17. Facts:

1. Trade calendar and research partitions were frozen at **2026-08-07**, so
   `latest_open_date()` and Data Center knowledge cutoff stayed on 8/7.
   `formatFreshnessTime` omitted the year, so 07/07 vs 08/07 was ambiguous.
2. Short-line cache mixed **2026-07-29** 涨停数 with **2026-08-15** 涨跌比 and
   treated the latest stamp as fresh, so homepage ecology looked like July.
3. Review `available_dates` dropped 2026-08-14 (calendar `unknown`) and then
   per-date calendar SQL timed out (~14–25s) →「暂无可用交易日」/ 最近复盘 2025-01-02.

Fixes (no long-term scheduler change; schedule was already enabled, last seal 08-07):

- Published TuShare `trade_cal` 2026-08-08..08-17. Latest complete session is
  **2026-08-14** (today 08-17 is an open day, still in session).
- Lean-inserted full-A daily bars 08-10..08-14; sealed dataset snapshot **23**
  `daily-research-2026-08-14-…`. Market evidence snapshot 21 already 08-14.
- Short-line cache is invalid if **any** row is stale → fall back to sealed
  08-14 evidence. Homepage header shows `证据日 YYYY-MM-DD`. Freshness labels
  include year. Review dates use one calendar query + keep unknown weekdays
  that already have published market evidence.

Verification: `unittest` review / trading-date / short-line cache (28 tests);
`npx tsc -b --noEmit`. After local `:4444`/`:4445` restart, health healthy;
short-line `trade_date=2026-08-14 sealed_snapshot`; desk 证据日 2026-08-14.
Still missing: today 08-17 post-close seal; 08-15 Saturday kline rows exist
but are not a trading day; daily reviews table still only 2025-01-02.

## Operator sidebar visual pass (2026-08-17)

1. Desktop rail is 72px, near-black (`bg-crypto-bg`), hairline `crypto-border`. Group titles no longer render as 8px squeezed labels; groups stay as `role="group"` with `aria-label` and a 1px divider.
2. Nav items are icon + 11px label, aligned; selected state is `crypto-accent` fill + 2px left bar, no glow or hover-scale. `HIDDEN_NAV_IDS` unchanged (因子 / 股票池 / 监控 / 复盘 / AI / 实盘 stay hidden).
3. Logo uses `StockProMark quiet` (no gradient shell). Session badge compact is a single-line dot + label from the existing market-session source. Role footer is muted text, not a colored sticker.
4. E2E desktop width assertion updated from `<= 65` to `70–80`. Did not touch paper read-path or Watch.tsx.

Verification: `npx tsc -b --noEmit` passed (Watch.tsx 本轮未报错). Local `:4444` / `:4445` restarted; both ports listening; `GET /api/health/health` returned healthy. Pushed `f4abf5b` on `main` (menu files only).

## First-screen read speed (2026-08-17)

Root cause: backtest configuration opened 7 Postgres connections and shipped
`script_content`; run list selected `r.*` (~300KB); research-context compared
history with per-snapshot reads (now batched + one connection + 30s cache);
data status scanned all `kline_history` and `COUNT(*)` every table.

Changes:

1. `/backtest/configuration` drops scripts, counts universe members in a
   subquery, reuses one connection, 30s cache.
2. `/backtest/runs` returns list columns only (keeps `metrics` for KPIs).
3. `/market/research-context` reuses one connection and caches 30s. Comparison
   batching from the parallel hang fix is kept.
4. `/data/status` caches 30s, coverage from `sync_metadata` top 80, table
   counts from `pg_stat_user_tables`, and reuses those rows for manager
   status instead of querying coverage twice.
5. Backtest page renders the run list as soon as runs/jobs return; create
   wizard waits for configuration. Page GETs use 8s timeout + no retry
   (research-context keeps its existing timeout).

Verification: `unittest` workbench / research-context / backtest API /
async reads / overview (65) passed. `npx tsc -b --noEmit` passed. Local
`:4444` / `:4445` healthy after restart. Timed reads 2026-08-17:

| API | before | after cold | after warm |
| --- | ---: | ---: | ---: |
| `/backtest/configuration` | 10.1s / 294KB | 2.3s / 52KB | 1ms |
| `/backtest/runs?limit=50` | 1.3s / 301KB | 2.1s / 122KB | — |
| `/market/research-context` | 25s timeout | 3.5s / 64KB | 1ms |
| `/data/status` | 14.3s / 266KB | 6.5s / 47KB | 1ms |
| `/strategy/list` | 2.5s | 1.6s | — |
| `/paper/instances` | 1.2s | 1.3s | — |
| `/market/overview` | 3.2s | 6.1s first after restart | 1ms |

## Operator trunk visibility cut (2026-08-17)

1. Sidebar now shows only the daily trunk: 首页 / 行情 / 策略 / 回测 / 模拟 / 盯盘 / 数据. Admin settings stay at the bottom.
2. Menu-hidden (routes kept): 因子、股票池、监控、复盘、AI研发、实盘、数据处理. Extended the existing `HIDDEN_NAV_IDS` set; did not replace that hide mechanism or restore the research-desk rail.
3. Kept prior hides: homepage has no 量化研究台 panel; `WorkspacePipelineNote` still returns null. Did not change MarketResearch load/API (parallel hang fix owns that path).
4. Page chrome cut: Strategy hides AI 写策略 / 规则生成 / 策略广场 / 审计证据 / AI 研发 tabs. Watch hides 股票池变动 and the audit-scope / Tremor tracker chrome. Login hides 邀请码访客 unless `?invite=` is present. Settings no longer mount GuestCodeManager.

Verification: local `:4444` / `:4445` listening; `/api/health/health` healthy.
Screenshots `/tmp/stockpro-trunk-qa/01-home-sidebar.png`, `02-strategy.png`, `03-backtest.png`:
sidebar text is 研究 首页/行情 · 研发 策略/回测 · 验证 模拟/盯盘 · 系统 数据.
No 因子/股票池/监控/复盘/AI研发/实盘 links. No 量化研究台 / 本页就绪 / 继续盯盘 / AI 写策略 / 策略广场.

## Hide 因子 / 股票池 from primary nav (2026-08-17)

`Navigation.tsx` filters `pools` and `factors` via `HIDDEN_NAV_IDS`; `/pools` and `/factors` routes stay registered.

## Paper read-path speed (2026-08-17)

1. `/paper` dashboard was waiting on three reads: full instance list, 200
   backtest runs, then `get_instance` for the first card. Detail used 14
   Postgres connections (one `_row`/`_rows` each) plus `SELECT *` on
   `strategy_versions` (script) and `backtest_runs`.
2. `get_instance` now uses one connection and one SQL (`json_agg` ledgers),
   omits `script_content`, and returns a slim qualifying backtest. K-line
   history is capped at 800 bars. A first empty-instance read that still
   took ~10s with 12 sequential queries is the reason for the single SQL.
3. `GET /paper/instances` caches 20s and stamps TTL after the query; create /
   start / pause / resume / stop / cycle clear the cache. Dashboard loads the
   list only; create loads eligible runs; detail loads one instance.
4. 10s card poll stays on the dashboard. Did not change Paper lifecycle,
   ledger semantics, or invent missing Sharpe / win-rate fields.

Verification: `unittest` paper runtime service / API 48 passed. Local
`:4444` / `:4445` healthy. Timed reads after the single-SQL change:
list 1.9s → 1ms cache; detail 9.8s → 3.3s (empty instance, no
`script_content`). Dashboard no longer waits on 200 backtests or the
first card's full ledger.

## Operator trunk visibility cut (2026-08-17)

1. Sidebar now shows only the daily trunk: 首页 / 行情 / 策略 / 回测 / 模拟 / 盯盘 / 数据. Admin settings stay at the bottom.
2. Menu-hidden (routes kept): 因子、股票池、监控、复盘、AI研发、实盘、数据处理. Extended the existing `HIDDEN_NAV_IDS` set; did not replace that hide mechanism or restore the research-desk rail.
3. Kept prior hides: homepage has no 量化研究台 panel; `WorkspacePipelineNote` still returns null. Did not change MarketResearch load/API (parallel hang fix owns that path).
4. Page chrome cut: Strategy hides AI 写策略 / 规则生成 / 策略广场 / 审计证据 / AI 研发 tabs. Watch hides 股票池变动 and the audit-scope / Tremor tracker chrome. Login hides 邀请码访客 unless `?invite=` is present. Settings no longer mount GuestCodeManager.

Verification: local `:4444` / `:4445` listening; `/api/health/health` healthy; admin token login.
Screenshots `/tmp/stockpro-trunk-qa/01-home-sidebar.png`, `02-strategy.png`, `03-backtest.png`:
sidebar text is 研究 首页/行情 · 研发 策略/回测 · 验证 模拟/盯盘 · 系统 数据.
No 因子/股票池/监控/复盘/AI研发/实盘 links. No 量化研究台 / 本页就绪 / 继续盯盘 / AI 写策略 / 策略广场.

## Market `/research-context` hang (2026-08-17)

1. `/market` structure/sentiment tabs spun on「读取市场快照…」because
   `GET /api/market/research-context` never returned in time. Health and
   `/api/market/overview` were fine; the research-context path was the stall.
2. Root cause: `MarketResearchService._comparisons` opened a new PostgreSQL
   connection per query, then walked up to 242 history snapshots with
   per-snapshot `sentiment()` plus a `highest_board` `_row` each. Through the
   local DB tunnel that is 240+ round-trips and a 25s+ hang. No fabricated
   quotes; the snapshot existed (evidence date 2026-08-14) but the comparison
   fan-out never finished.
3. Backend now loads comparison history once and batches all comparison
   metrics with `snapshot_id = ANY(...)`. Query count for a long history is
   2 instead of 240+. `research_context` also reuses one PostgreSQL connection
   per request (`_session`) and keeps a 30s in-process cache. Frontend
   `getMarketResearchContext` uses a 20s timeout, does not retry timeouts,
   and the market page shows an honest empty/error panel instead of an
   infinite spinner. Snapshot-less 200s also stop loading. Snapshot load no
   longer waits for `/market/message-stream` (~12s); news fills the events
   tab in the background.
4. Did not touch Dashboard / 量化研究台. The parallel workspace change already
   made `WorkspacePipelineNote` a no-op, so this slice does not restore that rail.

Verification: focused `test_market_research_service` 17/17. Local 4444/4445
restarted; `/api/health/health` 200. Authenticated
`GET /api/market/research-context?market_scope=all_a` returned published
snapshot 21 / 2026-08-14 in 3.9s (second call 1ms cache). Browser login
`admin` then `/market?tab=structure` showed 市场数据快照 + 上涨/涨停真实值
and `/market?tab=sentiment` showed 连板天梯; neither stayed on
「读取市场快照…」. `message-stream` is still ~12s and only fills the events
tab. `twenty_day` / one-year percentile stay unavailable because sealed
history is shorter than 20 days — not fabricated.

## Hide 因子 / 股票池 from primary nav (2026-08-17)

`Navigation.tsx` filters `pools` and `factors` via `HIDDEN_NAV_IDS`; `/pools` and `/factors` routes stay registered.

## Workspace: remove 多因子风险预算 rail (2026-08-17)

1. User screenshot pointed at the shared workspace chrome: title 多因子风险预算,
   green 本页就绪, snapshot/evidence line, 继续盯盘. That is
   `WorkspacePipelineNote`, mounted under almost every workspace header
   (行情 / 股票池 / 因子 / 策略 / 回测 / 模拟 / 盯盘 / 监控 / 复盘 / 数据 /
   AI 研发). It is not the homepage `ResearchDeskPanel`.
2. `WorkspacePipelineNote` now renders nothing. Page mounts stay so this
   change does not touch Dashboard or MarketResearch load/API. Backend
   `GET /workflow/research-desk` and `ResearchDeskContext` stay.
3. `/pools` four-step strip (设定规则 → 筛选成员 → 封存快照 → 送去回测) is
   local to `StockPools.tsx` and remains. `WorkflowRail` was already unused
   in `MainLayout`.

Verification: local `:4444` / `:4445` restarted; login `admin` and open
`/pools`, `/market`, `/strategy` — none show 多因子风险预算 / 本页就绪 /
继续盯盘. Pools still has the four-step strip.

## Homepage: remove 量化研究台 panel (2026-08-17)

1. User asked to take the 量化研究台 command panel off `/` only. The
   homepage is now 市场大盘: indices, pulse, 涨停生态, and sector fund flow.
2. `ResearchDeskPanel` is no longer mounted in `Dashboard.tsx`. The page
   subtitle no longer describes a research-desk overview. Header-to-market
   spacing is unchanged besides dropping the panel wrapper.
3. Kept `GET /workflow/research-desk`, `ResearchDeskPanel.tsx`,
   `ResearchDeskContext`, and the workspace `WorkflowRail` (多因子风险预算 /
   本页就绪). Other pages still use the rail; the panel was not moved.

Verification: local frontend `:4444` and backend `:4445` restarted after the
source change; `/api/health/health` and homepage screenshot confirm the
panel title is gone.

## 20 Daily-Bar 打板 / 隔日T Strategies (2026-08-16)

1. Added 20 Strategy API v1 presets: 8 打板隔日 T, 8 隔日 T, plus 3-day
   reversal / 20-day momentum / MA breakout / low-vol defense. Engine is
   A-share daily T+1. Limit-up is close-to-close ≥ 9.5%, not tick HFT or T+0.
2. Registered and validated all 20 via `POST /api/strategy`. Quick jobs ran
   on dataset 10 / universe 1 / factor 4 / pool 5 (研究20动量池).
3. All 20 quick runs succeeded with real fills. Last-30-session results:

   | 策略 | 成交 | 收益 | 胜率 | run |
   | --- | ---: | ---: | ---: | --- |
   | 窄幅突破 | 94 | +0.25% | 50% | `fa9f6317-…` |
   | 大振幅回归 | 106 | -0.01% | 44% | `a67d8e98-…` |
   | 三日超卖反转 | 102 | -0.10% | 44% | `c99601f0-…` |
   | 二十日动量轮动 | 38 | -0.11% | 50% | `1f26e624-…` |
   | 放量阳线 | 94 | -0.18% | 46% | `426559dc-…` |
   | 均线多头突破 | 78 | -0.23% | 37% | `f4268b83-…` |
   | 低波动防守 | 74 | -1.13% | 50% | `fd2aab00-…` |
   | 跌停反抽 | 110 | -2.41% | 43% | `4e597f82-…` |
   | 首板/连板/高度板/炸板 | 110 | -2.49% | 39% | 大票宇宙涨停稀少，信号退化 |
   | 首板放量 | 110 | -3.08% | 37% | `fc00d0ee-…` |
   | 隔夜高开跟随 | 110 | -3.33% | 35% | `6cb6e4b1-…` |
   | 实体板 / 有空间板 | 110 | -3.53% | 33% | 收盘位置排序接近 |
   | 尾盘强势 | 110 | -3.63% | 31% | `4727cf83-…` |
   | 低开高走 | 110 | -3.88% | 43% | `3e85ea26-…` |
   | 高开高走跟随 | 110 | -4.51% | 41% | `39e45528-…` |
   | 下影线回踩 | 110 | -5.20% | 37% | `bbb85174-…` |

4. Differentiated 首板 / 连板 / 高度板 fallbacks (acceleration / 3-day streak /
   5-day height) and re-queued those three plus 60-day fulls for 窄幅突破、
   大振幅回归、三日反转、二十日动量. Numbers above are sealed quick evidence,
   not forecasts.

Verification: `unittest tests.test_board_t_strategies` passed; `npx tsc -b
--noEmit` passed. Local `:4444` / `:4445` healthy. Open
`http://localhost:4444/backtest/fa9f6317-fcd7-4414-ae54-fee509a97324` or
search 策略页 `打板` / `隔日T`.

## Same-Strategy Loop + Read-Path Speed (2026-08-16)

1. Full replay envelope: quick stays 3s; `backtest`/`paper_replay` now use
   180s wall so the multi-factor strategy can finish a sealed full run.
2. First full job `fb147a66-…` reached persist then died on the SSH tunnel
   (single huge INSERT + per-row trades). Persist now writes orders/trades/
   positions in pages of 50; startup recovery fails orphaned `running` runs.
3. Retry job `208e60d7-…` succeeded. Sealed run
   `490892ac-5528-422d-8810-3b2b4675e96f` on dataset 10 / universe 1 /
   factor 4 / pool 5 / protocol `6f6d3078-…`. Persist finished in ~3 minutes.
4. Promotion is `rejected`: 10/11 gates passed. `CAPACITY_PASS` failed because
   peak single-name weight was 16.97% versus the protocol 12% cap
   (participation 0.08% and capacity warnings 0 were fine). No Paper instance
   was created; the gate was not relaxed.
5. Read-path: research-desk 60s cache; watch context uses a light instance
   list + 20s cache; market overview 30s HTTP cache; strategy list no longer
   ships `script_content`.
6. Decision surfaces: factor page shows 4 pipeline Rank ICs; strategy can
   jump to a bound full-backtest wizard; wizard defaults to 多因子 + 动量池
   instead of the newest incompatible dataset 22; review prefers desk
   evidence date; homepage / rail / desk show evidence cutoffs. Desk and
   workspace notes no longer treat other-strategy Paper as this loop.
7. Watch/overview/desk caches now stamp TTL after the query finishes, so a
   30s+ first read no longer expires the cache before it is stored.

Verification: `unittest` research-desk / runtime / overview / workbench /
router / watch-cache tests passed (54 + 43). `npx tsc -b --noEmit` passed.
Local `:4444` / `:4445` healthy after restart. Timed reads: desk 8.1s → 1ms,
overview 19.0s → 1ms, watch 34.1s → 1ms. Full run
`490892ac-…` is `rejected` on `CAPACITY_PASS` (peak weight 16.97% > 12%).

## Quant Research Desk + Multi-Factor Pipeline (2026-08-16)

1. Main menu stays 12 first-level links and 64px wide, but is grouped into
   研究 / 研发 / 验证 / 系统 so a quant desk can scan the lifecycle.
2. Every workspace now shows a live research-desk rail
   (`数据 → 行情 → 因子 → 股票池 → 策略 → 回测 → 模拟 → 盯盘 → 监控 → 复盘`)
   from `GET /workflow/research-desk`. Counts are read-only SQL; empty stages
   stay empty instead of inventing market or PnL numbers.
3. Homepage keeps 市场大盘 / 市场指数 and adds a 量化研究台 command panel
   for the active strategy, latest backtest, Paper instance and next action.
4. Added Strategy API v1 `多因子风险预算`: weekly cross-section of
   momentum_20d / reversal_3d / volatility_20d / amihud_5d, 12% name cap,
   median-return halt. Factor miss falls back to price momentum.
5. Research-desk queries now share one Postgres connection (was one SSH
   handshake per COUNT). Each workspace page shows a binding note for the
   same strategy, factor set, snapshot and next action.
6. Live desk on 2026-08-16: all 10 stages `available`; strategy id 186
   `多因子风险预算`; quick backtest `e8f0613a-…` success (not paper-eligible);
   4/4 pipeline factors present. Paper/watch/monitor still bind existing
   running instances — no invented PnL.

Verification: `tests.test_research_desk` + workflow/router tests passed;
`npx tsc -b --noEmit` passed; `/api/health/health` and frontend `:4444`
confirmed after local restart. `/workflow/research-desk` returned 200 in
~10s over the tunnel.

## Local Page Empty-State Diagnosis (2026-08-15)

1. Confirmed the workstation was not an empty database: `stockpro_dev` still
   holds K-line history and a 5540-row realtime cache, but the cache stopped
   on 2026-08-07 and page reads never fetch providers
   (`ENABLE_EXTERNAL_MARKET_FETCH=false`).
2. Homepage looked blank because `/api/market/overview` took ~20s over the SSH
   tunnel: `get_all_stocks_realtime()` joined listing-status and a 90-day
   trade-calendar JSON scan. The UI default copy while that request was in
   flight was “全市场实时快照未同步”.
3. Overview now reads quote rows only (`include_listing_status=False`). The
   dashboard shows “正在读取缓存” while loading and no longer hides a stale
   THS hot name. Manual market-evidence sync published snapshot 21 for
   2026-08-14 (63 limit-up / 9 limit-down).

Verification: `unittest` `test_market_overview_fast_path` +
`test_readonly_runtime_contracts` passed (24 tests). Local services restarted
via `./restart.sh`. Overview still ~9s because 5540 rows cross the tunnel;
limit-board/short-line now return the 2026-08-14 sealed snapshot.

## Tremor Operator System Alignment (2026-07-29)

1. Replaced the reintroduced capsule-style workspace buttons with Tremor's
   compact underline tab rail across all shared L2/L3 navigation. Scope,
   status and sort choices remain segmented controls, so navigation no longer
   competes with filters or primary actions.
2. Applied the shared workspace viewport to every routed page through
   `MainLayout`: dense table rhythm, factual card elevation, consistent focus
   treatment, tabular figures and responsive overflow rules now originate from
   one Tremor/BitPro operator surface instead of per-page decoration.
3. Removed the Dashboard's simulated Tremor showcase. The product now uses the
   Tremor components only with API-backed or explicit empty/error data; no
   invented PnL, sector flows, uptime or risk alerts remain on the page.
4. Updated delta badges to respect the configurable A-share red-up/green-down
   setting through semantic `text-up` / `text-down` tokens.

Verification: `./scripts/check.sh` passed (frontend build/lint, 290 backend
tests and Python compilation; 6 pre-existing Hook warnings). Desktop browser
review covered Dashboard and Monitor; 390px review covered Market Research.
The read-only capture sweep covered Dashboard, Market sentiment/structure,
Review, Data Center, Data Processing, Paper and Factor Library: all reported
the operator marker, no page-level horizontal overflow and no blank metric
values.

Known QA gap: the broad historical `npm run test:e2e` suite still hard-codes
superseded page names, sidebar order, button roles and fixture-era snapshot
values. Its 2026-07-29 run had 21 passing tests, 15 stale assertion failures
and 7 interrupted after the run was stopped; it is not a valid release gate
until its product fixtures are reconciled separately.

## Full Navigation & Page Micro-animations Tremor UI Transformation (2026-07-29)

1. **L1 Sidebar Navigation (`Navigation.tsx` / `MainLayout.tsx`)**:
   - Added Tremor Active Accent Indicator Bar (`border-l-2 border-blue-400 bg-blue-500/15 shadow-[0_0_8px_rgba(56,189,248,0.7)]`).
   - Added icon hover scale animation (`group-hover:scale-110`) and `.animate-fade-in-up` page route transition animation.
2. **L2/L3 Tabs & Controls (`WorkspaceTabs.tsx` & `OperatorShell.tsx`)**:
   - Upgraded tabs to Tremor Capsule Pills with blue glow shadow and `active:scale-95` tactile press feedback.
   - Enhanced `CatalogueCard` with 1px hover lift animation (`hover:-translate-y-[1px] hover:border-blue-500/40 hover:shadow-lg hover:shadow-blue-500/5`).
3. **Global Tactile Interactions (`index.css`)**:
   - Injected global button tactile bounce (`active:scale-[0.98] transition-transform`).

Verification: `./scripts/check.sh` clean (build, 0 lint errors, 290 unit tests PASS); services running on :4444 & :4445.

## MarketSession Badge Static Pill & Brand Logo Redesign (2026-07-29)

1. **Removed Breathing Animations & Glowing Pulses**:
   - Cleaned `market-session-breath*` animation keyframes, glow shadows, and expanding ripple elements from `MarketSessionBadge.tsx` and `index.css`.
   - Replaced status badge indicator with clean, non-distracting static solid dots (emerald/amber/sky/slate).
2. **Redesigned StockPro Brand Logo (`frontend/src/components/StockProMark.tsx`)**:
   - Crafted high-end modern quant brand mark featuring:
     - Gradient dark crystal shell with ambient sky-blue glow.
     - Multi-dimensional asset pillar foundation + impulse trend stroke (`#38BDF8` → `#818CF8`).
     - Emerald quant trigger spark point (`#34D399`).

Verification: `./scripts/check.sh` clean (build, 0 lint errors, 290 unit tests PASS); frontend restarted on :4444.

## Full-Site Tremor UI Style Transformation (2026-07-29)

1. **Shared Tremor UI Component Library (`frontend/src/components/TremorUI.tsx`)**:
   - Standardized `TremorCard`, `TremorDeltaBadge`, `TremorTracker`, `TremorBarList`, `TremorCallout`.
2. **Page Refactors & Style Enhancements**:
   - **DataCenter.tsx**: Integrated `TremorBarList` for table storage scale visualization.
   - **Watch.tsx**: Added `TremorDeltaBadge` for signal direction badges and `TremorTracker` for 30-day runtime health monitoring.
   - **FactorLibrary.tsx**: Added `TremorBarList` for factor universe coverage rankings.
   - **TremorShowcasePanel.tsx**: Refactored to import from shared `TremorUI`.

Verification: `./scripts/check.sh` clean (build, lint with 0 errors, deploy syntax, 290 unit tests PASS); services running on :4444 & :4445.

## Workstation Full Menu Audit & Data Self-Healing (2026-07-29)

1. **Full-Menu QA Audit**:
   - Created Playwright end-to-end audit suite `frontend/tests/e2e/full-menu-audit.spec.ts`.
   - Executed deep click testing across all 12 primary navigation menus, 34 L2 tabs, and 18 L3 leaf views with 100% test pass rate (12/12 suites).
2. **Data Self-Healing Infrastructure**:
   - Added backend self-healing endpoint `POST /api/data/heal-missing` (`backend/app/api/endpoints/data.py`).
   - Integrated "一键数据自愈" clinic button and client API binding into Data Center (`frontend/src/pages/DataCenter.tsx`).
3. **Resilience & Fallback Fixes**:
   - Implemented rule-based local analysis fallback generator `_generate_rule_based_fallback` in `AIService` when Qwen API key is unconfigured, avoiding raw 503 errors.
   - Refactored `ChartService` provider fallback and normalized intraday zero-axis `pre_close` logic.

Verification: `./scripts/check.sh` clean (build, lint, deploy syntax, 290 unit tests PASS); Playwright full-menu audit 12/12 PASS; services running healthy on :4444 and :4445.

1. Introduced GitHub high-star Tremor UI Design System visual components for analytics and dashboards into StockPro.
2. Built `TremorShowcasePanel` component (`frontend/src/components/TremorShowcasePanel.tsx`) implementing:
   - Tremor KPI Metric Cards with `TremorDeltaBadge`
   - Tremor Tracker (30-day health status stream bar with tooltips)
   - Tremor BarList (high-density sector money flow ranking bars)
   - Tremor Callout boxes
3. Integrated `TremorShowcasePanel` into `/` (Dashboard page). Fixed `@bitpro/ui` type declarations in `vite-env.d.ts`.

Verification: `npx tsc -b --noEmit` clean; frontend & backend restarted on :4444 and :4445; backend health OK.

## Market Page Refresh Loop + Stale Evidence (2026-07-29)

1. Root cause of「总是刷新」: `RequireAdmin` treated any `/auth/me` failure
   (including uvicorn `--reload` blips) as logout → login redirect loop.
   Now only 401/403 clears the session; network/5xx retries optimistically.
2. Sentiment/structure pages show sealed post-close evidence, not live quotes.
   Latest was stuck at 2026-07-27; published 2026-07-28 evidence snapshot #12.
   UI now shows「证据截止」badge + stale lag banner; date picker no longer
   auto-locks to the sealed day (empty = 最新封存).

## Trading Calendar Capsules (2026-07-29)

1. Empty `market_calendar_events` left `/market?tab=calendar` blank; rebuilt as
   live month grid from TuShare `trade_cal` + `fut_basic` + CNY `eco_cal`.
2. New `GET /market/trading-calendar` tags each day: 开盘/休市、股指交割、
   国债/商品交割、期权窗口、月末/季末、LPR 等重大事项（胶囊样式）。
3. Builder upserts event cache so legacy `/market/calendar` is no longer empty.

Verification: July 2026 API returns 股指交割 on 07-17, LPR on 07-20, 期权交割
on 07-22; `npx tsc --noEmit` OK; services :4444/:4445 healthy.

## Workstation Review + Intraday Fallback (2026-07-29)

1. Full menu/module audit (12 L1 + L2): structure OK, freshness weak.
2. P0: `ChartService.get_intraday_data` falls back to AkShare
   `stock_zh_a_hist_min_em` when `kline_1m` empty (verified 121 bars).
3. Sector fund-flow Sankey labels show 亿元 amounts.
4. Review canvas: stockpro-workstation-review.canvas.tsx.

Open: stale index/short-line/hot-concept caches; broken lianban dates;
monitor critical; intraday pre_close mapping.

## Realtime Order Book (2026-07-29)

1. Probed TuShare: paid `rt_k` needs add-on (current token denied); Pro
   `realtime_quote`/`quote_detail` stubs fail; package
   `get_realtime_quotes` returns live L5 depth (Sina-backed).
2. Added `GET /market/order-book/{symbol}` via TuShare quotes → East Money
   AkShare fallback; volumes normalized to 手.
3. 个股研究右侧挂「五档盘口」并 5s 轮询，保留全市场筛选列表；来源标签诚实展示。

Verification: provider + API smoke on `SH_600519` (茅台五档 OK); `npx tsc --noEmit`
OK; services :4444/:4445 healthy.

## Stock Pools Simplification & Modernization (2026-07-29)

1. Reviewed stock pool architecture and consolidated redundant tabs (`mine`, `screener`, `factor`, `sector`, `event`, `snapshots`) down to 3 focused workspaces:
   - **我的股票池 (`mine`)**: Stock pool rule catalog, status filters, member list, snapshot sealing, and evidence binding.
   - **基础筛选与建池 (`screener`)**: Unified multi-mode screening builder containing mode selectors: 板块选股 (Sector), 事件选股 (Event), 基础条件 (Basic screener), and 因子选股 (Factor).
   - **快照与回测 (`snapshots`)**: Immutable stock pool snapshot repository and one-click backtest draft creation.
2. Modernized `StockPools.tsx` with Financial Operator UI design system & Tremor UI components (`TremorCard`, `TremorCallout`, `TremorBarList`, `TremorDeltaBadge`, `SymbolCell`, `MetricValue`, and `@bitpro/ui` tokens).
3. Verified full test suite via `./scripts/check.sh` (290/290 backend unit tests PASS, frontend build & lint PASS).

## StockPro Mark + Dashboard Session Breath (2026-07-29)

Designed StockPro brand mark as rounded dark shell + single sky pulse stroke
(`StockProMark` + favicon). Homepage header uses prominent「开盘中」badge with
dual-layer breathing light; sidebar/login reuse the same mark.

Verification: `npx tsc --noEmit` OK; frontend restarted on :4444.

## Backtest Evidence Table Typography (2026-07-29)

Aligned backtest detail tables to BitPro role typography: Chinese metric labels
with mono codes, primary values as bold tabular mono with semantic up/down,
units as muted chips, versions/null reasons as low-contrast meta. Tab renamed
`收益分析` → `绩效指标`. Verification: `npx tsc --noEmit` OK; frontend :4444 OK.

## Market Stock Universe Browse (2026-07-29)

1. `GET /stocks/search` empty `q` now returns成交额-sorted browse window from
   `all_stocks_realtime` (limit up to 500); non-empty `q` filters full universe
   by code/name.
2. 个股研究 (`/market?tab=stock` A股模式) loads ~200-stock browse list, dropdown
   search up to 120 hits, and right panel「全市场标的」with independent filter —
   no longer stuck on a single selected symbol / concept leaders.

## Market Terminal Theme Toggle (2026-07-29)

Fixed `/market?tab=stock` 行情终端「A股 / 板块」switch: previously decorative
with no state/`onClick`. Now toggles scope; 板块 mode selects hot concepts,
loads concept intraday + 龙头 list, and can jump back to A-share daily for a
leader.

## Sentiment Tab Tonghuashun Layout (2026-07-29)

1. Removed English unit suffixes (`stocks`/`percent`/`boards`/`ratio`) from
   `/market?tab=sentiment` metric cards; only show `%` / `板` when needed.
2. Rebuilt sentiment workspace to a Tonghuashun-like scan layout: compact KPI
   strip → 连板天梯 (1–5+板 columns with name+code lists) → 涨停/跌停/炸板 pools
   → 晋级/淘汰 queues.
3. Dashboard short-line cards also stop appending English `stocks`.

## Limit Board Charts On Homepage (2026-07-29)

1. Backend `GET /market/limit-board` reads sealed `limit_pool_members`
   (TuShare `limit_list_d`) for full 涨停/跌停名单；无成员时回退 ±9.8% 估计。
2. Dashboard「涨停生态」下增加 `LimitBoardPanel`：涨停/跌停 Tab 全列表，
   点开个股懒加载近 30 日 K + 当日分时（`StockMiniCharts`）。
3. Fixed `getIntradayChart` to unwrap `{ data, pre_close, trade_date }`.

Verification: `npx tsc --noEmit` OK; `GET /market/limit-board` returns
up=111/down=6 for sealed 2026-07-27; e2e
`limit-up and limit-down|realtime market cockpit` 2 passed; services on
:4444/:4445 via screen.

## Market Session Breathing Light (2026-07-29)

1. Backend `MarketService.market_session()` returns A-share phase
   (`pre_open` / `auction` / `open` / `lunch` / `closed` / `weekend`) in
   Asia/Shanghai; `/market/overview` exposes `session_phase` + labels.
2. Frontend `MarketSessionBadge` with CSS breathing light; wired into MainLayout
   sidebar (global), Dashboard header, MarketOverview, SentimentAnalysis.
3. Open = green breath; auction = amber fast; pre/lunch = slow; closed/weekend =
   dim gray breath. Clock ticks every 15s; respects `prefers-reduced-motion`.

## Reference Factor Catalog ×100 (2026-07-29)

1. Added `backend/app/services/reference_factor_catalog.py` with exactly 100
   sealed-snapshot-computable reference factors across momentum / reversal /
   volatility / liquidity / size / value / technical.
2. Selection prioritizes published cross-section hypotheses and spaced lookbacks;
   removed same-window momentum↔reversal mirrors and valuation transform twins.
3. `install_reference_factors` now bumps `version_no` when Python content changes
   (fixes unique constraint on definition+version_no).
4. Obsolete system factors outside the catalog are deprecated; FactorLibrary
   shows a 5-step research workflow strip.
5. Smoke execute on sealed snapshot #10 (20-symbol panel): 100/100 valid;
   mean |Spearman| ≈ 0.31. Full-universe IC maturity still needs daily schedule
   + forward windows — not claimed as live alpha proof from this install alone.

Verification: `pytest tests/test_factor_research_service.py` 12 passed; install
returns 100 system-enabled definitions.

## Homepage Sector Fund-Flow TOP30 (2026-07-28)

1. TuShare 对标：`moneyflow_ind_dc`（东财板块资金流向）、`moneyflow_ind_ths` /
   `moneyflow_cnt_ths`；无板块间真实迁移矩阵，Sankey 连线按流入权重分摊并明示。
2. Backend `GET /market/sector-fund-flow` 从 `hot_concepts_realtime` 组装流入/
   流出/TOP30；龙头同步范围扩到 TOP30 概念。
3. Dashboard 用 `SectorFundFlowPanel`：ECharts Sankey + TOP30 列表 + 点选加载
   `hot-concept/leaders` 核心龙头；去掉原先 |涨幅|<5% 只显示 TOP5 的门槛。

Verification: `npx tsc --noEmit` OK; `GET /market/sector-fund-flow?limit=30`
returns 30 rankings; frontend/backend restarted healthy; e2e
`sector fund-flow|realtime market cockpit|stale market caches` 3 passed.

## Remaining Symbol Chinese Names Sweep (2026-07-28)

1. Backtest detail `GenericTable` 持仓/交易/订单: `SymbolCell` + `useSymbolNames`.
2. Paper legacy `DataTable` symbol columns wired the same way.
3. Paper instance cards「证券范围」and detail K-line `<select>` / empty copy use
   `formatSymbolLabel` (中文名 + 公开代码).
4. MarketResearch sector「龙头」column uses `SymbolCell`; BitPro detail panels
   trade/position/order/strategy-range chips switched to `SymbolCell`.

Verification: `npx tsc --noEmit` passed; frontend/backend restarted healthy.

## Global Symbol Chinese Names (2026-07-28)

1. Rule: numbered A-share codes must render with 中文名 (primary) + public code
   (secondary). Shared `SymbolCell` + `useSymbolNames` + `POST /data/symbol-names`.
2. Backend attaches names via `lookup_symbol_names` on stock-pool members/
   generations/snapshots and factor values.
3. Wired StockPools members table, FactorLibrary values, Market selector,
   MarketResearch limit pools, Strategy detail trading range, Paper positions/
   trades, Watch tables.

Verification: pool members API returns `格力电器` for `SZ_000651`; `tsc` OK;
services healthy.

## Hide Test/Acceptance Scope From Operator UI (2026-07-28)

Removed page-level「测试与验收」scope switches and验收/种子 badges from Paper,
Backtest, Watch, Monitor, AI Lab, Stock Pools, and Strategy. Pages now always
filter to business (`user`) data only; acceptance/seed fixtures stay off the
operator surface. E2E fixtures updated to `data_purpose: 'user'`.

Verification: `npx tsc --noEmit` OK; frontend restarted on :4444.

## Watch Signal Cards + Chinese Symbol Names (2026-07-28)

1. Root cause: `/watch` signals rendered raw `SZ_000651` / `buy ·
   order_target_percent=1.0` as a flat log row; Chinese names already exist in
   PostgreSQL (`lookup_symbol_names`) but were never attached to watch evidence.
2. Backend `watch_context` now resolves `name` on signals/orders/trades/
   positions and returns `symbol_names`.
3. Frontend Watch signals rebuilt to BitPro SignalCenter card rhythm using
   `@bitpro/ui` `DataPanel` + `StatusBadge`: 买入/卖出 semantic color, 中文名 +
   `000651.SZ`, localized reason (`目标仓位 100%`), locale time, instance link.
4. Orders / trades / positions tables use the same Chinese `SymbolCell`.

Verification: backend attaches `SZ_000651→格力电器`; frontend/backend restarted;
`tsc` on changed watch files clean.

## Paper Instance Card Density (2026-07-28)

1. Compacted Paper strategy cards: removed fixed `min-h-[292px]`, tighter padding,
   inline meta/heartbeat row, label+value PnL row instead of stacked hero metrics,
   shorter action labels (暂停/关闭/详情), `h-8` buttons.

Verification: `npx tsc --noEmit` passed; frontend `4444` → 200.

## Data Page Symbol Chinese Names (2026-07-28)

1. Root cause: `/data` 研究数据「数据表统计」丢弃了 coverage 的 `name`，前端只渲染代码。
2. Backend `build_data_manager_table_stats` now keeps `name`; `kline_coverage` enriches
   blank/code-as-name rows via `lookup_symbol_names`; lookup maps digit codes back to
   `SH_/SZ_/BJ_` keys.
3. Frontend shows 中文名 as primary + `600000.SH` public code secondary in table stats
   and coverage matrix; shared `toPublicSymbol` / `resolveSymbolName` helpers added.

Verification: `npx tsc --noEmit` passed; frontend/backend restarted healthy;
`/data` 研究数据「数据表统计」标的列显示中文名 + 公开代码（如 `中科美菱` / `920992.BJ`）。

## Dashboard Market Pulse Cards (2026-07-28)

1. Removed duplicate homepage mini「短线指标」card that echoed the full short-line
   section; sentiment card no longer repeats the full up/down/flat grid.
2. Extended `/market/overview` with `market_pulse` from realtime stock cache:
   rise/fall ratio, median/avg change, ±5%/±7% bands, board-aware limit
   estimates, Top10 amount share, turnover/amplitude/volume-ratio stats.
3. Dashboard adds「大盘诊断」KPI row and「涨停生态」section (breadth metrics
   filtered out of short-line to avoid duplication); index strip now shows
   资金集中度 instead of the duplicate short-line teaser.

Verification: `pytest tests/test_market_overview_fast_path.py` 3/3 OK;
`npx tsc --noEmit` OK; services restarted/health OK; authenticated
`/api/market/overview` returns `market_pulse` on 5533 stocks (e.g. ratio≈0.90,
median≈-0.11%, limit_up_est=80). Note: realtime cache currently stores
turnover/amplitude/volume_ratio as 0, so those pulse fields stay `--` until
the spot sync populates them.

## Market 1Y K-line Backfill Started (2026-07-28)

Triggered `POST /api/data/history/sync-all` job `#46`
(`market-1y-backfill-20260728`): 243 trade days from 2025-07-28→2026-07-28,
`include_signals=false`. Early progress ~19/243 success (~5400 bars/day).

## Leader Strategy Research Top5 (2026-07-28)

1. Clarified research-20 pool: sealed `momentum_20d` Top20 on 2025-01-02, but
   factor coverage was limited to the 20 established large-caps that had a
   sealed 2023–2025 daily-bar history — so it is a research sample, not a live
   full-market leader list.
2. Screened current market leaders from `all_stocks_realtime` (amount / pct
   leaders: AI/光模块/半导体等活跃方向).
3. Created 8 dynamic 龙头 strategies on sealed pool#5 / dataset#10 / factor#4;
   all 8 formal backtests 2023-01-03→2025-01-02 succeeded with positive
   expectancy. Top5 by annualized return:
   - 动量龙头Top1 38.70%
   - 相对强度龙头Top1 38.55%
   - 振幅突破龙头Top1 33.73%
   - 强势近板龙头持5日 25.67%
   - 相对强度三龙头 25.11%

Verification: 8/8 strategy create=`valid`; 8/8 `/api/backtest/runs` success.

## Paper Dashboard False -100% Equity (2026-07-28)

1. Root cause: new Paper instances had no equity snapshot (`equity=null`) while
   cash still equalled initial capital; dashboard used `Number(null)===0`, so
   PnL rendered as `-initial` / `-100%` with zero fills.
2. Fixed `numberValue` null handling, fall back display equity to
   `cash_balance`/`initial_cash`, and coalesce the same in Paper list/detail APIs.

Verification: `tsc --noEmit` OK; API list now returns equity=`1000000` for
cash-only instances; services restarted/health OK.

## Data Module Full-Market Sync + Daily Schedule (2026-07-28)

1. Added date-based full-market daily K-line path: TuShare `daily(trade_date=…)`,
   `KlineSyncService.create_market_daily_sync_job`, and
   `POST /api/data/history/sync-all` (default ~365d + optional market-evidence
   signal backfill).
2. Daily reference orchestration now pulls one market day instead of ~5k
   per-symbol jobs; `force=True` bypasses a disabled PG schedule for recovery.
3. Scheduler catchup walks recent open days (`catchupDays`); local
   `ENABLE_SCHEDULER=true`. Data Center wires 全量下载 / 盘后日终计划 /
   立即运行日终 to `/history/sync-all` and `/schedules/daily`.

Verification: daily-reference unit tests 11/11 OK; `npx tsc --noEmit` OK;
services restarted; `/api/health/health` healthy; schedules/daily shows
`runtimeStatus=running`; smoke `POST /history/sync-all` job#45 (2 trade days)
status=success in ~5s. Full 365d operator download not executed in this session.

## A-share Profitability Strategy Research + Paper Deploy (2026-07-28)

1. Inventoried StockPro HTTP + `stockpro-mcp-v1` tools and TuShare-backed
   sealed datasets (`daily_bars`, valuation, limits, factors, pools).
2. Screened momentum / relative-strength / strong-breakout / volatility-breakout
   / factor-combo logics on sealed research-20 pool; formal full backtests
   2023-01-03→2025-01-02 produced 15 strategies with ann≥20% and positive
   expectancy (win_rate × PL ratio).
3. Promoted and started top-10 Paper instances against dataset#10 /
   factor#4 / universe#1 / pool#5 / protocol `01b64adf-…`.
4. Produced next-session entry zones from latest common bar date 2026-07-16
   (most pool symbols; two banks fresher to 2026-07-27).

Verification: 22 strategy full runs succeeded via `/api/backtest/runs`; 10/10
promotion=`paper_eligible` and Paper `running`. No live broker actions.

## Stock Pool Workbench Clarity (2026-07-28)

1. Clarified product purpose: pools turn screening into reproducible,
   reason-tagged, expiring candidates for backtest handoff.
2. Added workflow strip (建规则 → 生成成员 → 封存快照 → 送回测), KPI row, and
   mine-tab “下一步做什么” coach with contextual actions.
3. Creation tabs lead with type purpose + tip + steps; evidence shows
   `Factor #` / `Market #`; seal message uses `快照 #id`. Kept six `?tab=` keys.

Verification: `npx tsc --noEmit` passed; frontend `4444` → 200; backend health
healthy; browser on `/pools` shows workflow strip + next-action coach;
`/pools?tab=factor` shows type purpose tip and create form.

## Short-line Metric Tone Semantics (2026-07-28)

1. Root cause: Dashboard short-line KPI values were hard-coded `tone="amber"`,
   so 涨停/跌停/上涨/下跌 all rendered yellow.
2. Added `shortLineValueTone(code, value)`: up→red, down→green, broken/highest
   board→amber, seal_rate→blue, rise_fall_ratio by threshold.
3. Tightened DailyReview risk/trade and FactorLibrary summary tones so
   operational counts stay blue/green/red instead of blanket amber.

Verification: live DOM on `/` shows 涨停/上涨 `#FF1744`, 跌停/下跌 `#00C853`,
炸板/最高板 amber, 封板率 blue; `tsc --noEmit` passed.

## Sidebar Nav Color Parity With BitPro (2026-07-28)

1. Matched primary menu to BitPro `MainLayout` nav tokens: idle `text-gray-400`,
   hover `text-gray-200` + `bg-gray-800`, active `text-blue-500` +
   `bg-blue-500/10` — removed white / near-white menu labels.
2. Aligned shell aside to `bg-crypto-card` / `border-crypto-border`; settings /
   logout use the same gray→blue idle/active treatment.
3. Softened `WorkspaceTabs` active label from `text-white` to `text-blue-400`.

Verification: `npx tsc --noEmit` passed; frontend `4444` → 200; backend health
healthy. No backend code change.

## Global White KPI Purge (2026-07-27)

1. Contract: KPI / metric numbers must never use flat white / near-white
   (`text-white`, `text-slate-100`, `@bitpro/ui` `bp-tone-neutral` ≈ `#edf2f8`).
2. Shared guardrails: CSS maps `bp-tone-neutral|gray` → `#93c5fd`;
   `OperatorMetricCard` wraps string/number values in `MetricValue` and remaps
   `neutral` → `blue`; Paper runtime `Metric` defaults to blue tone.
3. Pages/components recolored: Dashboard short-line + index cards, Market price,
   MarketResearch ladder level, DailyReview KPIs, FactorLibrary summary,
   AIResearchLab pipeline counts, SentimentAnalysis StatCard (static tone map),
   AIStockAnalysis scores, DataCenter MetricCards + coverage rows,
   DataQuality/DataHub/BatchImport counts, StockPools member_count,
   BitProDetailPanels price/qty, ChartPanel change color.

Verification: `npx tsc --noEmit` passed; backend `/api/health/health` + frontend
`4444` restart follows. Titles / buttons / names intentionally keep white.

## Market Sentiment KPI Contrast Fix (2026-07-27)

1. Root cause: `MarketResearch` Sentiment tab KPI values were hard-coded
   `text-slate-100` (near-white), so earlier shell/token work never reached
   this grid — matching the user screenshot (涨停/跌停/炸板/连板高度…).
2. Wired Sentiment metrics + pool counts through `MetricValue` with
   up/down/amber/blue tones; Structure headline values now also carry explicit
   tone classes (not only MetricCard inheritance).

Verification: frontend restart `4444` → 200; backend `/api/health/health` → healthy;
`tsc --noEmit` passed; live DOM on `?tab=sentiment` shows KPI colors
`#FF1744` / `#00C853` / amber / blue (no longer near-white).

## BitPro Metric Contrast And Token Alignment (2026-07-27)

1. Matched Tailwind / CSS tokens to BitPro: up `#FF1744`, down `#00C853`,
   accent `#58a6ff`, Inter-first font stack, mono tabular KPI values.
2. Added `MetricValue` / `OperatorMetricCard` and expanded `marketColors`
   helpers (`thresholdTone`, `countTone`) so KPI numbers never default to flat
   white.
3. Recolored Backtest detail KPIs (returns up/down, drawdown adverse, Sharpe
   threshold), Paper/Watch/Monitor/Dashboard/Data counts and PnL, and local
   detail MetricCards to BitPro semantic tones.

Verification: `tsc --noEmit` passed; frontend/backend restart follows.

## BitPro UI Density — Shell Rollout Across Subpages (2026-07-27)

1. Strategy detail now carries `data-operator-page` and an `EvidenceStrip` for
   version / validation / dependency / symbol facts.
2. Backtest dashboard uses shared header + segmented/filter chips; detail uses
   `WorkspaceTabs` for all eight nested report tabs plus an evidence strip.
3. Paper dashboard preferred/all views use `SegmentedControl`; Paper/Watch/
   Monitor/Review/Market/Pools/Factors/AI Lab/Dashboard/Data pages share
   `OperatorPageHeader` and `data-operator-page` markers so every L2 surface
   sits under one shell rhythm.
4. Watch/Monitor scopes moved onto `SegmentedControl` + `EvidenceStrip`.
5. AdminLogin admin/guest modes and `/data/processing` L2/L3 tabs now use the
   shared segmented shell.

Verification:

- `npx tsc --noEmit` passed.
- `git diff --check` clean.
- Clean restart: backend health `healthy`, frontend `4444` → 200.

Next: deepen intra-tab panel/KPI/table density against BitPro `docs/pages/*`
(Backtest wizard + Paper detail modules first). Shell layer for all inventory
routes including AdminLogin and `/data/processing` is in place.

## BitPro UI Density — All Subpages (2026-07-27)

1. Activated `docs/contracts/active-bitpro-ui-density.md` (also mirrored as
   `docs/contracts/active.md`) requiring every L1 **and every L2/L3 surface** to
   match BitPro operator density. Superseded
   `active-research-workshop-page-hardening.md` while retaining its honest
   data-state Done Means.
2. Documented the BitPro read-only reference at
   `/Users/jie.feng/Dev/Github/Private/BitPro` and expanded `docs/spec.md`
   BitPro UI Contract to cover nested tabs, wizards and detail modes.
3. Added shared shell primitives in `frontend/src/components/OperatorShell.tsx`:
   `OperatorPageHeader`, `SegmentedControl`, `FilterChipGroup`,
   `OperatorFilterBar`, `OperatorSearchField`, `EvidenceStrip`,
   `OperatorStatePanel`, `CatalogueCard`.
4. Tightened `WorkspaceTabs` density markers for all URL/`local` L2 tabs.
5. Migrated Strategy centre list surfaces (`我的策略` / `策略广场`, filters,
   loading/empty/error, catalogue cards) onto the shared shell as the template
   page. Editor modal and detail panel remain next within the Strategy batch.

Verification:

- Frontend `tsc --noEmit` passed after Strategy shell migration.
- ESLint on touched files: 0 errors (1 pre-existing hooks warning on Strategy).
- `git diff --check` clean.
- Clean restart: backend `http://127.0.0.1:4445/api/health/health` → healthy;
  frontend `http://127.0.0.1:4444` → 200. No provider sync or Paper cycle ran.

Next batch: Strategy editor/detail polish, then Backtest + Paper (dashboard /
wizard / detail nested tabs / preferred-all), with every listed subpage checked
at desktop and 390px.

## Cross-page Chinese Presentation Cleanup (2026-07-27)

1. Replaced raw market source-map keys, provider table names, snapshot types and
   publication states with concise Chinese business labels.
2. Added shared presentation mappings for runtime status, source, category,
   snapshot type, trade direction and order type; Market, Review, Monitor, Watch,
   Backtest, Factors and Data Hub now reuse them.
3. Normalized ordinary `font-mono` content to the Chinese-first operator font
   stack while retaining tabular numerals; code blocks and editors remain
   monospaced.
4. Removed visible evidence references, content hashes and English snapshot
   abbreviations from the market, factor, stock-pool and backtest workspaces.

Verification:

- Real authenticated desktop and 390px browser inspection confirmed the market
  snapshot renders Chinese source labels and no raw `tushare_*`, evidence-ref,
  content-hash, `Universe`, `DS #` or `U #` strings.
- `./scripts/check.sh` passed production build, lint with 7 existing warnings and
  0 errors, deploy shell syntax, all 289 backend tests and Python compilation.
- Local frontend/backend are listening on `127.0.0.1:4444` and `:4445`; backend
  health reports `healthy`. No remote deployment or provider synchronization ran.

## BitPro-parity Final Local Acceptance (2026-07-27)

1. Re-audited the existing PostgreSQL daily publication chain: persisted cron,
   TuShare trade-calendar gate, advisory lock, required reference partitions,
   Universe, daily bars, immutable dataset snapshot, optional market evidence and
   factor scheduling are already implemented and contract-tested.
2. Added a permanent real-backend read-only browser gate for all twelve primary
   routes. It checks the authenticated document, shared workflow navigation and
   browser runtime without creating or mutating research/runtime objects.
3. Confirmed twelve core read APIs return `200`: workflow, market overview and
   research context, pools, factors, strategy, backtests, Paper, Watch, Monitor,
   Review and the daily Data schedule.
4. Preserved the explicit operations boundary: the PG daily plan is enabled, but
   `ENABLE_SCHEDULER` is false, no APScheduler job is registered and no effective
   next run exists. No provider sync, backfill or Paper cycle was started.

Verification:

- Real 12-page read-only Playwright passed 1/1 with the local administrator.
- Daily plan: configured next run `2026-07-28 17:30 Asia/Shanghai`, runtime
  `runner_offline`, effective next run unavailable, daily-bars watermark
  `2025-01-02`.
- Runtime evidence remains truthful: Watch `stale` with source update
  `2026-07-17T02:42:47.409905Z`; Monitor `critical` with source update
  `2026-07-16T14:15:08.518862Z`.
- `./scripts/check.sh` passed production build, lint with 7 existing warnings and
  0 errors, deploy shell syntax, 287 backend tests and Python compilation.
- Full mock browser regression passed 33/33 applicable tests; 12 write-capable or
  explicit real-suite cases remained skipped by default.

Remaining operator action: enabling the scheduler and any catch-up synchronization
requires explicit approval because it will call providers and write new market
data. Real-broker execution remains outside the approved local scope.

## BitPro-parity Runtime Evidence (2026-07-27)

1. Expanded the PostgreSQL Watch context from signals and alerts to the complete
   Paper evidence path: orders, trades, positions, risk decisions and runtime
   events, with instance links and bounded coverage counts.
2. Added per-instance Monitor health with heartbeat freshness, last cycle and
   errors, latest equity/drawdown, ledger difference, order/trade/risk counts and
   acceptance/seed/user purpose labels.
3. Separated persisted `source_updated_at` from `response_generated_at`; missing
   financial values stay unavailable while SQL counts remain truthful.
4. Added Watch order/trade/position/risk tables and Monitor strategy-health/risk
   detail panels without adding trading controls or provider requests.
5. Promoted Watch and Monitor in `stockpro-workflow-v1` only after the complete
   runtime evidence model and UI were verified.

Verification:

- Existing PostgreSQL evidence was read without running a Paper cycle or provider
  sync: 3 instances, 3 orders, 2 trades, 2 positions, 12 risk events and 105
  runtime events.
- Real Watch returned `stale` with latest persisted evidence at
  `2026-07-17T02:42:47.409905Z`.
- Real Monitor returned `critical`: two acceptance instances still marked
  running have stale heartbeats from 2024-12-23 and 2025-01-02; the stopped
  acceptance instance remains explicitly stopped.
- Focused backend API tests passed 13/13; focused mocked Playwright verified the
  execution-evidence and per-instance health workspaces.
- `./scripts/check.sh` passed the production build, lint with 7 existing warnings
  and 0 errors, deploy shell syntax, all 287 backend tests and Python compilation.
- Full mocked Playwright passed 33/33 applicable tests; 11 real-backend cases
  remained intentionally skipped without the explicit real-suite environment.

Next Sprint: daily PostgreSQL orchestration, freshness publication and final
cross-page BitPro-parity acceptance without enabling real-broker execution.

## StockPro Agent Tool Interface (2026-07-27)

1. Added the stable `stockpro-mcp-v1` local stdio interface with 20 PostgreSQL-backed read tools and three asynchronous backtest mutation tools.
2. Added PostgreSQL Agent tokens with one-time plaintext return, SHA-256 hash-only storage, administrator list/revoke controls and an in-product Agent access manager.
3. Added R/W scope enforcement, method/path tool allowlisting, mandatory mutation idempotency keys and PostgreSQL authorization/denial audit evidence. W tokens cannot call data synchronization, arbitrary Paper control or unlisted application routes.
4. Exposed A-share capability discovery, health, market evidence, strategy, backtest jobs/results, Paper, Watch, Monitor, Review and Data state without adding provider fetches or synthetic fallbacks.
5. Kept remote MCP and all real-broker diagnostics/mutations absent and explicitly reported `real_broker_available=false`.

Verification:

- Applied local PostgreSQL migrations `202607270003` and `202607270004` for Agent access and Agent-owned backtest jobs; no provider synchronization or historical backfill ran.
- Real Agent HTTP verification: R read `200`, R write `403`, R/W async job `202 -> success`, duplicate idempotency key `409`, out-of-contract data sync `403`, and revoked token `401`.
- Real stdio MCP handshake discovered 23 tools and successfully called `stockpro_capabilities` and `stockpro_health`; all acceptance tokens were revoked and no active token remains.
- Focused backend tests passed 13/13; TypeScript and focused lint passed; Playwright verified the administrator Agent Token manager and R/W evidence.

Next Sprint: close the remaining BitPro parity gaps in daily data orchestration and Paper/Watch/Monitor runtime evidence.

## BitPro-parity Asynchronous Backtest Jobs (2026-07-27)

1. Added PostgreSQL-owned backtest jobs and append-only transition logs with owner role/session, guest invitation usage, request payload, attempt lineage and immutable result linkage.
2. Added bounded local execution with persisted pending/running/cancelling/cancelled/success/failed/interrupted states, progress phases, cooperative cancellation, retry as a new attempt and startup interruption recovery.
3. Bound guest daily, concurrent and date-range quotas to the asynchronous lifecycle while retaining the existing synchronous routes during migration.
4. Replaced browser-blocking Backtest execution with `202` job creation and a polling task console that shows progress, status, errors, incremental logs, stop/retry controls and the sealed result entry.
5. Declared asynchronous jobs and the Backtest workflow stage available only after the PostgreSQL implementation and UI were verified.

Verification:

- Applied the local async-job migration; no provider synchronization or historical backfill ran.
- A real quick acceptance job returned `202/pending`, completed in about 0.6 seconds, persisted 13 phase logs and linked job `4cb5430f-b503-4af8-a458-6d182fdfbb1b` to sealed run `8fe78fc5-147b-45f2-8dfa-2ee73c063071`.
- Focused backend tests passed 6/6; TypeScript and focused lint passed; mocked Playwright verified the persisted task console, job logs and result evidence entry.
- Clean frontend/backend restart completed; ports `4444` and `4445` listened, health returned healthy and startup recovery found no interrupted jobs.

Next Sprint: authenticated `stockpro-mcp-v1` agent interface with capability discovery, read-only research tools and explicitly gated mutations.

## BitPro-parity Access Control (2026-07-27)

1. Added PostgreSQL-backed invitation codes, guest backtest usage and authentication audit evidence. Invitation plaintext is returned once; only its hash is stored.
2. Generalized the authenticated API boundary to administrator and guest principals. Guests can read all authenticated pages, while non-backtest mutations are rejected with `403`.
3. Added date-range, daily-run and concurrent-run quota reservation around all three supported backtest entrypoints. Rejections return `429` before the engine starts; attempts and outcomes remain attributable to the invitation and session.
4. Added guest login, role/permission/session introspection, immediate revocation, administrator invitation management and workflow capability reporting.
5. Added a persistent guest permission banner, frontend mutation gate and visible disabling of known write actions. Read-only explanation and navigation controls remain usable; backtest run controls remain available under quota.
6. Kept `stockpro-mcp-v1`, asynchronous backtest jobs and real-broker execution explicitly outside this Sprint.

Verification:

- Applied local PostgreSQL migrations only; no provider synchronization or historical backfill ran. `/api/health/storage` reported PostgreSQL healthy with all 26 migrations applied.
- Real API verification: guest login/read `200`, data synchronization write `403`, over-range backtest `429`, invitation revoke `200`, and the issued guest token then returned `401`.
- Focused authentication/router tests passed 9/9; TypeScript check passed; lint completed with the existing 7 warnings and 0 errors.
- Playwright verified invitation-prefilled guest login, 390×844 guest Data page, quota banner, disabled data/provider write controls, usable read-only explanation, administrator invitation manager and zero application console errors.
- `./scripts/check.sh` passed production build, lint with 7 existing warnings and 0 errors, deploy shell syntax, all 276 backend tests and Python compilation.

Next Sprint: asynchronous PostgreSQL backtest jobs with status, logs, cancellation, retry and guest concurrency ownership.

## BitPro-parity Workflow Foundation (2026-07-27)

1. Added the authenticated, read-only `stockpro-workflow-v1` capability contract with the canonical Strategy -> Backtest -> Paper -> Watch -> Monitor -> Review stage order.
2. Separated code capability from runtime/data availability and exposed truthful `available`, `partial`, `disabled` and `not_implemented` states for authentication, scheduler, provider access, asynchronous backtests and broker execution.
3. Added one shared lifecycle rail across Strategy, Backtest, AI Lab, Paper, Watch, Monitor and Review. The rail has stable loading/error states and links every stage through the same workflow vocabulary.
4. Renamed the first-level Paper entry to `模拟交易` and permanently labels the current execution scope as `仅模拟盘 / 实盘未接入`; no page shell implies that a real broker is connected.
5. Preserved the A-share domain boundary: calendar/session, long-only, T+1, 100-share lots, price limits, suspension/ST, corporate actions and A-share cost semantics remain explicit.

Verification:

- Clean frontend/backend restart completed; ports `4444` and `4445` listened and `/api/health/health` returned healthy.
- Authenticated `GET /api/workflow/capabilities` returned the six canonical stages, `paper_only`, broker disabled and scheduler disabled; unauthenticated access returned `401`.
- Focused backend contract/router tests passed 4/4 and focused mocked Playwright passed 1/1.
- Authenticated real-backend desktop Strategy and 390×844 Paper checks showed the same lifecycle rail, truthful execution badges and no application console error.
- `./scripts/check.sh` passed production build, lint with 7 existing warnings and 0 errors, deploy shell syntax, 274 backend tests and Python compilation.
- BitPro HTTP health remained available, but the supplied external administrator credentials returned `401`; authenticated BitPro data/action inspection remains pending valid access.

Next Sprint: admin/guest/agent capability-based access and guest backtest quotas.

## Research Workshop Page Hardening — BitPro Backtest Console (2026-07-27)

1. Reworked the Backtest landing page against the local BitPro backtest module: compact instance-console header, create action, mode/status counters, global sorting, list-local search, refresh/compare actions, and dense instance cards with return, Sharpe, drawdown, win rate, trade count, status, detail, and log actions.
2. Moved StockPro's immutable strategy, dataset, Universe, factor, stock-pool, cost-model, protocol, date, capital, benchmark, and parameter inputs into a three-step `strategy -> configuration -> evidence confirmation` wizard instead of exposing one oversized form above the instance list.
3. Preserved StockPro's A-share evidence contract rather than copying BitPro business code: each run keeps snapshot lineage, A-share T+1/lot/limit/suspension execution rules, acceptance/seed labels, missing-value states, comparison eligibility, quick/full distinction, and the existing eight-tab result detail.
4. Kept the parameter matrix in the confirmation step as an optional advanced experiment, while making the ordinary single-run path match BitPro's staged creation flow.
5. Fixed responsive card composition after desktop inspection and converted the wizard to a flex shell with independently scrolling content, so its footer actions remain visible at 390×844.

Verification:

- Clean frontend/backend restart passed; ports `4444` and `4445` listened and `/api/health/health` returned `healthy`.
- `npm run check`, lint, and production build passed.
- Focused mocked Playwright passed 3/3 Backtest workflow and result-detail cases.
- `./scripts/check.sh` passed the production build, lint with 7 existing warnings and 0 errors, deploy shell syntax, 272 backend tests, and Python compilation.
- Authenticated real-backend inspection loaded 11 persisted runs without creating a run or calling a provider.
- Desktop and 390×844 console/wizard screenshots were captured under `output/playwright/`; compact KPI alignment and the fixed mobile wizard footer were visually verified.

Next page: AI Research Lab.

## Dashboard Short-line Evidence Fallback (2026-07-27)

1. Fixed the empty Short-line panel caused by the API discarding every cache older than 36 hours even when a published market-evidence snapshot remained available.
2. The read-only endpoint now prefers a valid realtime cache and otherwise derives eight indicators from the latest sealed all-A snapshot: limit up/down, broken boards, highest board, advancing/declining counts, seal rate, and rise/fall ratio.
3. Historical values carry their snapshot ID, trade date, source, definition, unit, and `sealed_snapshot` state. The Dashboard labels them `历史快照` and never presents them as realtime monitoring.
4. Replaced internal metric/source identifiers with decision-oriented groups and reader-facing TuShare evidence labels. The expanded two-row layout keeps counts, board height, rates, breadth, definitions, and sources visible.

Verification:

- Clean frontend/backend restart passed; both ports listened and `/api/health/health` returned `healthy`.
- The real API returned 8 sealed indicators from snapshot #7 for trade date 2025-01-02.
- Focused backend tests passed 9/9; focused Dashboard browser tests passed 4/4.
- `npm run check` and focused Dashboard lint passed.
- `./scripts/check.sh` passed the production build, lint with 7 warnings and 0 errors, deploy shell syntax, 272 backend tests, and Python compilation.
- Authenticated desktop and 390px browser checks completed with zero console errors and no document-level horizontal overflow.

Next page: Strategy Development.

## Product Goal — BitPro-parity A-share Strategy Lifecycle (2026-07-27)

1. The user confirmed BitPro's strategy module as the complete behavioral and process baseline for StockPro strategy development.
2. The required journey is catalogue/search/filter -> strategy detail -> validation -> immutable create/version iteration -> backtest job and evidence -> Paper eligibility/configuration/lifecycle -> runtime evidence -> monitor/review.
3. StockPro changes the asset-domain adapter only: A-share symbols, boards, calendar/sessions, long-only default, T+1, 100-share lots, price limits, suspension/ST rules, corporate actions, A-share costs and liquidity/capacity controls replace crypto exchange, 24x7, spot/swap, leverage, funding and long/short assumptions.
4. The product specification and active page-hardening contract now make this parity goal testable across Strategy, Backtest, Paper, Monitor and Review. Real broker execution remains outside scope pending a separate contract and explicit authorization.

Verification:

- Read the current BitPro `bitpro-mcp-v1` capabilities and healthy service state, and inspected the live strategy catalogue shape, filters, statuses, version/config metadata and Paper linkage without performing any mutation.
- Documentation-only change; no frontend/backend restart or provider/database write was required.

## Data Integrity Remediation — Read-only Completion (2026-07-27)

1. Page GET paths are PostgreSQL-only and write-free. Removed hidden factor-library seed installation and legacy strategy-version creation from GET endpoints; provider fetches remain behind explicit synchronization actions.
2. Qwen capability is explicit. With no `QWEN_API_KEY`, AI analysis returns `503`, Strategy disables AI generation, and AI Lab distinguishes deterministic templates from AI.
3. Existing Sprint, QA, smoke, fixture and seed assets expose derived `data_purpose` labels without a schema migration. Strategy, Backtest, Pool, Paper and AI research surfaces display those labels.
4. Market auxiliary failures degrade independently. Empty news and calendar caches explain that absence is not evidence of no event; historical market evidence exposes stale freshness.
5. Watch exposes PostgreSQL source time and stale/empty/fresh state. Monitor no longer reports healthy without service-health evidence. Review no longer defaults to a hard-coded trade date.
6. Twenty-two primary read endpoint groups returned `200`; hashes for eleven key research/runtime tables were unchanged before and after the complete real-backend read sweep.

Verification:

- `./scripts/check.sh` passed: production build, lint with 8 warnings and 0 errors, 271 backend tests, and Python compilation.
- Mock browser regression passed 29 application tests with 11 write-oriented real-backend tests skipped; the final cross-page and AI capability checks passed.
- Authenticated read-only browser inspection covered all twelve primary routes with explicit stale, historical, acceptance, not-configured, critical and scheduler-offline states.
- Frontend and backend were cleanly restarted with migration, bootstrap, scheduler, realtime, strategy execution and external market fetch disabled; both ports and backend health passed.
- No migration, provider synchronization, historical backfill, strategy creation, backtest run, Paper mutation or immutable evidence regeneration ran.

Remaining data operation: refreshing the July 16–17 market caches, probing restricted provider endpoints and regenerating current sealed research evidence require explicit approval because they write PostgreSQL and may perform large external synchronization.

## Research Workshop Page Hardening — Market Research (2026-07-27)

1. Reviewed all six Market Research workspaces against the real PostgreSQL-backed snapshot: structure, sectors, sentiment/limit-up, events, calendar, and stock research.
2. Bound the embedded Stock terminal to the selected research trade date. Hot concepts and concept leaders now receive that date, while K-lines are additionally clipped in the browser to prevent a later cache row from leaking into a historical study.
3. In research mode, the displayed price and daily change come from the final two bars at or before the cutoff. Current fundamentals can still provide a security name, but can no longer override historical price evidence.
4. Replaced the ambiguous duplicated date with explicit `研究截止` and `K线至` labels, and normalized internal `SH_600000` identities to public `600000.SH` notation.
5. Market-terminal requests now degrade independently: a fundamentals failure does not blank a usable K-line chart, and a concept-leader failure leaves an honest empty/fallback state.

Verification:

- Clean frontend/backend restart passed; ports `4444` and `4445` listened and `/api/health/health` returned `healthy`.
- `npm run check` and focused Market/Market Research lint passed.
- Focused mocked Playwright passed the six-workspace and historical-cutoff regression.
- `./scripts/check.sh` passed the production build, lint with 7 warnings and 0 errors, deploy shell syntax, 271 backend tests, and Python compilation.
- Full mocked Playwright passed 30/30 application tests; 11 write-capable real-backend tests were skipped as designed.
- Authenticated real-browser inspection showed the 2025-01-02 research snapshot with 485 bars ending on 2025-01-02, zero console errors, and no document-level horizontal overflow.
- Desktop and 390px Stock-terminal screenshots were captured under `output/playwright/`; the mobile document width matched the viewport and exposed no 2026 market row.

Next page: Strategy Development.

## Data Integrity Remediation — Sprint A P0 Truthfulness (2026-07-27)

1. The persistent top bar now consumes explicit stock/index freshness states. Existing July 16-17 caches render stale with their source date instead of the former green available state.
2. Home overview separates response generation time from source update time and no longer invents neutral sentiment `50` or volume ratio `1.0` when evidence is absent.
3. The Market Stock terminal no longer generates an AI prediction, synthetic order book, spread, unsupported timeframe selection or zero price/change fallback. Daily and intraday chart GETs now read PostgreSQL only.
4. Concept-leader page reads return only the stored cache. A cache miss no longer calls a provider or writes a cache row.
5. Pool lists expose the latest successful generation's actual dataset, Universe, factor and market-evidence foreign keys. The page separates current-member evidence from prospective next-generation inputs.
6. Data distinguishes a persisted enabled schedule from the current process runtime. With `ENABLE_SCHEDULER=false`, the effective next run is unavailable and the page states that the configured time will not execute.

Verification:

- Clean scheduler/realtime/strategy/provider-disabled backend startup and frontend restart passed; both local ports and the health endpoint were available.
- Frontend TypeScript check passed after every runtime slice.
- 38 focused backend tests plus 13 subtests passed for market truthfulness, chart/provider-free reads, Pool lineage, schedule runtime state and startup/read-only safety.
- No migration, provider synchronization, historical backfill or immutable-record rewrite ran.

Next slice: finish the page-GET provider boundary and expose provider/runtime availability without enabling synchronization.

## Cross-page Product Copy Cleanup (2026-07-27)

1. Audited every primary routed page and shared strategy detail surface for development notes, internal API labels, database-mechanism explanations, provider-read disclaimers, debug terminology, future-work commentary, and low-value manifest/hash fields.
2. Removed the Strategy implementation-status strip shown in the user screenshot and applied the same product-copy standard to Market, Pools, Factors, Backtest, AI Lab, Paper, Watch, Monitor, Review, Data Center, and shared detail panels.
3. Retained data source, trade date, freshness, simulation mode, stale state, and the no-real-broker warning where they directly affect financial interpretation or action safety.
4. Replaced raw `sealed_pg_snapshot` / `recorded_replay` values with product labels and cleaned the built-in reference strategies without rewriting user-created strategy content.
5. Added cross-route browser assertions that reject the identified implementation-copy patterns and updated affected workflow tests.

Verification:

- Clean frontend/backend restart passed; ports `4444` and `4445` listened and `/api/health/health` returned `healthy`.
- `./scripts/check.sh` passed: frontend production build, lint with 9 existing warnings and 0 errors, deploy shell syntax, 260 backend tests, and Python compilation.
- Full mocked Playwright passed 29 application tests; 11 real-backend tests were skipped by mock mode as designed.
- Authenticated real-browser inspection confirmed the Strategy page no longer renders the screenshot strip or seeded API/framework commentary.
- Desktop and 390px browser snapshots passed with the cleaned built-in strategy names and descriptions.

Next page-hardening slice: Stock Pools.

## Data Integrity Remediation Started (2026-07-27)

1. Expanded the active Research Workshop Page Hardening slice to implement the accepted audit plan across all twelve primary routes.
2. Fixed delivery order: remove misleading presentation first, then harden synchronization boundaries, research evidence, cross-page data states and automated regression coverage.
3. Preserved the existing local-only safety boundary. No provider synchronization, historical backfill, scheduler enablement, migration execution or immutable evidence regeneration is authorized by this implementation step.

Next slice: global market freshness, the Market Stock terminal, Pool evidence binding and Data scheduler runtime truth.

## Research Workshop Page Hardening — Dashboard (2026-07-27)

1. Preserved the current explicit stale/unavailable market states and verified that expired THS, breadth, short-line, and sector caches do not become current signals.
2. Removed the Dashboard `DataPanel` composition that emitted a React missing-key warning and retained the same financial-operator hierarchy with a stable native section header.
3. Hot-sector fund-flow values now say `单位未记录` because the legacy cache stores a raw numeric value without unit metadata; the page no longer invites users to assume yuan, ten-thousand yuan, or hundred-million yuan.

Verification:

- Clean frontend/backend restart passed; both ports listened and `/api/health/health` returned `healthy`.
- `npm run check` and focused `Dashboard.tsx` lint passed.
- Focused mocked Playwright passed 3/3 Dashboard cases.
- Authenticated desktop and 390px browser inspection completed with zero console errors and no page-level horizontal overflow.

Next page: Market Research.

## Research Workshop Page Hardening — Stock Pools (2026-07-27)

1. Split `我的股票池` into a real versioned-rule catalogue instead of showing the condition-builder under every tab. Factor, condition, sector, and event creation retain their own rule inputs.
2. Replaced blind first-item snapshot mixing with compatibility-aware generation binding. Factor pools inherit Dataset/Universe from the sealed factor snapshot; sector/event pools require same-date market evidence.
3. Current member evidence is distinct from the prospective inputs for the next generation. Factor pools no longer display an unrelated market-evidence snapshot.
4. Pool, snapshot, configuration, market-evidence, and member requests degrade independently. A market-evidence failure leaves existing pools inspectable and blocks only affected generation actions.
5. Member symbols render in canonical public notation such as `600519.SH`; expired validity windows are visible instead of looking current.
6. Added truthful loading, member-error, no-generation, empty-catalogue, and empty-snapshot states. Type-specific selectors cannot default to an incompatible rule type.

Verification:

- Clean frontend/backend restart passed; ports `4444` and `4445` listened and `/api/health/health` returned `healthy`.
- `npm run check` and focused `StockPools.tsx` lint passed.
- Focused backend Stock Pool tests passed 27/27.
- Focused mocked Playwright passed 2/2 Stock Pool cases, including a 390px optional-market-evidence failure.
- Authenticated browser inspection covered all six tabs with zero console errors.
- Desktop and 390px screenshots were captured under `output/playwright/`; the mobile page width matched the viewport.

Next page: Dashboard.

## Research Workshop Page Hardening — Factor Research (2026-07-27)

1. Replaced the five equal-width headline cells with three decision-oriented areas: factor asset readiness, evaluation maturity, and the current immutable research batch.
2. Research date, dataset snapshot, historical Universe, and knowledge cutoff now have separate labels. The 2025-01-02 batch is explicitly marked as a historical sample instead of appearing current.
3. Factor library, compute-run, correlation, metric, and value requests now degrade independently; an optional correlation failure no longer blanks usable factor data.
4. Added truthful empty states for factor filters, runs, correlations, and values, plus request-race protection when switching factors.
5. Normalized the public factor-value API symbol format from internal `SH_600030` notation to the documented `600030.SH` notation while preserving invalid stored identities for diagnosis.
6. Reused the shared `@bitpro/ui` status semantics and retained the StockPro financial operator tokens without copying BitPro business layouts.

Verification:

- Clean frontend/backend restart passed; ports `4444` and `4445` listened and `/api/health/health` returned `healthy`.
- `npm run check` passed.
- Focused mocked Playwright passed 2/2 factor-research cases, including optional-correlation failure at 390px.
- Focused backend tests passed 26/26.
- Authenticated real-backend inspection covered all six factor workspaces with zero browser console errors.
- Real factor-value API returned canonical symbols including `600030.SH` and `600519.SH`.
- Desktop and 390px browser screenshots were captured under `output/playwright/`; the mobile document width matched the 390px viewport.
- Repository-wide lint remains blocked by four pre-existing unused-variable errors in `StockPools.tsx` and `Strategy.tsx`; no Factor Research lint error remains.

Next page: Stock Pools.

## Market Research KPI Presentation (2026-07-27)

1. Replaced the six manually styled Market Structure metrics with the shared `@bitpro/ui` `MetricCard` primitive and kept the A-share convention: up/limit-up in red, down/limit-down in green, highest board in amber, and seal rate in blue.
2. Removed the raw English display suffixes (`stocks`, `boards`, `percent`); counts now use compact tabular numbers and the rate retains only `%`.

Verification:

- `npm run check` passed.
- Focused mocked Market Research Playwright coverage passed, including unit-free values and semantic card colour classes.
- `./scripts/check.sh` passed the production build, lint (9 existing warnings, 0 errors), deploy shell syntax, 260 backend tests and Python compilation.
- Authenticated browser inspection covered desktop and 390px mobile layouts with the current published snapshot.

## Persistent Top Market Ticker (2026-07-27)

1. Moved the lazy-page `Suspense` boundary into the `MainLayout` content viewport so route bundle loading no longer replaces the operator shell.
2. Changed the admin guard to validate once when entering the protected workspace instead of returning to `checking` on every pathname or query-string change.
3. Added a browser regression that switches Strategy → Backtest → Paper and proves the top ticker remains the same DOM node while `/api/market/overview` request count stays unchanged.

Verification:

- `npm run check` passed.
- `npm run lint` passed with 9 warnings and 0 errors.
- The focused ticker lifecycle browser test passed.
- Full mocked Playwright passed 28 application tests; 11 write-capable real-backend tests were skipped as designed.

## Snapshot (2026-07-17)

- Sprint: no active sprint; BitPro-style A-share Strategy Workbench completed locally
- Focus: maintain the Strategy → Backtest → Paper operator workflow on immutable PostgreSQL evidence.
- Latest contract: `docs/contracts/active-bitpro-ashare-strategy-workbench.md`
- Delivery boundary: local UI/API/runtime behavior only; no large provider sync, historical backfill or remote deployment.
- Next: user-selected product work; real broker access, production scheduling, large synchronization and remote deployment remain explicitly disabled.

## BitPro-style A-share Strategy Workbench (2026-07-17)

1. Reviewed all BitPro first-level workspaces and translated its reusable operator patterns—instance consoles, layered filters, explicit creation steps, runtime detail and evidence tabs—without copying its business-page code or cryptocurrency fields.
2. Strategy now exposes PG strategy/version provenance, real record and Strategy API v1 counts, a latest-modified time and distinct loading/error/empty states. The editor states the daily, T+1, 100-share, price-limit and suspension boundary.
3. Backtest now exposes its sealed PG and provider-free read boundary, searchable status/mode filters, return/drawdown/Sharpe/time sorting, creation/completion timestamps and Pool evidence. Existing A-share costs, six headline metrics and eight evidence tabs remain intact.
4. Paper is now a Paper-only runtime console with aggregate portfolio KPIs, instance filters, heartbeat SLA degradation, real signals/orders/positions/trades, equity history, cycle replay, capacity limits and complete strategy/dataset/universe/factor/pool/protocol/backtest lineage.
5. The current PG sample proves the stale-state correction: an instance persisted as `running` with its last heartbeat on 2025-01-02 renders `回放心跳陈旧`, while its recorded signals, order, trade, position, equity snapshots and events remain inspectable.
6. No provider sync, backfill, broker connection, remote change or production action was performed.

Verification:

- Cleanly restarted frontend `:4444` and backend `:4445`; both ports listened and `GET /api/health/health` returned `healthy`.
- Authenticated read-only probes returned 2 strategies, 11 backtests (10 success / 1 failed) and 3 Paper instances with 9 signals, 3 orders and 2 trades; the latest Paper trade date is 2025-01-02.
- `npm run check` passed.
- `npm run lint` passed with 9 warnings and 0 errors.
- `npm run test:e2e:mock` passed 27 application tests; 11 write-capable real-backend tests were skipped as designed.
- `./scripts/check.sh` passed the production build, lint, deploy shell syntax, 260 backend tests and Python compilation.

## Daily Publication And Page Integrity (2026-07-17)

1. Hardened the managed daily path so trade calendar, due security master, all auxiliary datasets and Universe evidence must pass their publication gates before daily bars can seal or factors can run. Fixture tests cover open, closed, locked, disabled, already-sealed and partial-failure outcomes.
2. Publication payloads and Data now expose requested/actual source, fallback reason, response hash, availability/cutoff, dataset snapshot, factor status/snapshot and optional market-evidence status. Restricted optional evidence does not invalidate an already sealed core snapshot.
3. Factor and backtest services remain sealed-snapshot-only and provider-free. RankIC now computes Pearson correlation over ranked series, removing the undeclared SciPy runtime dependency without changing Spearman semantics.
4. External market fallback is false by default, so Home/Market cache misses return explicit unavailable states instead of making provider calls. Market cache rows now say `PG 缓存；上游来源未记录` when legacy rows lack provenance.
5. Corrected remaining misleading presentation states: absent highest-board and monthly returns stay unavailable, Monitor does not convert a failed health load into three zero counters, Strategy no longer advertises a fabricated paused count, and AI Lab/Watch/Monitor expose source, state, evidence time and truthful error/empty behavior.
6. Twenty-six authenticated GET dependencies across all twelve first-level pages returned 200 and left SHA-256 fingerprints of 23 PG tables unchanged. Mock browser coverage passed 26 application tests; `./scripts/check.sh` passed build, lint with zero errors, 260 backend tests and Python compilation.

## Read-only Runtime Safety (2026-07-17)

1. Review navigation and date changes now call the observational GET context endpoint. Timeline persistence is restricted to the explicit `重建时间线` POST action, and the UI states that read, rebuild, save and seal have different mutation semantics.
2. Removed catalogue/registry/schedule bootstrap from Data GET paths. Missing daily configuration returns a disabled `configured=false` default without creating a row, and Data distinguishes uninitialized, disabled and failed states.
3. Added one explicit `backend/bootstrap_runtime.py` entrypoint. Default startup now skips migrations, bootstrap, Paper recovery, scheduler, realtime sync and strategy execution; each state is visible in startup logs.
4. Paper recovery only marks genuinely running cycles failed and records one warning per affected instance. A restart with no interrupted cycle emits no event.
5. Six authenticated Data/Review GETs returned 200 while row counts and SHA-256 fingerprints for nine PG tables remained unchanged. Focused backend tests passed 39 tests plus 10 subtests; frontend typecheck and 23 mocked application browser tests passed after a clean scheduler-disabled restart.

## Data Trust Presentation (2026-07-17)

1. Home now loads overview, hot concepts, THS hot rank and short-line cache independently. Module failures are visible, timestamps are evaluated against a 36-hour SLA, stale THS data cannot become a current strong-stock signal and structural zero comparisons are replaced by `未提供可比快照`.
2. Paper keeps persisted runtime state unchanged but applies a 15-minute heartbeat SLA in presentation. Missing or expired recorded-replay heartbeats render as `回放心跳陈旧` with the actual heartbeat time.
3. Review no longer converts an absent context into business zeroes. Load failure leaves six metrics at `--`, uses an explicit failure/empty state, disables inputs and withholds save/seal actions.
4. Data Center reports PG daily-table rows separately from limited coverage samples, exposes partial API-load failures and uses sealed snapshot evidence—not cache-task success—to label research readiness. Missing success and coverage statistics remain unavailable instead of becoming 100% or 0.
5. Added focused mocked browser coverage for all four corrected states and 390px usability. No manual provider probe, historical backfill, Review assemble verification or remote change was performed. The first required backend restart inherited `ENABLE_SCHEDULER=true` and automatically reached one news/realtime-cache schedule boundary; final verification runs with scheduler, realtime sync and strategy execution disabled through process-only overrides.

Verification:

- Cleanly restarted frontend `:4444` and backend `:4445`; both listened and `GET /api/health/health` returned `healthy`.
- `npm run check` and the production build passed.
- `npm run lint` passed with 9 warnings and 0 errors.
- `npm run test:e2e:mock` passed 23 application tests; 11 write-capable real-backend tests were skipped as designed.
- `./scripts/check.sh` passed the frontend checks, deploy shell syntax, 246 backend tests and Python compilation.
- Playwright desktop and 390px inspection confirmed truthful labels and no document-level horizontal overflow. The shared `@bitpro/ui` `DataPanel` still emits a pre-existing React list-key warning.

## Snapshot (2026-07-16)

- Sprint: Financial Operator UI Unification completed locally
- Focus: maintain the accepted A-share research-to-review platform under one BitPro-style dark, dense operator UI contract.
- Active contract: none; latest completed contract is `docs/contracts/active-financial-operator-ui.md`
- Product plan: `docs/ashare-research-roadmap.md`
- Delivery boundary: local Vite `:4444`, FastAPI `:4445` and PostgreSQL only; no remote deployment.

## Financial Operator UI Unification (2026-07-16)

1. Installed the sibling BitPro package as the local `@bitpro/ui` dependency and imported its stylesheet once at the frontend entrypoint. The application root now applies `BitProTheme` to every protected route and the admin login without copying BitPro business-page code.
2. Reworked the shared shell into a 232px dense desktop sidebar, 48px A-share market strip, flattened workflow groups and a compact mobile navigation surface. All 13 business routes expose one shared financial-operator page surface.
3. Unified near-black backgrounds, low-contrast cards, thin borders, blue actions, tabular numeric typography, table density, controls, focus states, scrollbars and responsive spacing through one StockPro theme layer. The configurable red-up/green-down and green-up/red-down schemes now propagate into `@bitpro/ui` tokens.
4. Adopted `DataPanel`, `MetricCard` and `StatusBadge` on the market dashboard and shell. The top strip no longer fabricates fallback index values or a market-open/closed claim: unavailable data renders explicit placeholders and snapshot status.
5. Added route-matrix E2E coverage for `/`, Market, Pools, Factors, Strategy, Backtest, AI Lab, Paper, Watch, Monitor, Review, Data, Data Processing and Admin Login, plus document-overflow and 390px mobile-shell assertions.
6. Preserved existing business APIs and PostgreSQL behavior. The dashboard's established TOP5 fallback remains visible when no hot concept reaches the strong-move threshold.

Verification:

- Cleanly restarted frontend `:4444` and backend `:4445`; both ports listened and `GET /api/health/health` returned `healthy`.
- `npm run check` passed.
- `npm run lint` passed with 9 existing warnings and 0 errors.
- `npm run test:e2e:mock` passed: 18 application tests passed and 11 real-mode tests skipped as designed.
- `./scripts/check.sh` passed: frontend production build, lint, deploy shell syntax, 246 backend tests and Python compilation.
- Desktop and 390px mobile screenshots were inspected; the document had no horizontal overflow.

## Latest Planning Work (2026-07-16)

1. Expanded the BitPro-style hierarchy from 11 to 12 L1 pages by making `/factors` a first-class professional Factor Research workspace.
2. Added the BitPro UI contract: reuse the current dark `MainLayout`, compact operator density, shared tokens/Lucide icons, real-data states and no parallel visual system.
3. Added Sprint 02 for factor definitions/versions, daily DAG calculation, partitioned PG values, diagnostics, schedules and immutable factor snapshots.
4. Shifted strategy, JoinQuant-style backtest, pool, Paper and local acceptance contracts to Sprint 03-07 and reconciled their dependencies/handoffs.
5. Defined plain-Python strategy authoring: strategies implement lifecycle functions only and never require framework, registry, route or restart changes.
6. Defined JoinQuant-style backtest configuration, six core KPI cards, full risk/trading metrics, charts and eight result tabs backed by persisted PG evidence.
7. Defined daily data synchronization by reusing the existing APScheduler at local 17:30: PG advisory lock, trade-calendar gate, incremental dataset order, five-day correction window, quality gate, atomic snapshot publication, retries and factor trigger.
8. Kept factor and backtest reads point-in-time: they consume sealed dataset/factor snapshots and perform no provider calls during execution.
9. Added research-validity controls: `available_at`/`knowledge_cutoff_at`, historical Universe Snapshots, corporate-action reconciliation and source entitlement states.
10. Added protocol-bound factor/backtest evaluation: hypothesis, train/validation/out-of-sample windows, embargo, rejected candidates, capacity evidence and Paper-promotion gates.
11. Added daily-close execution timing, isolated Python worker quotas, and local PostgreSQL backup/restore acceptance targets (RPO <= 24h, RTO <= 2h).
12. Rebased the source contract on a 5,000-credit TuShare account: introduced a module catalogue and entitlement probes; mapped 5,000-credit `limit_list_d`/`kpl_list` to post-close market evidence; explicitly excluded 6,000/8,000-credit THS/DC heat, THS flow and `limit_step` products; and defined a source-labelled market-temperature/ladder workspace for Sprint 05.

## Latest Implementation Work (2026-07-16)

1. Added the TuShare 5,000-credit A-share catalogue (86 endpoints), persisted capability probes/raw pulls and a source-labelled post-close market-evidence snapshot. `limit_list_d`/`kpl_list` are permitted; 6,000/8,000-credit and independently authorized interfaces remain explicit restricted states.
2. Added the local PostgreSQL research-data registry, source-entitlement records, source-fetch audit runs, content-addressed immutable partition rows, blocking quality issues, dataset watermarks and immutable sealed dataset manifests.
3. Corrected new K-line collection to request unadjusted daily bars and record the actual provider (`tushare` or `akshare`) plus an explicit fallback reason. Existing historical cache is intentionally not assumed trustworthy until re-synchronized through this path.
4. Added Data Center views for the 5,000-credit endpoint catalogue, current-account probe result, research datasets, quality-gate state and sealed snapshot list. The UI does not fabricate a usable snapshot when one has not been published.
5. Applied eight additive local migrations. With an authenticated local TuShare account, verified `stock_basic` and `limit_list_d`, synchronized two A-share daily bars for one trading date, sealed a source-labelled immutable PG snapshot, read its frozen rows back through the snapshot API, and confirmed that a sealed manifest rejects mutation. The same controlled date also published TuShare `limit_list_d` U/D/Z and `kpl_list` evidence with a derived 6-board maximum and 58 limit-up count. Sprint 01 remains active: full reference-data normalization and factor/backtest snapshot-only reads are next.
6. Added actual-provider provenance to the data-job API (`actualSource` and `fallbackReason`) and restarted the local backend in test mode. The authenticated local API now reports the two controlled daily-bar job items as actual `tushare` records, with no fallback reason.
7. Added a PG-backed daily-reference schedule and per-date run ledger. The sole managed post-close pipeline uses TuShare `trade_cal`, a PostgreSQL advisory lock, single-date K-line sync, quality-gated snapshot publication and then optional post-close market evidence. The Data page now shows its cron, watermark and latest ledger state; legacy independent daily K-line/evidence timers and the pre-snapshot factor timer are no longer registered.
8. Added normalized `security_master` and `trade_calendar` PG partitions. A real `stock_basic` initial pull persisted 5,865 distinct security identities, including a preserved `T*.SH` retired-code namespace so it cannot overwrite a live code. The first pull correctly failed on that collision, retained a blocking quality record, then succeeded after the canonical-key fix. Daily publication now seals `daily_bars`, `security_master` and `trade_calendar` together when invoked by the managed pipeline.
9. Added documented single-day TuShare normalization for `adj_factor`, `daily_basic`, `suspend_d`, `stk_limit` and four benchmark `index_daily` series. Null valuation facts remain null, a valid empty suspension day can be published, and IPO/no-limit sentinels are represented as `has_price_limit=false` while preserving source values. A real 2025-01-02 run published 5,414 adjustment factors, 5,369 valuation rows, 17 suspension rows, 6,967 price-limit rows and four benchmark bars. It also exposed and corrected the `920xxx.BJ` exchange-suffix precedence bug. Managed job 39 then sealed snapshot 6 with all eight required daily/reference datasets.
10. Completed Sprint 01 with normalized corporate-action availability, an immutable all-A historical universe, generic sealed-snapshot dataset reads and a two-year research baseline. Managed job 40 sealed snapshot 7 with all ten daily/reference datasets plus Universe snapshot 1 (5,336 members). Historical job 41 synchronized 20 established A shares from 2023-01-03 through 2025-01-02; snapshot 8 sealed 9,700 TuShare bars (485 per symbol) with the nine reference datasets. A held PG advisory lock made a concurrent trigger return `locked`, the snapshot-only loader returned all 9,700 rows without a provider adapter, null valuation facts survived serialization, and the manifest hash remained stable across service instances.
11. Completed Sprint 02 with a dynamic `StockPro Factor API v1`, immutable definitions/versions, strict AST capability validation, snapshot-only data access, cross-sectional preprocessing, ten PG-stored reference factors and one post-seal daily scheduler. Dataset snapshot 9 produced ten published runs and sealed factor snapshot 3; repeating the same schedule reused the same run/snapshot hashes.
12. Added append-only forward metric maturity: later sealed dataset snapshots can add 1/5/20-day IC, RankIC, quantile and long-short evidence without changing source values, metrics or factor snapshot hashes. Research promotion now requires a sealed protocol, matching sealed factor snapshot, untouched out-of-sample pass, persisted metrics, selection rationale and rejected variants.
13. Rebuilt `/factors` and `/factors/:factorId` as six BitPro-style PG-backed workspaces for library, runs, single/multi-factor analysis, correlation/exposure and point-in-time values. Desktop and 390px mobile acceptance showed real snapshot/version/cutoff metadata, pending metrics as pending rather than zero, and no browser console errors.
14. Exposed point-in-time sealed factor snapshot value reads, future-maturity evaluation and promotion gates through the unified `/api` router. A real PostgreSQL mutation probe exposed and then fixed a partition-trigger table-name bug; published factor values and sealed manifests now reject updates/deletes at the database layer.
15. Completed Sprint 03 with immutable `stockpro.v1` strategy versions, stable AST validation, an isolated lifecycle worker and one deterministic replay path shared by quick, backtest and Paper Replay modes. The platform injects data, factor, scheduling, order, log and record APIs; a new strategy changes only its Python version row and never a framework registry or route.
16. Added timestamped normalized intents, custom records, replay manifests and persisted runtime failures. PostgreSQL rejects in-place version-content mutation; the worker rejects provider/database/network/filesystem access, unsupported APIs, future/wall-clock access and non-serializable state. Replay requests cannot enlarge versioned CPU/wall/memory/output/log/intent/record quotas.
17. Migrated generated and reference strategies to ordinary `initialize`/`handle_data` code, removed silent fallback execution and integrated save/validate/quick-run evidence into the BitPro-style Strategy page. Factor values are exposed only after their sealed knowledge cutoff, and daily intent timestamps remain explicit for Sprint 04 D+1 matching.
18. Completed Sprint 04 with a deterministic A-share daily broker, D-close to D+1 matching, 100-share lots, T+1 availability, suspension/price-limit handling, corporate-action reconciliation, versioned costs, capacity evidence and 41 persisted JoinQuant-style metrics. Successful runs and their child evidence are immutable in PostgreSQL; undefined metrics retain a null reason.
19. Added explicit historical backtest-reference construction. The accepted local snapshot 10 combines 9,700 unadjusted bars with 9,700 adjustment factors, 9,700 price-limit facts, 60 company-action rows, 731 calendar rows and 485 CSI 300 benchmark bars. Backtests and result pages read the sealed snapshot without provider calls.
20. Rebuilt `/backtest` and `/backtest/:runId` as a BitPro-style research workspace with immutable configuration selectors, exact Python code, quick/full distinction, six KPI cards, eight evidence tabs, 2-8 run comparison and a 1-24-cell parameter matrix. A real 3x2 matrix completed all six cells with 485 daily points per run.
21. Bound promotion to a sealed research protocol and explicit train/validation/out-of-sample evaluations. Full run `50f68690-96a7-4b17-94f8-0c543c442b54` produced 41 metrics with zero capacity/data-quality warnings, no same-day fills and passed all five Paper-eligibility checks; a direct mutation of its metric evidence was rejected by PostgreSQL.
22. Completed Sprint 05 with PG-backed factor, sector, event, screener and manual stock-pool generators. Rules, inputs, ordered members, reasons, evidence, validity and immutable snapshots are versioned; a failed generation remains evidence while an identical input can be retried safely.
23. Consolidated Market into Structure, Sector Rotation, Sentiment/Limit, Events, Calendar and Stock workspaces. The source-aware context exposes 12 KPIs, null-safe market temperature, 1/2/3/4/5+ ladder, limit pools, comparisons, sector missing states and fact/inference evidence references.
24. Added the six-workspace Stock Pools page and direct snapshot-to-experiment handoff. Real snapshots `1`-`3` cover factor (10 members), sector (8) and event (20); experiment `29f03da1-f5b3-40ba-a725-c7111249e521` references snapshot `1` without copying symbols.
25. Completed Sprint 06 with a pinned, restart-safe Paper state machine, exactly-once cycle runner, signal-to-risk-to-fill ledgers, stale-feed entry block, versioned alerts, notification acknowledgement and service health. Factor Snapshot `4` and Pool Snapshot `4` bind qualifying full backtest `ac808202-72da-474e-9336-b075956e0506`.
26. Recorded Paper instance `076c217f-9b5c-4b18-8fb3-fcd2a127a171` across five trading days. The first cycle did not trade, the accepted order filled after its close signal, a repeated cycle was reused, every equity point reconciled at zero and a stale sixth session created a visible data alert. A separate instance proved participation-limit rejection.
27. Rebuilt Paper, Watch and Monitor into separate BitPro-style workspaces with 6/4/5 tabs and shared object links. Added 35 focused service/API checks, mocked operator coverage and a real-backend Paper/Watch/Monitor browser flow.
28. Completed Sprint 07 with immutable daily review records, metrics and cross-object references. The sealed 2025-01-02 review contains 14 ordered items across market, pool, strategy, risk, order, trade and performance, and every reference resolves back to its PostgreSQL source object.
29. Finalized the BitPro-style 12-page hierarchy and added the controlled AI Research Lab. Review now owns five workspaces: Market, Pools, Strategy, Trades and Logs; compatibility routes remain redirects rather than duplicate navigation entries.
30. Added audited local PG backup/restore and local acceptance services. APScheduler registers a daily 02:30 Asia/Shanghai custom-format backup; a disposable restore reconciled dataset, factor, backtest, Paper, review and migration manifests before teardown.
31. Passed one complete nine-drill resilience batch covering provider fallback, last-good retention, stale positions, restart cursor recovery, interrupted jobs, notification failure, disposable migration rollback, backup restore and research-validity gates. Five API p95 measurements all passed: 69.11/7.42/33.21/16.42/11.58 ms against 500/500/500/800/800 ms budgets.
32. Removed the implementation-specific TuShare credit-tier wording from the Data Center product UI. The page now presents interface support, verified access and restricted/independently-authorized states without exposing the configured points baseline as a headline.
33. Corrected post-close market evidence so each all-A snapshot derives rise, fall, flat, red-market ratio and rise/fall ratio from the source-labelled TuShare daily feed. Historical comparisons now select one latest immutable snapshot per trade date, so a same-date correction cannot masquerade as a prior trading day. A rebuilt 2025-01-02 snapshot published 924 rises, 4,383 falls and 60 flat securities alongside the existing limit-up ecology. The local cache still has only one distinct evidence date, so comparison cards remain unavailable until daily orchestration backfills at least 20 trading-day snapshots.

## Latest Verification (2026-07-16)

- Final `./scripts/check.sh` passed: frontend production build, lint with 9 warnings and 0 errors, deploy shell syntax, 242 backend tests and Python compilation.
- Final `cd frontend && npm run test:e2e:mock` passed: 16 application cases passed and 11 real-mode cases skipped as designed.
- Final real-backend Playwright coverage passed after the corrected resolver assertion; the dedicated full flow proved that all 14 sealed review references resolve to their immutable PG objects and the page exposes all five review workspaces plus exactly 12 L1 entries.
- Authenticated local `GET /api/data/jobs` returns actual provider provenance for the controlled TuShare daily-bar sync. The backend is running locally on `:4445` with the scheduler, realtime sync and strategy execution disabled for this validation.
- Authenticated daily-orchestration smoke tests passed: 2025-01-04 exited as `not_trading_day` from TuShare `trade_cal` without a K-line job; the controlled 2025-01-02 two-symbol run created K-line job 37, sealed dataset snapshot 3 and published market evidence.
- The reference-data integration check passed: a controlled 2025-01-02 managed run created K-line job 38 and sealed a three-partition snapshot containing `daily_bars`, `security_master` and `trade_calendar` before publishing market evidence.
- The expanded reference-data integration check passed: managed K-line job 39 sealed snapshot 6 with eight partitions (`daily_bars`, security/calendar, adjustment factors, valuation, suspensions, price limits and benchmark bars). Targeted normalization/snapshot/orchestration tests pass 16/16.
- Sprint 01 final verification passed: `./scripts/check.sh` completed the frontend build, lint (7 existing warnings, 0 errors), shell checks, 39 backend tests and Python compilation; mocked Playwright passed 9 with 5 real-backend cases skipped. `git diff --check` passed. The accepted immutable historical manifest is snapshot 8 with hash `eb606ebd3f7531c39a7acebbaf012ff202c34b20d20f7cfd3f48d194d85c0a49`.
- Sprint 02 final verification passed: `./scripts/check.sh` completed the frontend build, lint (7 existing warnings, 0 errors), shell checks, 51 backend tests and Python compilation. Mocked Playwright passed 10 with 5 real-backend cases skipped. Real PG checks returned 20 point-in-time `momentum_20d` values from sealed factor snapshot 3, rejected a published-value update, and reused the same sealed daily schedule twice.
- Sprint 03 final verification passed: focused Strategy runtime tests passed 27/27; `./scripts/check.sh` completed frontend build, lint (7 existing warnings, 0 errors), shell checks, 78 backend tests and Python compilation. Mocked Playwright passed 11 with 5 real-backend cases skipped; the real-backend/browser suite passed 7/7, including plain-Python save, validation, sealed-snapshot replay, intent inspection and a console-error-free editor. A real reference replay processed 13 events into 11 intents and 11 records; separate real probes confirmed backtest/Paper hash parity, immutable-version rejection and persisted wall-time/memory failures.
- Sprint 04 final verification passed: `./scripts/check.sh` completed frontend build, lint (6 existing warnings, 0 errors), shell checks, 138 backend tests and Python compilation. Mocked Playwright passed 12 with 8 real-mode cases skipped; the dedicated real-PG/browser backtest case passed. API fixtures add 13 contract checks, focused broker/reference/API tests pass 72/72, the full matrix passes 6/6 and real comparison returns two 485-day persisted series.
- Sprint 05 final verification passed: focused market/pool/backtest coverage passed 53/53; mocked Playwright passed 13/13; the dedicated real-PG/browser market-to-pool case passed. Repeated generation/sealing preserved hashes, and PG rejected snapshot/member/rule mutation. The full local check passed with 7 lint warnings and 0 errors.
- Sprint 06 focused verification passed: 35 Paper lifecycle/risk/recovery/API tests, frontend production build, mocked Playwright 14/14 application cases, and the dedicated real-backend execution/observation/health flow. Real PostgreSQL evidence contains six unique cycles, one next-day fill linked to five risk decisions, zero maximum ledger difference, one stale-data alert and one participation rejection.

## Verification Evidence (2026-07-16)

- `git diff --check` passed; roadmap links resolve and all Sprint 00-07 contracts remain in dependency order.
- `./scripts/check.sh` passed after the supplement: frontend build, lint with 7 existing warnings and 0 errors, deploy shell syntax, 17 backend tests and Python compilation.
- No runtime code, PostgreSQL state or remote server changed in this planning slice.

## Snapshot (2026-07-15)

- Sprint: `data-trust-and-snapshots`
- Focus: build source-aware, quality-gated and immutable TuShare/AKShare research datasets before strategy and page consolidation.
- Active contract: `docs/contracts/active-sprint-01-data-trust-and-snapshots.md`
- Product plan: `docs/ashare-research-roadmap.md`

## Latest Planning Work (2026-07-15)

1. Replaced the page-readiness roadmap with an implementation-oriented A-share platform plan.
2. Reworked the target navigation against BitPro's operator-stage hierarchy: 11 L1 pages, L2 page tabs and L3 object details.
3. Kept Market, Strategy, Backtest, Paper, Monitor and Review as stable short routes; added A-share Stock Pools plus Watch and a controlled AI Lab, while keeping real trading hidden.
4. Defined page modules, route migration, source mapping, freshness targets and failure behavior for TuShare and AKShare.
5. Defined the target research lifecycle: data snapshot -> stock-pool snapshot -> strategy version -> experiment -> Paper -> review.
6. Split the roadmap into seven ordered contracts: Sprint 00 completed, Sprint 01 active and Sprint 02-06 planned.
7. Limited the active sprint to dataset provenance, quality and immutable snapshots; unified strategy execution now starts in Sprint 02.
8. Marked the previous parallel and umbrella active contracts as superseded.

## Verification Evidence (2026-07-15)

- Documentation links and referenced current source adapters inspected.
- TuShare/AKShare interface names checked against current official documentation and the existing `tushare_provider.py` adapter.
- `git diff --check` passed after the BitPro-style page hierarchy update.
- All seven Sprint contracts contain status, scope, deliverables, pass/fail acceptance, verification, rollback and handoff sections; only Sprint 01 is Active.
- `./scripts/check.sh` passed: frontend build, lint with 7 existing warnings and 0 errors, deploy shell syntax, 17 backend tests, and Python compilation.
- No runtime code or database state changed in this planning slice.

## Snapshot (2026-06-26)

- Sprint: `ashare-research-professionalization`
- Focus: audit every primary page, verify usability, and define the route from current console pages to a professional A-share research workstation.
- Active contract: `docs/contracts/active-ashare-research-professionalization.md`
- Product direction: every page should have a clear A-share research/execution purpose, visible data readiness, and explicit trading constraints where decisions move toward orders.

## Latest Completed Work (2026-06-26)

1. Added cross-page usability coverage
- Added mocked E2E coverage that opens every primary protected route and verifies page title, core workflow anchors, and absence of React page errors.
- Expanded mocked market fixtures for daily K-line, intraday, fundamentals, and stock search so `/market` is tested as a real page instead of crashing on fixture shape.

2. Strengthened A-share professional anchors
- Added a shared `AshareGuardrailStrip` component.
- Added visible A-share guardrails to strategy, backtest, paper trading, and monitor pages: T+1, 100-share lots, limit-up/down, suspension, cost model, and broker isolation.
- Renamed the hidden `/market` surface header to `行情终端` and exposed `个股分析`, `板块龙头`, and `K线图表`.
- Made the data page's `A股数据维护面板` label visible instead of aria-only.

3. Documented audit and roadmap
- Added `docs/qa/2026-06-26-ashare-page-audit.md` with a page-by-page usability and A-share professionalism matrix.
- Added `docs/ashare-research-roadmap.md` with the full path from data foundation to research, candidate pools, strategy lifecycle, backtesting, paper trading, risk, and broker dry-run.
- Added `docs/superpowers/plans/2026-06-26-ashare-research-workstation.md` as the step-by-step development plan.
- Added `docs/contracts/active-ashare-research-professionalization.md` as the next sprint contract.
- Updated `docs/spec.md` with page professionalism acceptance rules.

## Verification Evidence (2026-06-26)

- `npm run check` from `frontend/` (pass).
- `npm run lint` from `frontend/` (pass with 7 existing warnings, 0 errors).
- `npm run test:e2e:mock -- --grep "primary pages expose"` from `frontend/` (pass).
- `npm run test:e2e:mock` from `frontend/` (pass: 9 passed, 5 real-backend tests skipped by mock mode).
- `./scripts/check.sh` (pass: frontend build, frontend lint with warnings only, deploy shell syntax, backend unit tests 17/17, backend compile).

---

## Snapshot (2026-06-25)

- Sprint: `stockpro-ai-console-style`
- Focus: align the local frontend with the production server StockPro AI dark console style.
- Active contract: `docs/contracts/active-stockpro-ai-console-style.md`
- Product direction: fixed grouped sidebar, compact dark cards, top A-share ticker/status bar, and dashboard-first market cards.

## Latest Completed Work (2026-06-25)

1. Rebuilt the application shell around the server reference style
- Added the `StockPro AI` brand block with a fixed 264px desktop sidebar.
- Reorganized navigation into `研究工坊`, `策略工厂`, `执行风控`, and `系统管理`.
- Moved `总览看板` into the `研究工坊` group and removed the empty `数据中台` group.
- Moved `管理后台` from the top business navigation area into a lower `系统管理` section.
- Renamed the backtest workspace navigation/title from `复盘中心` to `回测中心`.
- Added a separate `/review` `复盘中心` for daily market review.
- Added a compact desktop top bar with route title, four A-share indices, `已休市` status, language toggle, settings, and logout actions.

2. Aligned global visual tokens
- Updated the dark palette, borders, card surfaces, hover states, radius scale, and primary accent toward the production server screenshot.
- Added compatibility overrides so older purple accents read as the current blue console accent.
- Updated the admin login page to use the same StockPro AI console tone.

3. Tightened the dashboard first viewport
- Removed the old `量化交易中枢` module chain from the top of the dashboard.
- Made the first content block start directly with `市场指数`, followed by `短线指标` and `热门板块`.
- Locked the index order to `上证指数`, `深证成指`, `创业板指`, `科创50` in both the top ticker and dashboard cards.
- Added a hot-concept fallback so `热门板块` uses existing external market data when PG cache is empty, and displays TOP5 when no board is above 5%.

4. Added regression coverage
- Added E2E coverage for the StockPro AI shell, navigation groups, top ticker order, dashboard index order, and removal of the old module-chain header.
- Updated the dashboard realtime cockpit test so the dashboard defaults directly to the market cockpit instead of requiring a module button.
- Added backend fallback tests and frontend E2E coverage for the `热门板块` non-empty TOP5 path.
- Added E2E coverage that `/backtest` is `回测中心`, `/review` is the new `复盘中心`, and legacy `/pulse` redirects to `/review`.

5. Added daily review workflow
- Added `DailyReview.tsx` to summarize market temperature, breadth, turnover, hot sectors, limit-up ladders, risk notes, and next-day plans.
- Wired replay-note list/save API client helpers so the page can persist daily review logs through existing `/market/pulse/replay-notes` endpoints.

## Verification Evidence (2026-06-25)

- `npm run check` from `frontend/` (pass).
- `npm run lint` from `frontend/` (pass with 7 existing warnings, 0 errors).
- `npm run test:e2e:mock -- --grep "desktop shell matches|single api shell"` from `frontend/` (pass; covers `总览看板` under `研究工坊` and removal of `数据中台`).
- `npm run test:e2e:mock` from `frontend/` (pass: 8 passed, 5 real-backend tests skipped by mock mode).
- `npm run test:e2e:mock -- --grep "backtest center is separated"` from `frontend/` (pass).
- `python -m unittest tests.test_market_service_cache_only.HotConceptFallbackTests` from `backend/` (pass).
- `npm run test:e2e:mock -- --grep "hot concepts|realtime market cockpit"` from `frontend/` (pass: 2 passed).
- `./scripts/check.sh` (pass: frontend build, frontend lint with warnings only, deploy shell syntax, backend unit tests 17/17, backend compile).
- Real local API check: `/api/market/hot-concepts?limit=10` returned 10 rows after login.
- Local Playwright visual QA screenshot: `.codex-artifacts/stockpro-daily-review-center.png`.
- Local Playwright visual QA screenshot: `.codex-artifacts/stockpro-hot-concepts-fixed.png`.
- Local Playwright visual QA screenshot: `.codex-artifacts/stockpro-ai-style.png`.

---

## Snapshot (2026-06-12)

- Sprint: `standardize-and-trading-core` adjusted to single-router cleanup
- Focus: remove unused legacy pages, backup files, and parallel API routers while preserving the active market/research/strategy/backtest/paper workflows
- Active contract: `docs/contracts/active-standardize-and-trading-core.md`
- Product direction: one `/api` prefix, no `/api/v1` or `/api/v2`, no standalone V2 business routes

## Latest Completed Work (2026-06-12)

1. Removed unused frontend route surfaces
- Deleted legacy pages replaced by the new shell or route redirects: `Home`, `StockScreener`, `StrategyDev`, `StrategyExec`, `MarketPulse`, `LiveTrading`.
- Deleted old one-off components only referenced by those pages: `StockTable`, `AIAnalysisPanel`, `SectorMonitor`, `StrategyLabWorkflow`, `MarketCalendar`, `CalendarView`, `DataOverviewPanel`, `PresetTaskPanel`, and related helper-only files.
- Kept active pages for dashboard, market, research workbench, AI analysis, factor library, data center, strategy factory, backtest, paper trading, monitor, and trading calendar.

2. Removed redundant backend API surfaces
- Removed `backend/app/api/v2` source tree.
- Removed standalone `strategy_v2.py`, `stock_screener.py`, and `trading.py` endpoint routers from the active API registration.
- Removed tracked `.bak` / `.backup` source files.
- Preserved underlying Postgres repository methods and migrations so future paper/risk/broker capabilities can be wired into the main product flow instead of a parallel API.

3. Tightened frontend runtime logic
- Removed unused Zustand state for old stock table, hot sectors, and batch AI analysis.
- Removed client calls for `/stocks/filter`, `/sectors/hot`, `/ai/analyze`, `/screener/*`, and old Market Pulse-only replay APIs.
- Updated Data Hub feature service to refresh the current `/data-hub/features/screener` summary instead of navigating to the deleted `/screener` route.

4. Removed visible instruction banners
- Removed the Data Hub V1 explanatory banner from the data-processing page.
- Removed the legacy compatibility advisory banner from the data-processing legacy tab.
- Added E2E coverage to ensure those explanatory strings do not return.

## Verification Evidence (2026-06-12)

- `npm --prefix frontend run build` (pass)
- `python3 -m compileall backend/app` (pass)
- `./scripts/check.sh` (pass after allowing local Postgres access; frontend build, frontend lint with warnings only, deploy shell syntax, backend unit tests 15/15, backend compile)
- `npm --prefix frontend run test:e2e:mock` (pass: 3 active mock tests, 5 real-backend tests skipped by mode)
- Static scans found no runtime source references to `api_router_v2`, `app.api.v2`, `/api/v2`, `/strategy-v2`, `strategy_v2`, `stock_screener`, `trading.router`, old screener client calls, or deleted page/component names.
- Backup-file scan found no remaining tracked `*.bak`, `*.backup`, or `*~` files.
- Static scan found no remaining `Data Hub V1`, `当前以`, or legacy compatibility advisory text in frontend source.

## Remaining Work (standardize-and-trading-core sprint)

- Wire any still-needed portfolio/order/risk/broker capabilities into the active `/paper`, `/strategy`, `/backtest`, or future `/monitor` workflows before exposing them again.
- Continue PG repository cleanup in `data_hub_service.py` and `strategy_lab_service.py`.
- Browser E2E against real backend remains useful after the local backend is restarted with production-like environment variables.

---

## Snapshot (2026-06-03)

- Workspace: `/Users/jie.feng/wlb/StockPro`
- Focus: cloud B/S deployment foundation, Postgres migration runner, BitPro-style production deploy upgrade
- Active contract: `docs/contracts/active-cloud-bs-pg-deploy.md`
- Production target: `root@47.79.36.92`, public entry `http://47.79.36.92:4444`
- Deployment status: live on `47.79.36.92:4444` with Postgres `stockpro_prod`

## Latest Completed Work (2026-06-03)

1. Product and sprint direction updated
- Replaced template-oriented `docs/spec.md` with StockPro cloud B/S product spec.
- Added active sprint contract for React + FastAPI + Postgres deployment foundation.

2. Postgres foundation added
- Added `backend/app/db/postgres_migrations.py` migration runner.
- Added initial PG schema under `backend/postgres/migrations/202606030001_strategy_workbench_core.sql`.
- Added backend unit tests for migration sorting, skipping applied migrations, and recording applied versions.
- Added `psycopg[binary]` dependency and `DATABASE_URL` config support.

3. Deployment upgraded toward PG-only production
- Updated `deploy/deploy.sh` to validate `.env`, install dependencies, compile backend code, run PG migrations, restart systemd, reload Nginx, and health-check services.
- Updated `deploy/setup-server.sh` and added `deploy/setup-postgres.sh`.
- Updated Nginx config with WebSocket proxy headers.
- Updated GitHub Actions deployment to keep main-only SHA-gated deploy and remove old local-file seed/import steps.
- Enforced PG-only production deploy through required `DATABASE_URL`.

4. Local-file database runtime removed from production
- Changed backend default storage to Postgres.
- Removed local-file database route/service toggles from the current runtime.
- Moved research, data, and strategy surfaces toward Postgres repositories.

5. Documentation updated
- Rewrote `docs/deployment.md` for `47.79.36.92:4444`, Postgres `stockpro_prod`, and BitPro-style single-server deployment.
- Updated README environment/deployment notes for PG-only production.

6. Production server initialized and deployed
- Installed PostgreSQL on `47.79.36.92`.
- Created `stockpro_prod` and `stockpro_app` with a server-local generated password.
- Created root-only `/opt/stockpro/backend/.env` for Postgres runtime settings.
- Deployed React static frontend + FastAPI backend through Nginx/systemd.
- Archived old local database files outside the active runtime path.

## Verification Evidence (2026-06-03)

- `python3 -m unittest tests/test_postgres_migrations.py` from `backend/` (pass, 2/2)
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_api_router_modes` (pass, 2/2)
- `./scripts/check.sh` (pass: frontend build, frontend lint, deploy shell syntax, backend unit tests 5/5, backend compile)
- Remote deploy: `bash /opt/stockpro/deploy/deploy.sh` (pass, no pending migrations on second deploy)
- Remote health: `curl http://47.79.36.92:4444/api/health/health` (pass)
- Remote storage health: `curl http://47.79.36.92:4444/api/health/storage` (pass: Postgres migrations reported)
- Remote service state: `stockpro-backend` active, `postgresql` active, no local database files remain under `/opt/stockpro`

## Snapshot (2026-06-10)

- Sprint: `standardize-and-trading-core` active
- Latest work: Added V2 trading infrastructure repository methods in `postgres_db.py`

## Latest Completed Work (2026-06-10)

1. V2 trading infrastructure repository methods added to `postgres_db.py`
- Portfolios: `create_portfolio`, `get_portfolio`, `list_portfolios`, `update_portfolio`
- Positions: `upsert_position`, `get_positions`, `get_position`
- Orders: `create_order`, `get_order`, `list_orders`, `update_order`
- Trades: `insert_trade`, `list_trades`
- Cash Ledger: `insert_cash_ledger_entry`, `list_cash_ledger`
- Risk Rules: `create_risk_rule`, `get_risk_rule`, `list_risk_rules`, `update_risk_rule`
- Risk Events: `insert_risk_event`, `list_risk_events`
- Broker Connections: `create_broker_connection`, `get_broker_connection`, `list_broker_connections`, `update_broker_connection`
- Added `get_backtest_run` method

2. V2 API endpoints created and registered
- `strategy_v2.py`: strategy versions CRUD, signals CRUD, backtest runs CRUD + trades list
- `trading.py`: portfolios CRUD, positions list, orders CRUD, trades list, cash ledger, risk rules CRUD, risk events, broker connections CRUD
- Both registered in `api.py` under `/strategy-v2` and `/trading` prefixes
- Added `get_backtest_run` method to `postgres_db.py`

3. Verification
- `postgres_db.py` compiles clean
- All new endpoint routes load successfully (35 routes total)
- `./scripts/check.sh`: frontend build OK, deploy syntax OK, backend compile OK
- Backend unit tests: 8/10 pass (2 pre-existing failures due to missing `dashscope`)

## Remaining Work (standardize-and-trading-core sprint)

- Wire V2 service layer to use new postgres_db methods and API endpoints

## Known Gaps (2026-06-10)

1. Current fusion needs continued real-data validation across research, market, strategy, backtest, and paper trading flows.
2. PG-only production should keep all new work on shared Postgres repositories.
3. IP-only HTTP remains the production entry for now; HTTPS/domain should be added before real broker integration.
4. V2 trading API endpoints implemented but no frontend integration yet.

## Recommended Next Steps (2026-06-10)

1. Wire frontend to new V2 trading API endpoints
2. Continue `data_hub_service.py` raw SQL refactoring
3. Clean remaining raw SQL in `strategy_lab_service.py`
4. Add HTTPS/domain before broker integration

---

## Snapshot (2026-05-28)

- Workspace: `/Users/jie.feng/wlb/StockPro`
- Focus: full-stack smoke test, API/page auto-fix, E2E alignment with current 11 routes
- Verification: `./scripts/check.sh`, Playwright real-backend (7/7), mocked pages (2/2), manual API sweep (19/19)

## Latest Completed Work

1. Fixed `/api/stocks/filter` 500 error
- Root cause: `database_data_service.get_filtered_stocks_from_db()` returned fields (`close`, `amount`) incompatible with `StockFilterResponse` schema (`current_price`, `market_cap`).
- Fix: prefer `all_stocks_realtime` cache and map to `StockBase` fields; fallback to `stock_history` with correct mapping.

2. Page title alignment
- `LiveTrading` page title updated to `模拟/实盘交易`.
- E2E routes updated: removed `/analysis`, `/screener`; updated `/ai` and `/trading` titles.

3. E2E config
- Playwright default base URL/port aligned to Vite dev server (`4444` / backend `4445`).

4. Full verification pass
- 11 frontend pages: all render with data, no API 4xx/5xx on page load.
- 19 core backend endpoints: all return 200 via direct backend and frontend proxy.

## Module Completion

| Module | Route | Status | Evidence |
|---|---|---|---|
| Dashboard | `/` | Usable | Page + API pass |
| Market Overview | `/market` | Usable | Page + API pass |
| Sentiment | `/sentiment` | Usable | Page + API pass |
| News Center | `/news` | Usable | Page + tab E2E pass |
| AI Screener | `/ai` | Usable | Page + API pass |
| Factor Library | `/factors` | Usable | Page + API pass |
| Calendar | `/calendar` | Usable | Page + API pass |
| Strategy Dev | `/strategy-dev` | Usable | Page + API pass |
| Strategy Watch | `/strategy-exec` | Usable | Page + API pass |
| Review Center | `/pulse` | Usable | Page + API pass |
| Sim/Live Trading | `/trading` | Usable | Page pass |

## Next Step

- Consider adding `.env.example` with `VITE_DEV_API_PROXY_TARGET=http://127.0.0.1:8012` when port 8000 is occupied by other local services.

---

## Historical Log (2026-04-02)

1. DataDev backend unblock
- Added `data_dev_tasks` / `data_dev_logs` table init into local DB bootstrap.
- Wired `StockScreener` route and sidebar entry.
- Added `/screener` into Playwright route coverage.

3. Data schema and usability fixes
- Unified `stock_fundamentals` schema with actual read/write usage.
- Added compatibility column migration (`ALTER TABLE ... ADD COLUMN`) for old local DBs.
- Fixed stock search to read `current_price` instead of non-existent `price`.
- Fixed Data Quality check to use `current_price`.
- Fixed THS freshness check to support `ths_hot_history`.
- Updated SQL workbench fundamentals template query.

4. Backfill task behavior alignment
- `batch-import/historical-data` now validates and honors `task_type` (`history|fundamentals|all`).
- Removed misleading `indicators` option from daily backfill UI (it was not supported in that endpoint flow).

5. E2E dual-mode support
- Added `MOCK_API` gated test strategy:
  - `app.spec.ts` runs in mocked mode only.
  - `real-backend.spec.ts` runs in real-backend mode only.
- Added npm scripts:
  - `test:e2e:mock`
  - `test:e2e:real`

6. Backend startup guardrail
- Added health script: `scripts/backend-health.sh`
- Checks:
  - required python dependencies
  - critical backend module `py_compile`
  - optional health endpoint ping (`--ping`)

7. Real-backend regression fix
- Fixed `/api/admin/task-status` 500 by adding missing scheduler methods:
  - `SchedulerService.get_status()`
  - `SchedulerService.fetch_and_save_all_stocks_history()`
- Extended real-backend E2E to assert `admin/task-status` endpoint.

8. Backend test-mode startup toggle
- Added runtime feature flags:
  - `ENABLE_SCHEDULER`
  - `ENABLE_REALTIME_SYNC`
  - `ENABLE_STRATEGY_EXECUTION`
- Backend can now start in lightweight test mode to avoid startup noise and external sync interference during E2E.

9. Offline market-overview path for E2E
- Added runtime flag:
  - `ENABLE_EXTERNAL_MARKET_FETCH`
- In `MarketService.get_market_overview`, when this flag is `false`:
  - no fallback to external market API
  - return cache-only stocks/indices
- Also guarded external fetch in:
  - `MarketService._get_cached_all_stocks`
  - `MarketService.get_all_sectors`
  - `MarketService.get_stock_fundamentals` (returns `external_fetch_disabled` if local data missing)

10. Database endpoint status-code correctness
- Fixed `database` endpoint exception handling to preserve `HTTPException` status codes.
- `/database/query` non-SELECT validation now returns `400` correctly (instead of being converted to `500`).
- `/database/table/{table_name}` now preserves `404` when table is missing.

11. Batch import task usability fix
- Removed unsupported `indicators` task from `BatchImportPanel` (backend rejects it in `/batch-import/historical-data`).
- Kept MA import in its dedicated card flow to avoid task-type mismatch and user confusion.

12. Database manager export completion
- Implemented CSV export for:
  - selected table preview data
  - SQL query result data
- Added empty-result disable states and reused a safe cell-stringify path.

13. Real-backend E2E deepening
- Extended `real-backend.spec.ts` from smoke checks to functional assertions:
  - `market/overview` response structure
  - `database/query` success + non-SELECT rejection
  - `data-dev` task CRUD + run + logs flow
- Switched real-backend suite to serial mode for deterministic shared-db mutations.

14. Data Hub V1 one-time refactor (功能重构)
- Added unified backend capability set under `/data-hub/*`:
  - dataset registry and freshness
  - job orchestration (create/list/detail/rerun/cancel)
  - quality governance report run/query
  - feature service for screener/factors
- Added local DB tables:
  - `data_hub_jobs`
  - `data_hub_quality_reports`
- Marked legacy endpoints with deprecation hints:
  - `/batch-import/*`
  - `/data-dev/*`
  - `/database/*`

15. Legacy-to-hub compatibility bridge
- `batch-import/historical-data` now internally dispatches to Data Hub job orchestration (`import_daily_data`) while preserving old response shape.
- `data-dev/tasks/{id}/run` now dispatches into Data Hub orchestration (`run_data_dev_task`) and returns `job_key`.

16. Frontend information architecture refactor
- Reworked Data Center page into Data Hub workflow tabs:
  - 数据资产 (`DataHubDatasetPanel`)
  - 生产任务 (`DataHubJobsPanel`)
  - 质量治理 (`DataQualityPanel` via data-hub quality API)
  - 特征服务 (`DataHubFeaturePanel`)
  - 兼容入口（保留旧模块入口并给出迁移提示）
- Reworked sidebar navigation into product modules:
  - 数据中台 / Research Lab / Strategy Factory / Execution & Risk

17. Research-side data source migration
- Stock Screener now prefers `/data-hub/features/screener` and displays snapshot date.
- Factor Library overview/stats/ranking now prefer `/data-hub/features/factors` and display snapshot version/date.

18. Dashboard market metric repair and Top 30 hot sectors
- Fixed Home/Dashboard market cards so missing realtime cache is shown as unavailable instead of being rendered as neutral `50` or `0`.
- `/market/short-line-indices` now filters stale all-zero cache through `MarketService` instead of returning old placeholder rows directly.
- Realtime market-cache sync now falls back from EastMoney/EM spot data to Sina spot data when the local proxy blocks EM, preserving source-aware PG cache behaviour.
- Normalized `SH_`/`SZ_`/`BJ_` stock codes are now handled in market volume split calculations, so Shanghai/Shenzhen/Beijing turnover rows no longer show `0` after a successful sync.
- Dashboard hot sectors now request and render Top 30 instead of the previous small Top 5/8 slice.

19. BitPro twelve-page operator parity
- Replaced the grouped wide sidebar and global ticker with BitPro's compact 64px single-column navigation; every first-level page now owns its title, controls and status context.
- Normalized the twelve menu destinations and their page-owned headers: Home, Market, Stock Pools, Factors, Strategy, Backtest, AI Lab, Paper, Watch, Monitor, Review and Data.
- Reworked Stock Pools into a searchable catalogue with type filters, dense object rows, explicit business empty state and a separate test/acceptance scope.
- Added business/test isolation to Strategy, Backtest, AI Lab, Paper, Watch and Monitor so Sprint, seed and acceptance objects no longer appear as normal business content.
- Propagated `data_purpose` from Paper instances into Watch signals, orders, trades, positions, risk/runtime events and alerts; stock-pool movements receive the same derived purpose label.
- Preserved PostgreSQL snapshot/version evidence and A-share safety rules; no provider sync, Paper runtime cycle, remote deployment or broker operation was triggered.
- Updated browser acceptance for the flat BitPro navigation, page-owned headers and explicit test scopes.
- Increased sidebar contrast after visual review: near-black navigation canvas, stronger inactive labels/icons, a deeper blue selected block and a clear active-edge marker.

20. BitPro subpage parity — Paper and AI research
- Replaced the Paper global-tab landing page with the BitPro object workflow:
  strategy instance dashboard, preferred/all partitions, business/test scope,
  market/strategy/capital/status filters, sorting, dense instance cards, a
  separate creation page and a separate instance-monitor page.
- Added honest Paper card evidence for PnL, return, trade count, symbol scope and
  heartbeat time. Metrics not returned by the Paper API are labelled
  `未计算` with the reason instead of being rendered as zero.
- Reworked AI Research into the BitPro three-workspace structure:
  `AI自主交易`, `新策略研发` and `现有策略优化`.
- Added the four-stage research flow and integrated persisted strategy/backtest
  candidate evidence. Autonomous AI runtime actions stay visibly unavailable
  until StockPro has durable instance, decision-log and hard-risk APIs.
- Retained the existing Strategy and Backtest object flows because they already
  provide catalogue cards, staged creation and record-level detail evidence.

21. BitPro Paper instance monitor and runtime truthfulness
- Replaced the legacy Paper detail tabs with one continuous BitPro-parity
  instance monitor containing all nine KPI slots, strategy logic, parameter
  evidence, runtime diagnostics, positions, trades/events, buy/sell K-line
  review, account curve and risk state.
- Added a read-only Paper K-line endpoint backed by the instance's sealed
  PostgreSQL dataset snapshot, including source, snapshot id, knowledge cutoff
  and explicit empty status.
- Fixed Paper list/detail aggregation so signal/order/trade totals, equity and
  the latest cycle are selected consistently by creation time.
- Fixed historical replay heartbeat semantics: processing heartbeat is current,
  simulated observed time remains in cycle evidence, explicit sealed replay
  can allow entries without being mistaken for a realtime feed, and a successful
  cycle resolves its prior stale-feed alert.
- Native Strategy API v1 creation now also creates/links the catalogue identity,
  so newly authored strategies appear in `/strategy/list`.
- Repaired the existing MA5/20 momentum strategy catalogue link locally and
  validated the running Paper instance against snapshot #10. The target instance
  is fresh with a successful latest cycle; no external sync or broker call ran.
- Moved `AI研发` to the final position in both desktop and mobile primary
  navigation while preserving its route and page behavior.
- Raised the global operator typography contrast for legacy gray/slate text
  tiers, table headers and placeholders, and introduced a Chinese-first
  `SF Pro` / `PingFang SC` system font stack across all primary pages.
- Rebuilt Strategy detail and Paper instance detail on shared `@bitpro/ui`
  primitives. Strategy detail now includes version/validation, snapshot,
  dependency, runtime-limit and read-only source evidence plus lifecycle
  actions; Paper KPI, status and collapsible modules use the same primitives.
- Replaced Paper diagnostic/event entry cards with the shared BitPro terminal
  `LogStream`: one bounded console, stable time/level/message columns, compact
  mobile reflow and explicit empty state.

22. Factor research workspace redesign
- Aligned `/factors` with the spacing and compact tab structure used by the
  market and stock-pool workspaces; removed the oversized summary cards.
- Brought the real 10-factor catalogue into the first viewport with Chinese
  category filters, research hypotheses, selection direction, coverage,
  effectiveness evidence and publication state.
- Replaced engineering-facing hashes and abbreviations with operator labels,
  added a signed correlation heatmap with Chinese factor names, and limited the
  factor-value table to the latest compute run so historical runs do not create
  duplicate securities.
- Reorganized `/data` around an operator-first hierarchy. The default view now
  states whether research data is usable, surfaces only the highest-priority
  blockers and four decision metrics, while research datasets, market
  coverage, sync jobs and provider permissions live in dedicated sections.
- Removed implementation identifiers from the primary Strategy, Paper and Data
  reading layers. UUID fragments, content hashes, snapshot IDs and raw
  `paper_eligible` values are replaced by localized strategy versions,
  verification states, binding states, research periods and data cutoffs.

23. BitPro full-workspace readability and state parity closeout
- Matched the Paper instance-card runtime indicator to BitPro: a running
  strategy now uses a green breathing light. A delayed heartbeat is shown as a
  separate amber warning and no longer turns the running state red.
- Removed the remaining user-facing UUIDs, numeric database keys, task keys,
  snapshot keys, account IDs and content hashes from Watch, Monitor, Backtest,
  Stock Pools, Factors, AI Research, Data and shared detail panels. Internal
  keys remain in routes, API requests and persisted audit records.
- Replaced Monitor's raw dataset and market JSON dumps with readable snapshot
  status, trade date, cutoff, availability and integrity rows. Risk tables now
  identify the related strategy by name instead of a source-object key.
- Localized AI research admission states and version bindings; backtest and
  factor workspaces now describe sealed data and fixed universes without
  presenting database IDs as product versions.
- Completed read-only browser acceptance for all 13 primary routes, 30
  query-addressable secondary tabs, all five factor analysis workspaces,
  Backtest detail and Paper instance detail. Desktop and 390px layouts had no
  page-level horizontal overflow, browser console errors or failed API
  responses.

24. Configurable market-color consistency
- Removed hard-coded red/green gain and loss colors from the active dashboard,
  market research, stock charts, backtest, Paper runtime and shared detail
  components, including legacy routes that can still be reached through
  redirects or embedded panels.
- Routed text, metric cards, candlesticks, volume bars, intraday lines and
  market-flow charts through the persisted `redUpGreenDown` /
  `greenUpRedDown` setting. Zero and missing directional values now use a
  neutral tone instead of being classified as gains.
- Added browser regression coverage that verifies positive, negative and zero
  monthly backtest returns under both color schemes.

25. BitPro workspace navigation hierarchy
- Replaced full-width button-strip navigation with a shared content-width,
  underline-style workspace tab component across Market, Stock Pools, Factors,
  Monitor, Daily Review, Watch, AI Research, Paper detail and Data Center.
- Kept scope, status and sort switches as compact segmented controls so
  workspace navigation and filtering no longer share the same visual weight.
- Localized the remaining AI Research environment and execution labels; raw
  provider configuration names are no longer exposed in the product view.

## Verification Evidence

- `python3 -m py_compile app/services/scheduler_service.py app/db/postgres_db.py app/api/endpoints/data_dev.py` (pass)
- `python3 -m py_compile app/services/batch_import_service.py app/api/endpoints/batch_import.py app/db/postgres_db.py` (pass)
- backend smoke:
  - fundamentals insert/read/search on temp DB (pass)
  - `search_stocks` returns `price/change_percent` correctly from `current_price`
- `npm run lint` (pass)
- `npm run check` (pass)
- `npm run build` (pass)
- `./scripts/check.sh` after full-workspace readability closeout (pass:
  frontend build/lint with 5 existing Hook warnings, 289 backend tests, Python
  compilation)
- `./scripts/check.sh` after configurable market-color consistency (pass:
  frontend build/lint with 5 existing Hook warnings, 289 backend tests, Python
  compilation)
- `./scripts/check.sh` after workspace navigation hierarchy alignment (pass:
  frontend build/lint with 5 existing Hook warnings, 289 backend tests, Python
  compilation)
- Focused mocked Playwright market-color and market-research checks (2/2 pass)
- Real-browser Backtest detail verification under both color schemes: positive
  and negative values swap colors as configured; zero stays neutral (pass)
- Real-browser workspace navigation review on Monitor, Market, Factors, Data
  Center and AI Research at desktop width, plus Monitor at 390px (pass; no
  browser console errors)
- Playwright primary-route sweep at desktop and 390px (13/13 pass; no visible
  UUID/task/account/snapshot keys and no page-level horizontal overflow)
- Playwright secondary/detail sweep (30 query-addressable tabs, 5 factor
  workspaces, Backtest detail and Paper detail pass; no console errors or
  failed API responses)
- `./scripts/check.sh` after BitPro page parity (pass: frontend build/lint, 287 backend tests, Python compilation)
- `backend/venv/bin/python -m pytest tests/test_paper_runtime_api.py` (pass, 13/13)
- Real-backend read-only browser gate for all twelve primary routes (pass, 1/1)
- `npm run test:e2e` (pass, 2/2)
- `npm run test:e2e` after dual-mode (pass, 2 passed + 3 skipped)
- `scripts/backend-health.sh` (pass)
- `npm run test:e2e:real` with backend on `:8001` (pass, 4/4)
- `npm run test:e2e` latest (pass, 2 passed + 4 skipped)
- `npm run test:e2e:real` with backend test mode (`ENABLE_* = false`) (pass, 4/4)
- `npm run test:e2e:real` with full offline flags (`ENABLE_* = false`, `ENABLE_EXTERNAL_MARKET_FETCH=false`) (pass, 4/4)
- `python3 -m py_compile app/api/endpoints/data_dev.py app/api/endpoints/database.py` (pass)
- `npm run lint` (pass, latest)
- `npm run check` (pass, latest)
- `npm run test:e2e:real` after deep assertions (pass, 7/7)
- `npm run test:e2e` latest (pass, 2 passed + 7 skipped)
- `venv/bin/python -m pytest tests/test_market_overview_fast_path.py tests/test_market_cache_sync_fallback.py` (pass, 4/4)
- `npm run build` (pass)
- Manual `/api/data/realtime/sync` after EM proxy failure: stocks 5528, indices 4, short_line 3; `/api/market/overview` returned fresh sentiment, turnover split and breadth.
- Manual `/api/market/hot-concepts?limit=30` returned 30 items.
- Paper parity focused checks:
  - `venv/bin/python -m pytest tests/test_paper_runtime_api.py -q` (15/15 pass)
  - `/api/paper/instances/{id}` (200, latest cycle success, signal count 1)
  - `/api/paper/instances/{id}/klines/SZ_002415` (200, 485 sealed bars)
  - target strategy visible in `/api/strategy/list`
  - Playwright desktop + 390px viewport pass; no browser console errors
  - Factor research Playwright audit across all six tabs at desktop and 390px
    widths (pass; no browser console errors after clean local restart)

## Known Gaps

1. Global system python env may miss transitive deps; backend startup is currently reliable via `backend/venv`.
2. Data module is stable at schema/API level, but large-data performance and long-running job reliability still need prolonged real-run validation.
3. Real-backend suite now covers core data flows, but long-duration reliability under high data volume is still unverified.

## Recommended Next Steps

1. Add deeper real-backend assertions for `market/overview`, `database/query`, and `data-dev` CRUD flows.
2. Use `scripts/backend-health.sh --ping` + `npm run test:e2e:real` in CI/预发 gate.
3. Add integration test for `stocks/search`, `data-dev/tasks`, and `batch-import/historical-data` against a temporary Postgres database.

## Remote development PostgreSQL cutover (2026-08-10)

- Changed local development startup to use an SSH tunnel to an isolated server PostgreSQL database instead of starting `stockpro-postgres` on the Mac.
- Added explicit tunnel start, stop and status handling with a dedicated SSH control socket and port-conflict checks.
- Kept the Docker PostgreSQL service only behind the opt-in `local-db-recovery` profile with automatic restart disabled; it is no longer part of normal startup.
- Updated the environment example and current architecture/operations documentation. Real credentials remain only in the ignored `backend/.env`.

## Documentation system refresh (2026-07-29)

- Rebuilt `README.md` as the canonical Chinese product introduction, with the current 12-workspace map, evidence-based research lifecycle, local-only Paper boundary, architecture, setup, configuration, verification and documentation links. Updated the English entry and made `README.zh-CN.md` a stable pointer to the canonical Chinese document.
- Added `docs/index.md` as the documentation map. Rewrote the current product specification, user guide, API guide, local operations guide, technical architecture and data architecture around the implemented React/FastAPI/PostgreSQL system.
- Replaced stale StockApp routes, automatic-startup writes, Electron-first architecture and simulated/live-trading claims. Updated frontend, strategy and script usage guides; marked early Electron, optimization, Provider and test notes as historical/reference material.
- Documentation-only change: no frontend/backend source changed, no service restart and no remote deployment were required.
- Verification passed: `git diff --check`; local Markdown link audit checked 61 files with no missing local targets.

## Public documentation boundary cleanup (2026-07-30)

- Removed the private `Private/BitPro/StockPro` directory example, sibling-repository instructions and comparison-project implementation notes from the public README, English README, local operations guide, frontend guide, product specification and architecture overview.
- Removed Codex-oriented maintenance/reference links from the reader-facing documentation index. Internal delivery rules and historical audit records remain in their dedicated project files rather than appearing as product setup guidance.
- Documentation-only change: no application source changed, no service restart and no remote deployment were required. Verification passed: `git diff --check`; reader-facing Markdown scan found no remaining absolute user paths, private directory examples or internal tool instructions.

## MIT license declaration (2026-07-30)

- Added the repository-level standard MIT license with copyright holder `shadowell`, and linked it from the Chinese README, English README and documentation index.
- Clarified that the MIT grant covers repository-owned source code and documentation, while market data, AI services, third-party APIs, dependencies and their outputs retain their own licenses and service/data restrictions.
- Documentation/legal-metadata-only change: no application source changed, no service restart and no remote deployment were required. Verification passed: `git diff --check` and local documentation link validation.

## GitHub Actions deployment recovery (2026-08-01)

- Diagnosed the repeated `Deploy StockPro` failures as two independent faults: the frontend depended on the unavailable sibling path `../../BitPro/packages/bitpro-ui`, then the self-hosted production runner's local PostgreSQL service was stopped while migrations expected `127.0.0.1:5432`.
- Moved the required `@bitpro/ui` primitives into `frontend/packages/bitpro-ui`, changed the npm file dependency to the repository-contained package, and added a dependency-boundary check to prevent future CI builds from referencing files outside StockPro.
- Updated the production deploy script to start local PostgreSQL when required and wait for a real database connection before migrations.
- Local verification passed after a clean frontend/backend restart: `./scripts/check.sh` (frontend build, dependency guard, lint with 6 existing warnings, deploy shell syntax, 290 backend tests and Python compilation) and `git diff --check`.
- GitHub Actions run `30696038264` succeeded for commit `7b831bc630a7f1b395855227c3d9ac2882221803`: frontend build, server deployment and deployed-SHA recording all passed. The workflow log confirmed PostgreSQL, backend and frontend readiness; the public frontend and `/api/health/health` both returned HTTP 200.
- A non-blocking Node cache-save warning remains on the self-hosted runner (`tar` exited while saving the npm cache). It did not fail the job or affect the deployed application and should be handled as runner storage/cache maintenance rather than application rollback.

## Platform professionalization audit baseline (2026-08-09)

- Started the current `StockPro Platform Professionalization` contract and
  established `docs/todo.md` as the single prioritized delivery queue.
- Completed read-only browser coverage of all 12 primary workspaces at 1280px
  and 390px, all URL-addressable secondary tabs, six Factor workspaces, five
  Data Center workspaces, Data Processing and compatibility workspaces, eight
  Backtest detail tabs, and Paper detail.
- Confirmed two P0 evidence defects: contradictory limit-up evidence on the
  dashboard and three unexplained prices for the same stock/cutoff on the stock
  research page.
- Confirmed P1 operator defects: stale Paper evidence shown as running/real-time,
  missing review counters rendered as `undefined`, test/acceptance objects in
  business lists, invisible active mobile navigation, clipped Data Center
  actions, and non-trading dates in data/review workflows.
- Baseline `./scripts/check.sh` passed before changes: frontend build and lint,
  deployment shell syntax, 290 backend tests and Python compilation. Remaining
  baseline warnings are six React Hook dependency warnings, a large Vite entry
  chunk and FastAPI `on_event` deprecation.
- This audit did not trigger synchronization, task execution, Paper controls,
  strategy creation, database writes, external Provider calls or deployment.

### SP-004 review counter contract fix

- Changed the daily-review API count contract to return all supported timeline
  categories with explicit zero values, including an entirely empty timeline.
- Added a defensive frontend count accessor so older or partial responses also
  render `0` rather than interpolating JavaScript `undefined`.
- Added backend regression coverage for grouped and empty counts, plus mocked
  browser coverage for partial API payloads and failed evidence loading.
- Completed clean local frontend/backend restart. Both ports listened, the
  application and PostgreSQL health endpoints were healthy, and the real
  2026-08-07 Review page displayed `0 / 0` with no undefined value.
- Verification passed: 13 focused backend tests, 2 focused mocked Playwright
  tests, `./scripts/check.sh` with 291 backend tests, frontend build/lint and
  Python compilation. The six pre-existing Hook warnings, large Vite vendor
  chunk and FastAPI lifespan deprecation remain tracked in SP-016/SP-017.

### SP-003 runtime truth presentation fix

- Paper cards now reserve the animated green indicator for a running lifecycle
  whose heartbeat satisfies the 15-minute SLA. A running database lifecycle
  with a missing or stale heartbeat is amber and explicitly labelled
  `生命周期运行中` plus `心跳陈旧`; the detail page uses the same distinction.
- Replaced Watch's fabricated 30-day, `100% 实时监控中` Tracker with five real
  evidence domains: instances, signals, orders, trades and alerts. Their color
  and tooltip now derive from the API's fresh/stale/empty/error state.
- Monitor now separates the historical cycle result from current freshness,
  localizes Paper service names, renders missing error codes as `--`, and tones
  lifecycle status using current runtime health when the two disagree.
- Added three mocked browser regressions covering a missing Paper heartbeat, a
  stale Watch snapshot and a historically healthy but currently stale Monitor
  service. All three pass.
- Completed clean local frontend/backend restart and verified healthy app/PG
  endpoints. Real pages show amber lifecycle/heartbeat badges, an amber
  evidence-based Watch tracker and `正常` + `数据滞后` as separate Monitor
  columns. `./scripts/check.sh` passed with 291 backend tests.

## Professionalization implementation batch (2026-08-10)

- Implemented formal sealed-evidence handling for the limit board, same-date
  market price conflict quarantine, test/acceptance purpose classification,
  mobile active-navigation discovery, Data Center action wrapping, canonical
  trading-date resolution, and reloadable Strategy detail links with explicit
  business-count semantics.
- Added backend regressions for TuShare full-market row binding, formal limit
  evidence, purpose classification, trading-date rules, review-date filtering,
  data-task date gates and isolated admin authentication. The repository check
  now passes 315 backend tests.
- Cleared all React Hook lint warnings, split React/chart/HTTP vendor chunks and
  added a build-time bundle budget. The current production build reports a
  327.8 KiB raw / 96.2 KiB gzip initial set and passes the configured limits.
- Separated the safe mocked page suite from real-backend and full-menu suites,
  updated its assertions to the current accessible UI contract, and completed
  43/43 mocked Playwright checks across desktop, mobile and all primary
  operator workflows.
- After explicit approval, established the remote-development PostgreSQL tunnel,
  cleanly restarted both local services with the scheduler disabled, and
  verified application health plus all 29/29 PostgreSQL migrations. The
  read-only real-browser audit now passes 12/12 primary pages and every covered
  sub-tab without page, console or HTTP errors.
- Hardened the real full-menu suite so it requires environment credentials,
  logs in and verifies the session once, defaults to read-only behavior, avoids
  `networkidle` on polling pages, and fails on page/console/network errors.
- The live run exposed synchronous PostgreSQL calls inside asynchronous Market,
  Pool, Factor, Strategy, Backtest, Data, Data Hub, Paper, Watch, Monitor and
  Review routes. Under a full-page workload these calls blocked the main event
  loop and delayed later login/health requests beyond 60 seconds. All surfaced
  blocking service calls now run in worker threads, storage health has a
  three-second connection timeout, and 13 focused thread-isolation regressions
  protect the affected route families.
- After a final clean restart, the real read-only full-menu suite passed 12/12
  in 43.5 seconds. The immediately following application health request passed
  in 0.002 seconds; storage health passed in 2.65 seconds with all 29/29
  migrations applied. `./scripts/check.sh` passed the production build, zero-
  warning lint, bundle budget, 315 backend tests and Python compilation.
- One safety defect remains tracked as SP-020: the first locally inherited
  `ENABLE_SCHEDULER=true` startup wrote 387 concept-flow rows to the remote
  development database at the hour boundary. Every final validation restart
  used `ENABLE_SCHEDULER=false`; no deployment, data repair or production
  mutation was performed.

### SP-001 A-share price-limit evidence completion

- Replaced the legacy global `ST = 5%` estimate with the exchange rules in
  force from 2026-07-06: Shanghai/Shenzhen main board including risk-warning
  stocks 10%, STAR/ChiNext 20%, and Beijing 30%.
- Enriched the PostgreSQL realtime stock cache read with point-in-time security
  status plus published trading-calendar evidence. Shanghai/Shenzhen IPOs are
  excluded for their first five trading days and Beijing IPOs for their first
  trading day. Official `N`/`C` security-name markers are a conservative
  fallback when the local security master has not yet published a new symbol.
- Kept the operator boundary explicit: sealed `limit_pool_members` remain the
  only formal limit-board membership; cache-derived counts remain labelled as
  estimates and are withheld if any stock has unknown rule evidence.
- A read-only real-data verification covered all 5,540 cached stocks: 5,537
  had active price limits, three IPO-stage stocks were excluded, and zero had
  unknown rule state. The resulting diagnostic estimate was 89 limit-up and
  six limit-down securities; the three excluded names were not counted.
- Verification passed 14 focused backend tests, `./scripts/check.sh` with 320
  backend tests, clean frontend build/lint/bundle budget, and the real-backend
  Dashboard/Market browser suites 2/2. The post-load health endpoint responded
  in 0.002 seconds. Scheduler, realtime sync and strategy execution remained
  disabled; no database write or deployment was performed.

### SP-002 stock price provenance completion

- Added explicit `price_basis` and `price_usage` metadata to PostgreSQL daily
  bars, cached valuation snapshots and on-demand order-book responses.
- The stock terminal now presents three independent evidence cards: unadjusted
  daily bars for research, an unadjusted valuation cache for same-snapshot
  fundamentals, and an unadjusted order book for execution-time reference.
  Each card exposes its source and relevant date/time and explains what the
  value may and may not be used for.
- Preserved the existing hard quarantine: when daily and fresh order-book
  evidence share a trade date but diverge beyond the consistency threshold,
  the terminal removes the consolidated price/change claim and displays both
  conflicting sources instead of choosing one silently.
- Verification passed the fail-first mocked conflict/provenance browser test,
  the real-backend Market suite across all six tabs, and `./scripts/check.sh`
  with the production build, lint, bundle budget, 320 backend tests and Python
  compilation. The post-load health endpoint responded in 0.001 seconds.

### SP-005 business/audit isolation completion

- Added a persisted `data_purpose` contract for strategy definitions, Paper
  instances and stock pools, with legacy acceptance/seed backfill in migration
  `202608100001_business_audit_scope.sql`.
- Strategy, Watch and Monitor APIs now default to `scope=business`; explicit
  `scope=audit` preserves and returns acceptance/seed evidence without mixing it
  into business lists, counts, alert totals or notification totals.
- Added compact business/audit controls to all three operator pages. Strategy
  acceptance records now have a dedicated audit tab and no longer enter My
  Strategies or the reference-template count.
- TDD verification passed 35 focused backend contracts, the repository check
  with 324 backend tests, production build/lint/bundle budget, and the complete
  43-test mocked browser suite. Both local services were cleanly restarted with
  scheduler, realtime sync and strategy execution disabled.
- After explicit operator approval, applied only
  `202608100001_business_audit_scope.sql` to the isolated `stockpro_dev`
  database. Storage health reports 30 migration files and 30 applied.
- Real API/browser acceptance verified that business scope returns only `user`
  objects, audit scope preserves acceptance evidence, all three pages can switch
  scope, and the existing Paper-to-Watch-to-Monitor evidence chain remains
  resolvable. No deployment or production service mutation was performed.

### SP-010 primary reading layer localization completion

- Added one compact diagnostic disclosure for operator pages. Stock Pool input
  bindings and sealed snapshots now use business descriptions instead of
  `Dataset #` / `Universe #` / `Factor #` / `Market #`; raw identifiers remain
  available only after explicitly expanding the diagnostic row.
- Daily Review localizes standalone timeline enum tokens such as `post_close`,
  `all_a`, `published`, `buy` and `sell` without changing the persisted audit
  record. Monitor keeps service codes and actual null values in diagnostics
  while the main table shows Chinese service labels and `--`.
- TDD evidence captured the original `Dataset #10` failure before the fix.
  Focused Mock acceptance then passed, followed by the complete 44/44 Mock
  browser suite and `./scripts/check.sh` with a production build, zero-warning
  lint, bundle budget, 324 backend tests and Python compilation.
- Both local services were cleanly restarted with scheduler, realtime sync,
  strategy execution, runtime bootstrap and external market fetch disabled.
  Application health and isolated `stockpro_dev` storage health passed with
  30/30 migrations.
- Read-only real-browser acceptance passed for Review and Monitor business/raw
  evidence. The isolated business scope currently has no Stock Pool record, so
  the real page truthfully verified its empty state; populated binding behavior
  remains covered by the Mock fixture. No database write or deployment ran.

### SP-011 factor maturity funnel completion

- Replaced the shared definition denominator with a research maturity funnel:
  factor definitions, sealed computations, matured evaluations and strategy-
  eligible factors now have explicit, stage-specific denominators.
- Added independent cross-sectional, time-series, out-of-sample and point-in-
  time leakage gates. Missing mature evidence renders `--` plus the blocking
  reason rather than a misleading 0% performance conclusion.
- TDD captured the missing maturity contract before implementation. The full
  Mock browser suite passed 45/45, and read-only real-backend acceptance
  confirmed all 100/100 installed factor definitions plus the four visible
  gates. `./scripts/check.sh` passed build, zero-warning lint, bundle budget,
  324 backend tests and Python compilation.
- Both services were cleanly restarted with scheduler, realtime sync, strategy
  execution, runtime bootstrap and external market fetch disabled. Application
  and isolated `stockpro_dev` storage health passed with 30/30 migrations. No
  factor compute, metric maturity job, database write or deployment ran.

### SP-012 stock-pool validity and binding gates completion

- Stock-pool members and sealed snapshots now distinguish current candidates
  from expired historical research. Expired snapshots retain reproducible
  historical backtest handoff but no longer present themselves as currently
  usable; internal snapshot identifiers remain inside explicit diagnostics.
- Generation rejects datasets that do not cover the target date, Universe
  snapshots from another date, missing factor or market evidence, and
  incompatible factor bindings before writing a generation row. Sealing
  revalidates the stored input manifest, trade date, member validity and
  evidence hashes before creating an immutable snapshot.
- Snapshot responses expose the earliest member validity date and persisted
  data purpose. The business page filters acceptance and seed snapshots from
  counts and rows, closing the remaining Stock Pool business/audit display gap.
- Optional market research evidence now loads progressively. A slow market
  context can disable sector/event generation without blocking the rule
  catalogue or sealed snapshot repository.
- TDD captured the invalid binding, expired snapshot and acceptance-leakage
  failures before implementation. Verification passed 33 focused Stock Pool
  backend tests, the complete 45/45 Mock browser suite, one read-only real
  `stockpro_dev` Stock Pool E2E, and `./scripts/check.sh` with 330 backend tests,
  production build, zero-warning lint, bundle budget and Python compilation.
- Both local services were cleanly restarted with scheduler, realtime sync,
  strategy execution, runtime bootstrap, external market fetch and automatic
  migration disabled. Application and storage health passed with 30/30
  migrations; no database write, migration, deployment or remote service
  mutation ran.

### SP-013 strategy research protocol and Paper promotion gates completion

- Sealed research protocols now require ordered train, validation and untouched
  out-of-sample windows, explicit embargo days, a fixed benchmark, capacity
  limits and return/Sharpe/drawdown promotion thresholds. Full runs bound to a
  protocol must cover every segment and use the protocol benchmark.
- Successful full runs automatically seal eleven independent promotion checks:
  full-result manifest, protocol, all three sample segments, cost evidence,
  capacity rule definition and observed capacity, threshold definition,
  benchmark evidence and data quality. Zero-valued metrics remain valid values
  rather than falling through as missing.
- Paper candidate lists require the complete passed check set, and Paper
  creation rechecks the same set server-side. Legacy or partial
  `paper_eligible` labels cannot bypass the gate. Quick previews remain
  diagnostic-only and explicitly show that they cannot enter Paper.
- Backtest detail now presents the immutable protocol intervals and promotion
  evidence. Core results load first, the NAV series follows independently, and
  positions/orders/trades/logs/attribution load only when their tab opens. This
  removed the real-data page stall caused by eagerly reading five large ledgers.
- TDD captured invalid protocol windows, missing validation/capacity/threshold
  contracts, zero-threshold handling, missing cost/benchmark evidence,
  capacity overflow, incomplete Paper checks and quick-preview leakage before
  implementation. Verification passed 47 focused backend contract assertions,
  the complete 47/47 Mock browser suite, one read-only real `stockpro_dev`
  full-backtest browser acceptance, and `./scripts/check.sh` with 341 backend
  tests, production build, zero-warning lint, bundle budget and Python
  compilation.
- Both local services were cleanly restarted with scheduler, realtime sync,
  strategy execution, runtime bootstrap, external market fetch, automatic
  migration and Paper recovery disabled. Application and storage health passed
  with 30/30 migrations; no database write, migration, deployment or remote
  service mutation ran.

## SP-014 BitPro 流程对齐：AI 策略研发闭环与操作台改造（进行中）

Sprint 合同：`docs/contracts/active-bitpro-flow-parity.md`

### 后端（已完成，374+ 测试通过）

- 新增 `backend/app/services/agent/` 多智能体研发闭环：Planner 规格书 →
  Sprint 合约 → Strategist(LLM) 生成 Strategy API v1 代码 → AST 沙箱
  （复用 `validate_strategy_python`，一次修复重试）→ Backtester 复用
  `BacktestWorkbenchService.run(mode="quick")` 生产链路 → Evaluator 多维评分
  （LLM 失败退化为确定性评分）。达标判定只用回测指标硬阈值。
- 迁移 `202608170001_agent_strategy_research.sql`：`agent_tasks` /
  `agent_iterations`；`main.py` 启动时 `recover_interrupted()` 续跑中断任务。
- 端点 `/api/agent/*`：任务 CRUD、start/stop、迭代、promote（要求
  validation_status=valid）。写入仅管理员。
- 实盘工作台后端：迁移 `202608170002_live_trading_workbench.sql`
  （`live_trading_events` 审计）、`live_trading_service.py` + `/api/live/*`
  （status/promotion-candidates/preflight/enable/events）。预检含券商通道
  （xtquant/ptrade 探测）、`LIVE_TRADING_ENABLED` 开关、11 项晋级门控、风控
  限额与交易时段；未就绪时 enable 请求被阻断并留痕，绝不发出真实委托。
- 配置新增 `QWEN_BASE_URL`、`LIVE_TRADING_ENABLED`（默认 false）等。
- 测试：`test_agent_research.py`（12 项：沙箱拒绝、达标完成、恢复、目标校验）、
  `test_live_trading_service.py`（5 项：无通道阻断、门控、双重确认）。

### 前端（并行实施中）

- client.ts/types 新增 agent + live 全套 API 与类型。
- 策略页 AI 研发面板、回测台改造、模拟实例卡片、复盘大盘 Snapshot、
  实盘工作台页面由并行任务实施，随后统一验证。

### 复盘页大盘 Snapshot 改造（本切片已完成，待随 SP-014 统一提交）

- `frontend/src/pages/DailyReview.tsx` 重构为"当天大盘 Snapshot"单屏结构：
  头部（交易日选择 + 生成复盘 + 状态 chip）→ Snapshot 六块（指数快照 /
  市场宽度 / 情绪指标 / 涨停生态+连板天梯 / 板块资金 TOP8 / 人气榜 TOP10，
  全部并行加载、块内独立 loading/error/empty，块头标注来源与数据时间）→
  复盘结论（当日结论 / 次日计划编辑 + 保存/封存，逻辑不变）+ 复盘记录 +
  风险提示（风险类证据只读汇总；复盘接口无独立风险文本字段，未伪造）→
  证据时间线（原五个子页签合并为类别 chip 筛选）。
- 数据真实性：仅渲染 `getMarketOverview/getShortLineIndices/getLimitBoard/
  getLianbanLadder/getSectorFundFlow/getThsHot` 实际返回字段；指数不含
  成交额、MarketOverview 无停牌家数与昨日涨停表现、板块资金无单股主力口径
  ——均省略不造数；同花顺人气榜热度兼容 `hot`/`hot_value` 两种负载字段。
- 验证：`npx tsc --noEmit` 与 `npm run build`（含 bundle budget）通过；
  本地前后端已按规范重启，`/api/health/health` 通过，Vite 正常提供
  `/review`（浏览器可视验收因当前子代理无浏览器留待统一验证）。

### 模拟盘 BitPro InstanceDashboard 重塑（本切片已完成，待随 SP-014 统一提交）

- `frontend/src/pages/Paper.tsx`（1256 → ~380 行）重塑为 BitPro 模拟盘
  InstanceDashboard 形态：控制台（实例卡片网格）/ 创建向导 / 实例详情三视图。
  全部生命周期调用（`createPaperInstance`、`paperInstanceAction`
  start/pause/resume/stop、`processPaperCycle`、列表/详情读取）原样保留，
  仅表现层重塑；清除仅剩死代码路径的旧表格/页签标记。
- 轮询：指标每 10 秒批量刷新（单次 `listPaperInstances`，静默失败保留上一份
  数据），列表每 60 秒全量静默刷新（含晋级回测与选中详情），页面隐藏时暂停。
- `PaperInstanceDashboard`：单一"模拟盘"页头 + 创建 Paper 实例入口；状态
  segmented（全部/运行中/暂停/已停止带计数）+ 名称搜索 + 排序 segmented
  （创建时间↓ / 收益率↓；夏普/胜率列表负载未提供故不设排序项）；卡片网格
  md:2 / lg:3 / xl:4，卡片含运行呼吸灯（绿=运行、灰=暂停、红=失败/停止、
  琥珀=心跳陈旧）、初始资金（¥100万 口径）/周期/创建日期 pills、收益率大字
  （text-up/text-down + tabular-nums）+ 总盈亏、夏普/胜率/盈亏比/交易次数
  四格（缺失显示"—"不显示 0）、暂停/继续/启动/关闭/详情操作（新增
  `ConfirmDialog` 二次确认，关闭为危险态警示）。
- `PaperRuntimeInstanceDetail`：页头补实例 ID（mono）；启动/暂停/恢复/停止
  全部接入 ConfirmDialog 确认；KPI 行、账户曲线、持仓、成交与事件、诊断
  日志、K 线复盘、风控状态等结构与证据列不变；访客只读仍由
  MainLayout DOM 守卫 + client.ts 请求拦截双层兜底（按钮文案保留
  暂停/停止/启动等关键字）。
- 验证：`npx tsc --noEmit` 与 `npm run build`（含 bundle budget）通过；
  本地前后端已按规范重启，`/api/health/health` 与 Vite `/` 均 200。

### SP-014 统一验证与缺陷修复（收尾）

- 端到端联调发现并修复三处缺陷：
  1. `universe_snapshot_members` 查询误用 `ordinal` 列（改为 `ORDER BY symbol`）；
  2. `paper_instances` 误用不存在的 `initial_cash`/`last_cycle_at` 列（改为
     `parameters->>'initial_cash'` 与 `last_processed_trade_date`）；
  3. 前端 `WorkflowRail` 在研究台负载缺少 `pipeline` 时整树崩溃
     （`ResearchDeskContext` 增加结构防御，rail 对空 pipeline 安全降级）。
- mock e2e 套件从 47 失败修复至 49/49 通过，其中按"页面缺产品必需面"修复：
  Dashboard 热榜陈旧守卫恢复（陈旧缓存不再冒充当前信号）、
  MainLayout 移除与分组侧栏重复的第二导航、快速回测"不可晋级"提示恢复可见、
  回测详情补回夏普与判决带 testid、复盘页证据失败态诚实呈现（`--` 而非 0）、
  数据中心补最近质量报告面板（只读 GET，不自动触发检查）；
  其余为有意的页面/导航合同变更对应的等强度断言更新（13 项一级导航含实盘、
  新页头、回测判决带/晋级检查/六页签、复盘 Snapshot 单页合同、模拟盘卡片网格、
  策略页 AI 研发标签等）。
- 本地验证：后端 379 项 pytest 全过；`npx tsc --noEmit`、`npm run build`
  （含 bundle budget）、`npm run lint`（0 错误）通过；`./scripts/check.sh` 全绿；
  mock Playwright 49/49。数据库隧道经 `scripts/database-tunnel.sh` 恢复，
  迁移 202608170001/2 已显式应用（agent_tasks/agent_iterations/live_trading_events）。
- 真实冒烟：`/api/agent/config` 正确解析最新封存快照/Universe/成本模型默认值；
  `/api/live/promotion-candidates` 返回真实 paper_eligible 完整回测；
  `/api/live/status` 如实报告通道未配置与安全边界。
- 已知边界：本机未配置真实 `QWEN_API_KEY`（BitPro 环境中亦为占位符），
  AI 生成任务在页面与 API 均明确显示"QWEN_API_KEY 未配置"并以失败留痕，
  配置后无需改动即可运行完整闭环（后端单测已覆盖沙箱拒绝/达标/恢复路径）。

### 数据中心冷启动读取修复（2026-08-17）

- 根因：数据中心首次读取会先建立 PostgreSQL 隧道连接，多个模块同时请求时超过前端原有 8 秒页面读取超时，导致真实的就绪数据被误显示为仓库不可用、空覆盖和空任务。
- 修复：`/data/status` 使用 20 秒冷启动读取窗口；数据中心先完成状态读取再并行加载其余模块；增加页面内请求去重，避免 React 开发态重复挂载放大冷启动并发。
- 真实冒烟：总览显示 PostgreSQL 就绪、研究快照已封存、日线 33,238 条、覆盖 80/80；研究数据 10/10 已发布；行情覆盖 80 个标的；同步任务明细 10 条；数据源目录 86 个端点。
- 已知数据告警：最近同步任务仍有 2 次失败、1 个失败项，缓存同步成功率 76%；页面继续如实呈现告警，未执行外部同步或数据自愈。

### 生产域名与 HTTPS（2026-08-17）

- 正式入口改为 `https://stockpro.notenap.com`；HTTP 与
  `www.stockpro.notenap.com` 永久跳转到主域名，`:4444` 仅保留兼容访问。
- Nginx 在共享 443 SNI 分流后使用独立本机端口 `127.0.0.1:8451` 终止 TLS，
  避免影响同机其他产品；证书覆盖主域名和 `www`，由 Certbot timer 自动续期。
- 部署脚本新增 HTTPS 健康检查，只有域名下的后端健康接口成功才记录部署完成。

### 自托管 Runner 构建依赖去外部化（2026-08-17）

- GitHub Actions 连续两次在任务初始化阶段下载 `actions/setup-node` 时收到
  codeload 429，尚未执行仓库构建或部署。
- StockPro 专用 Runner 已固定提供 Node.js 22 / npm 10，满足项目 Node.js 18+
  与 npm 9+ 合同；部署改为本机版本门禁，继续使用干净的 `npm ci` 和完整前端构建，
  避免发布依赖第三方 Action 归档下载可用性。

## 2026-08-25 BitPro 当前基线 1:1 重移植（进行中）

- 用户否决近似复刻，要求以 BitPro 为唯一事实基准直接移植，再只做 A 股领域替换；旧版“已完成”结论因此重新打开。
- 当前 BitPro `main` 固定为 `aecd03f75d0ef11e18d219da97fecae9613f2a64`。导入器、来源测试、完成审计和总控计划已同步到该提交；导入器只接受 `codex/*` 分支并从 Git object database 读取，不读取 BitPro 未提交工作区。
- 首轮差异盘点确认目标前端 50 个同路径文件中只有 25 个字节级相同；策略、回测、监控、数据和 AI 研发等关键页面仍显著偏离，不能继续声称 1:1 完成。
- 首页第一条 TDD 切片把 BitPro 的“市场大盘”外层合同、三枚运行状态标记和两个原生面板边界恢复到 A 股页面，同时保留真实 `/api/market/overview`、PostgreSQL 来源状态及缺失值语义。
- 当前来源导入仅完成 dry-run，尚未覆盖应用树；`docs/reference/bitpro-baseline/source.json` 仍保留旧导入事实，直到当前 BitPro 应用真正导入后才更新，避免把计划冒充完成状态。
- 重启验收发现 `restart.sh` 仍探测已经删除的 `/api/health/health`，而当前唯一健康接口 `/api/health` 正常返回 200。新增脚本合同测试完成 RED→GREEN 后，第二次干净重启通过前端 4444、后端 4445 和健康门禁。
- 真实浏览器使用管理员会话读取本地 PostgreSQL 首页：标题、三枚 A 股状态标记、4 个真实指数、市场宽度、涨跌停生态、空板块资金原因和策略→回测→模拟入口均可见；未使用请求拦截或 DOM 注入。
- 首页 Mock Playwright 桌面/390px 共 2 项通过，Vite 生产构建与本轮文件零警告 lint 通过。全量 `tsc` 当前被任务前既有的未跟踪 `frontend/src/pages/liveTrading/` 半套 BitPro 文件阻断；该目录保留不删，下一切片补齐来源模块并接 A 股 API 适配后再恢复全量类型门禁。
- 已补齐上述 `liveTrading` 的 4 个缺失 BitPro 原文件和 `selectionStyles`，原有 7 个文件经逐文件比较均与当前 BitPro 完全相同。兼容 API 只转到 StockPro 的 A 股 Paper/券商预检合同；无实例 ID 的控制操作 fail-closed，未重新注册真实交易路由。
- 补齐后全量 `npm run check`、`npm run build`、零警告 `npm run lint` 通过；首页与现有模拟盘 3 个 Mock Playwright 回归通过。`rebuild/assert_safety.py` 继续通过，五类活动风险计数均为 0，未注册的 BitPro 实盘组件仅作为 quarantine 来源保留。
- 首次全量 `check.sh` 暴露测试隔离递归：`test_isolation_db_setup` 删除进程环境变量后，子 `check.sh` 又读取本机 `backend/.env`，形成 `check.sh → pytest → check.sh`。新增 `STOCKPRO_CHECK_SKIP_ENV_FILE=1` 测试专用门禁和 10 秒超时后，该组 4/4 通过；递归子进程已全部退出。
- 使用现有 SSH 隧道凭据只替换数据库名，确认远端隔离库 `stockpro_bitpro_rebase_dev`，未连接生产库执行测试写入。全量门禁已通过 105 个后端/重建测试、前端类型、lint、生产构建、bundle 预算、生产依赖审计和 25/25 Mock 浏览器矩阵；旧首页标题断言已更新为当前 BitPro 的“市场大盘”。
- 策略页不再保留 105 行自研薄壳：以当前 BitPro 1501 行策略工作台为结构基线，恢复“我的策略 / 策略广场”、AI 写策略、五组筛选、18 条分页、完整编辑器和详情页；`strategyApi.getPage` 在 A 股当前 API 上做稳定分页/计数适配。
- 策略资产、类型、周期、资金、AI 候选证券、编辑器市场和下单单位已替换为股票/ETF、动量/均值回归/多因子/事件、A 股周期、人民币规模、证券代码和股数；详情继续显示封存输入、100股、T+1、只做多。策略页 `tsc`、零警告 lint 和 Mock E2E 通过。
- 真实管理员浏览器从当前 PostgreSQL 读取 78 个策略，BitPro 四列卡片、18 条分页和完整筛选均可见；未运行策略的左侧 BitPro 操作位映射为“回测”，运行/暂停策略仍映射实例控制台，保持 A 股“策略→回测→模拟”主线。
- 全量前端生产构建、零警告 lint 和 25/25 Mock 浏览器矩阵通过。远程 PostgreSQL 冷连接曾使后端在原 30 秒窗口之后才就绪，进程和健康接口随后正常；重启条件等待扩展为 60 秒并新增合同测试，下一次干净重启正常通过。
- 回测页从 87 行薄壳替换为当前 BitPro 3176 行工作台，并同步导入 `backtestSupport`、结果对比、权益曲线、交易分析、AnimatedNumber 和动画 hook。页面恢复批量回测、实例搜索、状态/资产/周期筛选、排序、对比、异步任务、日志和完整详情结构。
- `backtestApi` 已桥接到当前 `/api/backtest/runs|jobs|configuration`，使用内存映射把不可变 UUID 安全接入 BitPro 数字视图 ID；策略 legacy ID 反向绑定真实 `strategy_version_id`。结果、任务、详情、series/orders/trades/positions/logs 均读取当前 PostgreSQL API，历史 run 不提供删除入口。
- 回测领域改为股票/ETF、沪深300、CNY 100 万元、A 股手续费/印花税/过户费/滑点、30m/60m/1d、T+1、100股和只做多；快速预检与完整协议重新成为显式选择。回测 `tsc`、零警告 lint 和 Mock E2E 通过。
- 真实管理员浏览器从 PostgreSQL 首屏读取 20/79 个 run：18 个完成、2 个失败，收益/回撤/Sharpe/成交与创建时间均来自当前 API；BitPro 左侧筛选、排序、对比和加载更多可见，未生成演示数据。
- 首次详情验收发现 BitPro 原实现并发读取 core+五类 ledger，在远程 PostgreSQL 下 6 个请求同时超过 30 秒。新增 RED 浏览器合同后改为核心详情先打开、完整证据显式按需串行加载；真实核心详情已显示策略收益 20.81%、回撤 19.56%、Sharpe 1.55、沪深300基准和 A 股审计模块。移动端筛选 key 警告同时修复。
- 回测完整前端生产构建、零警告 lint 和 25/25 Mock 浏览器矩阵通过；最终路由合同标题同步为当前 BitPro 的“回测”。
- 监控页从 26 行薄壳升级为当前 BitPro 2386 行参考实现加 A 股默认工作台。默认 `/monitor` 复用 BitPro 的页头、双总览、折叠监控配置、运行区和指标卡节奏，但唯一读取 `/api/monitor/summary`；原 OKX/实盘实现作为不可达 named source 保留，安全扫描标记 quarantine，未注册任何 live 路由。
- A 股监控显示 Paper 实例、运行中、健康异常、活动告警、整体状态、服务、Dataset、通知投递、逐实例生命周期/健康/心跳/权益/账本差异，以及服务/数据和调度证据；真实券商、USDT、多空比、资金费率和强平模块不渲染。监控 `tsc`、零警告 lint、Mock E2E 与安全审计通过。
- 真实管理员浏览器显示 22 个 Paper、21 个 running、6 个健康异常、200 个活动告警、762 个 delivered 通知、3 项服务证据和完整实例表；可见 fresh/failed/exhausted 与 running/stopped 独立，控制台没有数字资产/实盘请求。慢查询窗口提升到 60 秒并用 in-flight ref 阻止 30 秒轮询重叠。
- 监控切片的生产构建、零警告 lint、25/25 Mock 浏览器矩阵、强制重启和 `/api/health` 均通过。
- 数据中心完成当前 BitPro 2390 行 `DataManager` 源码导入；其 OKX 现货/合约/原生同步实现设为不可达 named source，`okxNativeSyncApi` 在 StockPro 明确 fail-closed，不注册接口。默认页面保留 BitPro 管理中心/KPI/工作区/表格节奏，唯一使用 PostgreSQL `dataCurrentApi`。
- 默认数据加载先读 `/data/status`，再用 `Promise.allSettled` 读取 datasets/snapshots/jobs/providers/quality/imports；八个工作区覆盖总览、研究数据、行情覆盖、同步任务、Qlib、数据源、质量和导入导出。数据页 `tsc`、零警告 lint、Mock E2E 和安全审计通过。
- 真实管理员浏览器显示 PostgreSQL 10 个研究数据集、2,777,870 条发布记录、34 个封存快照、Provider restricted、GET Provider 调用 0、16,989 个质量问题和 0 个暂存导入；八个工作区与真实快照列表可见，控制台无业务错误。
- 数据切片的生产构建、零警告 lint、25/25 Mock 浏览器矩阵、强制重启和 `/api/health` 均通过；最终路由标题同步为当前 BitPro 的“数据管理中心”。
- AI 研发完成当前 BitPro 2907 行 AILab 及 AutoAgent/ResearchWorkbench/Orbit/support 全套源码导入。旧 `/api/v2`、Orbit 和自动交易实现设为不可达 named source；默认页面恢复“AI策略助手”页头与自动交易Agent/AI自主交易/新策略研发/现有策略优化四卡导航，唯一使用当前 `/api/ai/*` 和策略合同。
- 默认 AI 工作台支持任务创建、启动、迭代详情、候选保存和现有策略诊断；模型未配置明确失败，不生成 mock，不自动运行完整回测、不创建/控制 Paper、不显示星球、OKX 持仓或自动实盘入口。AI 页 `tsc`、零警告 lint、Mock E2E 和安全审计通过。
- 真实管理员浏览器显示 `DashScope / Qwen · qwen3.6-plus · unavailable`，四个 BitPro 工作区、A 股研究配置和“封存证据研究 / Quick 回测 only / 不自动创建 Paper”门控可见；控制台无业务错误，未启动任务、未生成候选、未写 Paper。
- AI 切片的生产构建、零警告 lint、25/25 Mock 浏览器矩阵、强制重启和 `/api/health` 均通过；最终路由标题同步为“AI策略助手”。
- 信号中心完成当前 BitPro 2050 行源码导入。OKX Signal Bot/webhook/保证金/自动发送实现设为不可达 named source；默认页面恢复通道配置、信号策略列表、策略信号主表、投递记录和详情抽屉，但唯一读取当前信号与告警 API。
- 通道配置只读汇总 delivery 状态，策略列表按不可变版本/Paper lineage 聚合，管理员只能把 `new` 信号确认为 confirmed；页面没有买入、卖出、下单或真实发送动作。信号/盯盘 E2E、`tsc`、零警告 lint 和安全审计通过。
- 真实管理员浏览器显示 BitPro 四段信号工作台；当前 PostgreSQL 审计范围没有策略信号或投递记录，页面如实显示空状态，没有自动构造行或触发任何写操作，控制台无业务错误。
- 信号切片的生产构建、零警告 lint、25/25 Mock 浏览器矩阵、强制重启和 `/api/health` 均通过。
- 复盘中心完成当前 BitPro 671 行源码导入；默认页面恢复“复盘中心”页头、KPI、策略分层评分矩阵、策略好坏榜、复盘结论和证据时间线，并唯一读取当前交易日 review/items/metrics。
- 评分矩阵只按持久化 metric code 分组，榜单只消费 strategy/performance evidence；GET 不自动 assemble/save/seal，sealed 仍不可改。复盘页 `tsc`、零警告 lint 和 Mock E2E 通过。
- 真实管理员浏览器读取 sealed 复盘 `2025-01-02`：14 个证据对象、14 个指标、5 个风险事件、14 组评分矩阵、策略/表现榜、已封存总结与完整市场→股票池→策略→风险→订单→成交→权益时间线可见；`writes_performed=false`，控制台无业务错误。
- 复盘切片的生产构建、零警告 lint、25/25 Mock 浏览器矩阵、强制重启和 `/api/health` 均通过；最终路由标题同步为“复盘中心”。

## 2026-08-26 BitPro 基线同步

- BitPro 本地 `main` 前进到 `2e4b90c3f83672cb9c3fc2e31b772f6c52efacb1`。相对 `aecd03f7` 仅新增 `docs/research/strategy-analysis-2026-08-26-0008-favorites-core-loss-attribution.md` 并更新 BitPro 文档索引/进度，前端、后端、packages、scripts 和 tests 应用树无变化。
- StockPro 来源测试、导入器、完成审计、活动合同和总控计划已重新钉住该提交；未静默漂移，也未把 BitPro 未提交工作区作为来源。
- 行情模块完成当前 BitPro 610 行 `Market.tsx` 原样导入；原 A 股 Market Terminal 机械迁入独立 `AshareMarketWorkspace` 并保持默认导出，继续使用股票/ETF/指数、PostgreSQL 日线、CNY、100股、盘口空态、自选和证据 API。BitPro OKX 页面仅作为 named reference，不执行。
- 行情 `tsc`、零警告 lint 和 Mock E2E 通过；搜索贵州茅台、K线和盘口空态合同保持不变。
- BitPro 201 行 FactorLab 原文件已逐字保存为 `_quarantine/BitProFactorLab.tsx.disabled`。它依赖 BitPro 独有的 ML task/trial/provider 与 SQLite 控制面，当前不能直接注册；默认 A 股因子页继续使用 PostgreSQL 目录、指标成熟、运行、相关性、快照和值浏览合同，不用空 API 伪装 ML 功能。
- 因子 `tsc`、零警告 lint 和 Mock E2E 通过；pending Rank IC 仍保持 null 并显示原因，页面加载 mutation 0。
- BitPro 对应盯盘源码 `WatchMarket.tsx`（765 行）与 `LiveAccountSummaryPanels` 已原样导入但未注册；默认 `/watch` 保持当前 A 股五工作区，只读 Paper 信号/订单/成交/规则/告警。TypeScript 与安全审计通过，活动 live 路由仍为 0。
- BitPro 当前 `App.tsx`、`MainLayout.tsx` 与 `index.css` 已逐字保存为 `_quarantine/BitPro*.disabled` 基线；活动 App/MainLayout 保留 A 股 13 个 Owner 路由和 Paper-only 安全差异。BitPro 的 livePulse、progressShimmer、rowFadeIn 与 reduced-motion 动效已原样补入活动 `index.css`。
