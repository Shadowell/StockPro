import { Link } from 'react-router-dom'
import { WorkspaceStatePanel } from '../../shell/WorkspaceState'

export type WorkspaceState = {
  title: string
  description: string
  ownerRoute: string
  status: 'adapting' | 'unavailable' | 'reserved'
}

const STATUS_COPY = {
  adapting: {
    kind: 'stale' as const,
    badge: 'A股适配未完成',
    detail: '正在接入 A股 PostgreSQL 数据。当前页面不发起业务请求，不展示 mock 行情，也不会启动 Provider、策略或 Paper recovery。',
  },
  unavailable: {
    kind: 'unavailable' as const,
    badge: '不在 A股 Paper MVP',
    detail: '该深链已被明确标记为不可用，而不是静默当成实盘或数字资产工作台。请回到对应 Owner 页面继续研究或模拟。',
  },
  reserved: {
    kind: 'unavailable' as const,
    badge: '领域预留',
    detail: '该领域已预留接口，但在独立合同完成前不注册产品路由，也不出现在侧栏。',
  },
}

export default function UnavailableWorkspace({ state }: { state: WorkspaceState }) {
  const copy = STATUS_COPY[state.status]

  return (
    <div data-testid="unavailable-workspace">
      <WorkspaceStatePanel
        kind={copy.kind}
        title={state.title}
        description={state.description}
        detail={`${copy.badge}。Owner 页面 ${state.ownerRoute}。${copy.detail}`}
        actions={
          <Link
            to={state.ownerRoute}
            className="inline-flex h-8 items-center rounded-md border border-[var(--bp-border)] px-3 text-[11px] text-[var(--bp-text)] hover:border-[var(--bp-accent)]"
          >
            返回 {state.ownerRoute === '/paper' ? '模拟盘现金账本' : 'Owner 页面'}
          </Link>
        }
      />
    </div>
  )
}
