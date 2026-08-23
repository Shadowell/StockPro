import { expect, test } from '@playwright/test'


test('signal center audits and watch observes without order actions', async ({ page }) => {
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ auth_enabled: false, authenticated: true, role: 'admin', permissions: ['admin'] }) }))
  const signal = { id: 'signal-1', paper_instance_id: 'paper-1', strategy_version_id: 'strategy-1', symbol: 'SZ_000001', signal_type: 'buy', status: 'new', signal_time: '2026-08-21T10:00:00Z', evidence: { score: 0.8 } }
  const alert = { id: 'alert-1', paper_instance_id: 'paper-1', severity: 'warning', category: 'signal', title: '策略信号', message: '信号已生成', source_object_type: 'strategy_signal', source_object_id: 'signal-1', triggered_at: '2026-08-21T10:00:00Z', status: 'active' }
  await page.route('**/api/signals?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [signal], total: 1, scope: 'audit' }) }))
  await page.route('**/api/watch/alerts*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [alert], total: 1 }) }))
  await page.route('**/api/watch/context?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ scope: 'audit', data_status: 'fresh', source_label: 'PostgreSQL Paper audit evidence', source_updated_at: '2026-08-21T10:00:00Z', instances: [{ id: 'paper-1' }], signals: [signal], orders: [{ id: 'order-1', paper_instance_id: 'paper-1', symbol: 'SZ_000001', status: 'filled' }], trades: [{ id: 'trade-1', paper_instance_id: 'paper-1', symbol: 'SZ_000001', side: 'buy' }], positions: [], risk_events: [], runtime_events: [], alerts: [alert], pool_moves: [], coverage: {}, symbol_names: { SZ_000001: '平安银行' } }) }))
  await page.route('**/api/watch/rules?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ id: 'rule-1', name: '价格异动', rule_type: 'price', rule_version: 1, severity: 'warning', enabled: true, config: {} }], total: 1, scope: 'audit' }) }))

  await page.goto('/signals')
  await expect(page.getByRole('heading', { name: '信号中心' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '投递记录' })).toBeVisible()
  await expect(page.getByTestId('signal-row')).toHaveAttribute('data-paper-instance-id', 'paper-1')

  await page.goto('/watch')
  for (const tab of ['策略信号', '订单与成交', '图表联动', '规则', '告警']) await expect(page.getByRole('tab', { name: tab })).toBeVisible()
  await expect(page.getByRole('button', { name: /下单|买入|卖出/ })).toHaveCount(0)
})
