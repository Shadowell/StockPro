# BitPro-first StockPro A股重建：生产切换就绪报告

日期：2026-08-23
状态：**Pre-deploy ready，等待最终生产切换确认**

## 结论

StockPro 已在独立分支完成 BitPro-first A股重建。机器审计的 BASE/API/DB/PAPER/SAFE/UI/
ASHARE/FUTURE 八项必需能力均为 passed；`DEPLOY-001` 是唯一
`pending_final_confirmation`。当前没有推送分支、PR、main 合并、生产迁移、服务重启或部署。

## 固定来源与分支

- BitPro 固定来源：`00517963e90f463e608289b0277fe598bd82d9bf`
- StockPro/回滚基线：`99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440`
- 验收分支：`codex/bitpro-a-share-rebase`
- Pre-deploy 代码验收 SHA：`9dad95c77dc2a6e0ffd0b189072e00a60b9212ff`
- 切换就绪提交：`5ed617471d3cdd87f29f35dae66f15e554c1ba41`
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
- Completion audit：passed；SHA-256
  `0fa69e262712aad0aa3a6a132d2b62085ba9d140409ddf6d58f5e317be5caa88`。

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

## 已知限制与切换前动作

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

## 获批后的生产流程

1. 只读 production pre-cutover manifest 已采集；生产当前 37 migrations、业务对象均为 0，
   部署 SHA 为旧基线，不与本地 15 个 Paper 跨环境比较。
2. 推送 `codex/bitpro-a-share-rebase` 并创建 PR。
3. 等待 required checks，通过 PR 合并 `main`。
4. 仅由 GitHub Actions 部署并应用 additive migration；禁止 SSH/rsync 手工修补。
5. 采集同环境 post-cutover manifest，核对服务、部署 SHA、内外健康和真实页面。
6. post-deploy audit 全项通过后关闭合同；失败则回滚应用 release，不回滚/清空数据库。

生产 pre-cutover 采集必须在最终确认后执行，建议命令入口：

```bash
ssh stockpro 'sudo -u postgres psql -d stockpro_prod -c "...只读 manifest 查询..."'
```

该命令需使用与 post-cutover 完全相同的查询集合，产物只写本地忽略目录
`.codex-artifacts/rebuild/production-pre-cutover.json`。

## 最终确认范围

请明确确认是否允许执行以下动作：轮换相关数据库凭据、推送分支、创建 PR、合并 `main`、
由 GitHub Actions 部署并运行生产 additive migrations，以及执行 production pre/post manifest
和真实页面验收。
