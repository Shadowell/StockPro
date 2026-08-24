import type { ReactNode } from 'react'
import { BitProTheme, DataPanel, StatusBadge } from '@bitpro/ui'
import { useSettingsStore } from '../stores/useSettingsStore'

export type WorkspaceStateKind = 'loading' | 'empty' | 'error' | 'permission' | 'unavailable' | 'stale'

const KIND_COPY: Record<WorkspaceStateKind, { label: string; tone: 'blue' | 'neutral' | 'red' | 'amber' }> = {
  loading: { label: '加载中', tone: 'blue' },
  empty: { label: '空', tone: 'neutral' },
  error: { label: '错误', tone: 'red' },
  permission: { label: '权限不足', tone: 'amber' },
  unavailable: { label: '不可用', tone: 'amber' },
  stale: { label: '过期', tone: 'amber' },
}

export function WorkspaceStatePanel({
  kind,
  title,
  description,
  detail,
  actions,
}: {
  kind: WorkspaceStateKind
  title: string
  description?: string
  detail?: string
  actions?: ReactNode
}) {
  const colorScheme = useSettingsStore((state) => state.colorScheme)
  const copy = KIND_COPY[kind]

  return (
    <BitProTheme
      className="min-h-[40vh] p-4 sm:p-6"
      colorScheme={colorScheme === 'greenUpRedDown' ? 'green-up-red-down' : 'red-up-green-down'}
    >
      <DataPanel
        title={title}
        subtitle={description}
        actions={<StatusBadge tone={copy.tone}>{copy.label}</StatusBadge>}
      >
        <div className="space-y-3 px-4 py-5 text-xs leading-5 text-[var(--bp-muted)]">
          {detail && <p>{detail}</p>}
          {actions}
        </div>
      </DataPanel>
    </BitProTheme>
  )
}
