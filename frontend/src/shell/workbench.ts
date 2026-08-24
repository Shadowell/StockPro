export type WorkspaceGroup = 'overview' | 'research' | 'mainline' | 'operations' | 'capability'

export type NavRole = 'admin' | 'guest'

export type ProductWorkspace = {
  path: string
  label: string
  group: WorkspaceGroup
  allowedRoles: NavRole[]
}

export const PRODUCT_WORKSPACES: ProductWorkspace[] = [
  { path: '/', label: '首页', group: 'overview', allowedRoles: ['admin', 'guest'] },
  { path: '/market', label: '行情', group: 'research', allowedRoles: ['admin', 'guest'] },
  { path: '/pools', label: '股票池', group: 'research', allowedRoles: ['admin', 'guest'] },
  { path: '/factors', label: '因子', group: 'research', allowedRoles: ['admin', 'guest'] },
  { path: '/strategy', label: '策略', group: 'mainline', allowedRoles: ['admin', 'guest'] },
  { path: '/backtest', label: '回测', group: 'mainline', allowedRoles: ['admin', 'guest'] },
  { path: '/paper', label: '模拟', group: 'mainline', allowedRoles: ['admin', 'guest'] },
  { path: '/watch', label: '盯盘', group: 'operations', allowedRoles: ['admin', 'guest'] },
  { path: '/signals', label: '信号', group: 'operations', allowedRoles: ['admin', 'guest'] },
  { path: '/monitor', label: '监控', group: 'operations', allowedRoles: ['admin', 'guest'] },
  { path: '/review', label: '复盘', group: 'operations', allowedRoles: ['admin', 'guest'] },
  { path: '/data', label: '数据', group: 'capability', allowedRoles: ['admin', 'guest'] },
  { path: '/ai-lab', label: 'AI研发', group: 'capability', allowedRoles: ['admin', 'guest'] },
]

export type HiddenWorkspaceKind = 'unavailable' | 'reserved'

export type HiddenWorkspace = {
  path: string
  title: string
  description: string
  ownerRoute: string
  kind: HiddenWorkspaceKind
  redirect: boolean
}

const HIDDEN_WORKSPACES: HiddenWorkspace[] = [
  {
    path: '/futures',
    title: '期货',
    description: '期货领域已预留，但在独立合同完成前不进入产品导航或工作台。',
    ownerRoute: '/',
    kind: 'reserved',
    redirect: true,
  },
  {
    path: '/live-real',
    title: '数字资产实盘',
    description: 'OKX / 合约实盘不属于 StockPro。当前 sprint 不开放真实交易，也不会注册下单路由。',
    ownerRoute: '/paper',
    kind: 'unavailable',
    redirect: false,
  },
  {
    path: '/live',
    title: '实盘工作台',
    description: '当前 sprint 不开放真实交易。A股执行只走模拟盘现金账本，不把实盘深链展示为可用工作台。',
    ownerRoute: '/paper',
    kind: 'unavailable',
    redirect: false,
  },
  {
    path: '/arbitrage',
    title: '套利中心',
    description: '跨所套利与资金费率扫描属于 BitPro 数字资产能力，不在 A股 Paper MVP 中。',
    ownerRoute: '/',
    kind: 'unavailable',
    redirect: false,
  },
  {
    path: '/onchain',
    title: '链上研究',
    description: '链上研究继续属于 BitPro，不进入 StockPro 产品路由。',
    ownerRoute: '/',
    kind: 'unavailable',
    redirect: false,
  },
  {
    path: '/arc',
    title: 'ARC Console',
    description: 'ARC 自主研究不属于 StockPro 产品能力。',
    ownerRoute: '/ai-lab',
    kind: 'unavailable',
    redirect: false,
  },
  {
    path: '/trading',
    title: '币圈交易页',
    description: '旧 OKX 现货/合约交易页已下线。A股只保留模拟盘现金账本。',
    ownerRoute: '/paper',
    kind: 'unavailable',
    redirect: false,
  },
]

const normalizePath = (pathname: string) => {
  if (!pathname) return '/'
  if (pathname.length > 1 && pathname.endsWith('/')) return pathname.slice(0, -1)
  return pathname
}

export function resolveHiddenWorkspace(pathname: string): HiddenWorkspace | null {
  const path = normalizePath(pathname)
  return HIDDEN_WORKSPACES.find((item) => path === item.path || path.startsWith(`${item.path}/`)) || null
}

export function isProductWorkspace(pathname: string): boolean {
  const path = normalizePath(pathname)
  return PRODUCT_WORKSPACES.some((item) => item.path === path)
}
