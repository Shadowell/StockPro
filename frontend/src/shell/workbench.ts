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
    title: 'A股模拟执行',
    description: 'BitPro Paper 工作台在 StockPro 中由 A股模拟盘现金账本承接。',
    ownerRoute: '/paper',
    kind: 'reserved',
    redirect: true,
  },
  {
    path: '/arbitrage',
    title: 'A股套利策略',
    description: 'BitPro 套利策略入口由 A股策略中心承接，不保留跨所与资金费率语义。',
    ownerRoute: '/strategy',
    kind: 'reserved',
    redirect: true,
  },
  {
    path: '/onchain',
    title: 'A股资金与基本面研究',
    description: 'BitPro 链上研究入口映射到 A股数据中心的资金流、股东与基本面数据。',
    ownerRoute: '/data',
    kind: 'reserved',
    redirect: true,
  },
  {
    path: '/arc',
    title: 'A股 AI 研发',
    description: 'BitPro 的自主研究入口由 A股 AI 研发工作台承接。',
    ownerRoute: '/ai-lab',
    kind: 'reserved',
    redirect: true,
  },
  {
    path: '/trading',
    title: 'A股模拟交易',
    description: 'BitPro 交易页的安全等价入口为 A股模拟盘现金账本。',
    ownerRoute: '/paper',
    kind: 'reserved',
    redirect: true,
  },
  {
    path: '/orderflow',
    title: 'A股盘口与资金流',
    description: 'BitPro 订单流入口由 A股行情工作台的盘口和成交证据承接。',
    ownerRoute: '/market',
    kind: 'reserved',
    redirect: true,
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
