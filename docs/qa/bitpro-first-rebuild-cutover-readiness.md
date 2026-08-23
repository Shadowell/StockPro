# BitPro-first StockPro A股重建：生产切换验收报告

日期：2026-08-23
状态：**Deployed and verified**

## 结论

StockPro 已完成 BitPro-first A股重建、PR 合并、GitHub Actions 部署和生产验收。机器审计的
BASE/API/DB/PAPER/SAFE/UI/ASHARE/FUTURE/DEPLOY 九项必需能力全部 passed。生产只执行
additive migration，同环境 pre/post 对账无业务记录差异。

## 固定来源与分支

- BitPro 固定来源：`00517963e90f463e608289b0277fe598bd82d9bf`
- StockPro/回滚基线：`99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440`
- 验收分支：`codex/bitpro-a-share-rebase`
- Pre-deploy 代码验收 SHA：`9dad95c77dc2a6e0ffd0b189072e00a60b9212ff`
- 切换就绪提交：`5ed617471d3cdd87f29f35dae66f15e554c1ba41`
- 应用 PR：[#4](https://github.com/Shadowell/StockPro/pull/4)，merge SHA
  `4c7fe5194cae7abf6c07a8be005bbfb573b032d8`
- 部署修复 PR：[#5](https://github.com/Shadowell/StockPro/pull/5)，最终生产 SHA
  `381ec5429114a52af71aae7948834a3f6538f366`
- 从 StockPro 基线起包含 50+ 个可审计提交；核心阶段提交见 `docs/progress.md` 和各 Wave 计划。

## 功能与页面

唯一执行主线为：

```text
策略 → 回测 → 模拟
```

13 个启用路由：首页、行情、股票池、因子、策略、回测、模拟、盯盘、信号、监控、复盘、
数据、AI研发。实盘、期货、链上、套利和 ARC 不注册。公共 API 只使用当前 `/api/*`。

最终截图索引：`docs/screenshots/rebuild/capture-index.json`，覆盖 13 路由 × 1440x900/390x844
共 26 张真实隔离数据截图；无 request interception、DOM 注入、console error 或写请求。

## 验证汇总

- Python：84 passed（含最终部署健康探针合同）。
- Playwright Mock 完整套件：24 passed。
- 真实隔离 route matrix：13 路由 × 2 viewport，无请求拦截，通过。
- TypeScript、ESLint（0 warning/error）、生产构建、bundle budget：通过。
- 生产依赖审计：0 vulnerabilities。
- 安全扫描：私有数字资产执行、SQLite 业务仓库、版本化 API、实盘路由、币圈后台任务均为 0；
  54 个导入遗留文件保持不可达隔离。
- Pre-deploy completion audit：passed；SHA-256
  `0fa69e262712aad0aa3a6a132d2b62085ba9d140409ddf6d58f5e317be5caa88`。
- Post-deploy completion audit：九项全部 passed；SHA-256
  `188d9f9bbfd0e6f855615441f8325a6f41e188cd692b86845364271bff868b1c`。

## 数据库与 Paper 连续性

- 隔离目标：`stockpro_bitpro_rebase_dev`，38 migrations。
- Paper：15 instances / 61 orders / 47 trades / 23 positions / 428 equity samples /
  681 events；逐实例 ID、lineage、首尾权益无差异。
- Local continuity SHA-256：
  `eb6116fba0f791e7ddbbe3f229dbcda7bce8d24b6ae7ec40576bbaec26054292`。
- Instrument 定义：5,550 stock / 0 ETF / 4 index / 0 future。ETF 当前没有权威源记录，未补造；
  future 只有隐藏 Protocol，无数据、页面、API、回测、Paper 或通道。

## 最新恢复与旧应用兼容演练

来源 `stockpro_dev`（2.9GB）使用 custom-format pg_dump 恢复到严格前缀临时库，应用 37→38
additive migrations 后：67 strategy versions、79 backtests、15 Paper、61/47/23/428/681 和
1 daily review 全部一致；临时库与远端 dump 已删除。

- Source manifest SHA-256：`ef9f03a098788a4ff8cceb9d7e2293dd859ceb443211f35e684536b11b38e716`
- Rebuild manifest SHA-256：`4d9672698e8f320fd645a6afa903a4b33dd037195c361f4191fa93465df0025b`
- 固定旧 SHA 创建临时 worktree，PG 强制只读并正常管理员认证后，旧应用进程的 health、
  strategy list、backtest runs 和 Paper instances 均返回 HTTP 200。
- Old app smoke SHA-256：`67131115368d5e3fcb476ce65aef5841adf06bce04fffeebbb708b047c38824c`

## 已知限制与切换记录

1. 当前 DashScope/Qwen 未配置，AI 页面诚实显示 unavailable；配置后仍只生成验证策略和
   quick replay，不自动完整回测或 Paper。
2. 分时、盘口、板块或 Provider 证据在本地无缓存时显示 empty/stale，不合成数据。
3. Watch 冷读在 SSH 环境双请求约 16.6 秒，Signals 约 1.6 秒；已使用 single-flight 和专用
   查询，低于 30 秒客户端上限。
4. 早期诊断暴露的数据库角色已在获批后完成无中断轮换：创建继承旧对象权限的
   `stockpro_rebuild_app`，更新服务器环境，并由 Actions run `32646230741` 重部署当前 main；
   生产活动连接已切换，新旧健康均通过，旧 `stockpro_app` 已设为 `NOLOGIN` 并更换随机密码。
5. PR 创建后的快速审阅发现部署脚本仍探测旧 `/api/health/health`；已改为唯一当前
   `/api/health`，补充部署合同测试，并重新完成 84 Python / 24 Playwright / completion audit。
6. PR #4 的自动部署 run `32647022871` 在服务器同步前失败，原因是 workflow 引用了仓库中
   不存在的 `frontend/scripts/check-local-dependencies.mjs`；生产仍保持旧版本健康。PR #5 删除
   失效 precheck 后，run `32647137727` 成功部署最终 SHA。

## 生产结果

1. Production pre-cutover：37 migrations，业务对象均为 0，部署 SHA 为旧基线
   `99adaaae...`；manifest SHA-256
   `374dafcaaa61bf301b169ac05b372e9408a287ec6f9bc042b0dad810be0d547d`。
2. Production post-cutover：38 migrations，策略/回测/Paper/账本/信号/告警/复盘计数仍为 0，
   对账通过；manifest SHA-256
   `c5f419cd46c2413d9c98f1458c24ba73aa219a16b18e4c1d940aff68a6891b41`。
3. systemd backend、Nginx、内部与公网 `/api/health`、storage health 全部正常，部署 SHA 对齐。
4. 公网首页、行情、策略、回测、模拟、信号、数据、AI研发共 8 路由真实 canary 通过；
   console errors 为 0，单页耗时 1.86–2.58 秒。canary SHA-256
   `11718b497a1319c92381f5a1e1caa3dcd1bfaf4908ec2cd6f7c8be826f52a50a`。
