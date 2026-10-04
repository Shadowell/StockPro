# 实施方案：StockPro 统一登录

## Technical Context

FastAPI / Python，React / TypeScript，既有 httpx；不新增依赖、数据库表或长期会话。
修改 domain/auth 新增 SSO 校验模块、core/auth_middleware.py、api/v2/endpoints/auth.py 与 Login.tsx。

## Constitution Check

通过：Paper/Live 不变；失败关闭；原角色与机器权限不变；隔离分支、限定提交与分支推送，禁止 main 合并、本地服务与生产操作。

## 接口与设计

固定 GET https://monitor.notenap.com/api/auth/sso/session，仅发送唯一合法的 notenap_session Cookie（URL-safe `[A-Za-z0-9._-]`，1–1024 字符）；
TLS 校验开启，禁重定向、环境代理及 netrc，短超时，无正向缓存。200 只接受字典、authenticated 严格 true、
role 严格 admin、user 非空字符串；401 视为未认证，其他异常或无效响应明确 503。
不接收客户端身份头，不保存中央签名密钥，不签发本站替代长期令牌。

MCP 原分支先执行；本站有效会话优先；缺失或无效时才尝试 SSO。/me 两个别名共用浏览器解析器，
中间件为 /me 预解析有效 MCP 身份以与业务入口一致。现有本地 auth disabled 行为保持不变。
SSO 身份含 authenticated、role、user、auth_method，不改变业务数据与写权限实现。

SSO 的非 GET/HEAD/OPTIONS 请求若带 Origin，必须且只能为 https://stockpro.notenap.com。
请求携带共享 Cookie 的退出同样先检查 Origin，清 host-only 本地 Cookie 与 Domain=.notenap.com 的共享 Cookie；
同时清本站同名共享 Cookie，防止 cookie shadowing。无共享 Cookie 的本地退出保留原行为，不发送共享 Cookie 删除指令。

登录按钮指向 `https://monitor.notenap.com/login?redirect=https%3A%2F%2Fstockpro.notenap.com%2F`，回跳固定本站首页；原登录表单保留。

## 测试与发布

先新增纯 ASGI / httpx MockTransport 拒绝与兼容回归，观察失败后实现；不开 listener，不启动 lifespan。
复用已有 Python venv 与前端 node_modules 做定向认证回归、类型检查、构建、定向 lint 与 diff 检查。
完整 scripts/check.sh 会要求隔离数据库并启动 E2E 服务，本机不运行；相关运行验收交 CI / 解除禁令后的 HTTPS。

只有中央端点已部署、StockPro 生产限制明确解除后，才进行 main 合并与 Actions。此前仅允许任务分支推送供审查。
当前不修改 Nginx、部署工作流或默认认证开关。
