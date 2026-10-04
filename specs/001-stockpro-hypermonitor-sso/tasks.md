# 任务：StockPro 统一登录

## Phase 1: Setup

- [x] T001 在隔离 worktree 接入 .specify/ 与项目 constitution，核验无模板冲突。
- [x] T002 检查 rebuild/tests/test_direct_auth.py 无服务基线与现有登录调用链。

## Phase 2: US1 中央会话

- [x] T003 [US1] 在 rebuild/tests/test_hypermonitor_sso.py 写 Cookie、中央响应与两个 /me 别名的失败回归。
- [x] T004 [US1] 实现 backend/app/domain/auth/sso.py 固定 HTTPS 校验及共用身份解析器，接入中间件与 /me。

## Phase 3: US2 权限兼容

- [x] T005 [US2] 在 rebuild/tests/test_hypermonitor_sso.py 验证本地/访客/MCP 优先、伪造头、跨站写与失败关闭。
- [x] T006 [US2] 在 backend/app/core/auth_middleware.py 保持原授权分支并为 SSO 增加 Origin 限制。

## Phase 4: US3 登录与退出

- [x] T007 [US3] 在 rebuild/tests/test_hypermonitor_sso.py 验证退出清 Cookie 及来源限制。
- [x] T008 [US3] 修改 frontend/src/pages/Login.tsx 与 backend/app/api/v2/endpoints/auth.py 完成统一入口及退出。

## Phase 5: Verification

- [x] T009 更新 AGENTS.md 的 Spec Kit 入口、docs/spec.md、docs/contracts/active.md 与 docs/progress.md 长期合同。
- [x] T010 运行无服务认证回归、前端类型/构建/定向 lint、敏感内容与 git diff 检查。
- [x] T011 对照 specs/001-stockpro-hypermonitor-sso/ 收敛审查，并创建限定文件 Git commit 供任务分支审查；只允许推送任务分支，不合并或部署。

依赖：T001→T002→T003→T004→T005→T006；T007→T008；最后 T009→T010→T011。
测试先于对应实现。原认证回归、类型检查与文档审查可独立运行。
上线 E2E 为发布条件，本轮生产禁令下不执行，也不标记为已验证。
