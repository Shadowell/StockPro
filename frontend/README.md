# StockPro 前端

StockPro 前端是 React + TypeScript + Vite 的本地金融操作台。产品介绍见 [根 README](../README.md)，页面与交互规则见 [产品规格](../docs/spec.md)。

## 前置条件

- Node.js 18+、npm 9+
- 本地后端运行在 `http://127.0.0.1:4445`
- 同级 BitPro 仓库可用，因为 `@bitpro/ui` 通过 `file:../../BitPro/packages/bitpro-ui` 引用

```text
Private/
├── BitPro/
└── StockPro/
```

## 开发

```bash
npm install
npm run dev -- --host 127.0.0.1 --port 4444
```

默认通过 Vite 将 `/api` 代理到 `http://127.0.0.1:4445`。推荐从仓库根目录运行 `./restart.sh`，统一启动前后端。

## 检查

```bash
npm run check
npm run lint
npm run build
npm run test:e2e:mock
npm run test:e2e:real
```

真实后端 E2E 需要 PostgreSQL、FastAPI 和 Vite 均已启动，且测试数据库状态符合用例要求。

## 页面

```text
/            首页
/market      行情
/pools       股票池
/factors     因子
/strategy    策略
/backtest    回测
/paper       模拟
/watch       盯盘
/monitor     监控
/review      复盘
/data        数据
/ai-lab      AI 研发
/admin-login 登录
```

旧路由只做兼容跳转。新增功能优先放入对应工作区的二级标签或详情界面，不增加平行的一级菜单。

## UI 约束

- 使用 `@bitpro/ui` 主题令牌和现有共享组件。
- 中文优先，不在主阅读层展示 UUID、哈希、数据库主键和 Provider 工程字段。
- 页面保持紧凑的操作台密度，不使用营销 Hero、巨大留白、渐变装饰和整行按钮式二级导航。
- 所有数据面板覆盖加载、空、过期、错误、部分缺失和权限不足。
- 涨跌颜色通过全局设置读取，零值和缺失值保持中性。
- 不复制 BitPro 业务页面代码。

## 环境变量

参考 `frontend/.env.example`：

```bash
VITE_API_URL=/api
VITE_DEV_API_PROXY_TARGET=http://127.0.0.1:4445
VITE_DEV_SERVER_PORT=4444
```

不要把后端密钥、Provider Token 或管理员密码放进 `VITE_*` 变量；这些变量会进入浏览器构建。
