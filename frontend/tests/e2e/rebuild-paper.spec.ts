import { expect, test } from '@playwright/test'


test('paper dashboard renders existing instances without reset', async ({ page }) => {
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ auth_enabled: false, authenticated: true, role: 'admin', permissions: ['admin'] }) }))
  const items = Array.from({ length: 15 }, (_, index) => ({ id: `paper-${index + 1}`, name: `A股模拟 ${index + 1}`, lifecycle_status: index === 14 ? 'stopped' : 'running', health_state: 'healthy', initial_cash: '1000000', equity: '1100000', total_pnl: '100000', return_rate: '0.1', trade_count: 3, position_count: 2, heartbeat_at: '2026-08-21T12:00:00Z' }))
  await page.route('**/api/paper/instances?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items, total: 15, scope: 'audit' }) }))
  await page.route('**/api/backtest/runs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))
  const detail = { id: 'paper-1', name: 'A股模拟 1', status: 'running', view: items[0], positions: [{ id: 1, symbol: '600519.SH', quantity: 100, available_quantity: 100, avg_cost: 1200, market_value: 127296, updated_at: '2026-08-21T12:00:00Z' }], trades: [], events: [{ id: 1, message: '周期完成', event_type: 'cycle', occurred_at: '2026-08-21T12:00:00Z' }], risk_events: [], alerts: [], cycles: [{ id: 1, trade_date: '2026-08-21', status: 'success', cycle_key: 'paper-cycle' }], equity_snapshots: [{ equity: 1000000 }, { equity: 1100000 }], strategy_version_id: 'strategy-1', dataset_snapshot_id: 1, universe_snapshot_id: 1, factor_snapshot_id: 1, pool_snapshot_id: 1, research_protocol_id: 'protocol-1', qualifying_backtest_run_id: 'run-1', runtime_version: 'paper-runtime' }
  await page.route('**/api/paper/instances/paper-1', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) }))
  await page.route('**/api/paper/instances/paper-1/pause', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...detail, status: 'paused', view: { ...items[0], lifecycle_status: 'paused' } }) }))

  await page.goto('/paper')
  await expect(page.getByTestId('paper-instance-card')).toHaveCount(15)
  await page.getByTestId('paper-instance-card').first().getByRole('button', { name: '详情' }).click()
  for (const title of ['账户曲线', '当前持仓', '成交与事件', '风控状态', '诊断日志']) await expect(page.getByRole('heading', { name: title })).toBeVisible()
  await expect(page.getByText(/USDT|杠杆|强平/)).toHaveCount(0)
  page.once('dialog', (dialog) => dialog.accept())
  const pauseRequest = page.waitForRequest((request) => request.url().endsWith('/api/paper/instances/paper-1/pause') && request.method() === 'POST')
  await page.getByRole('button', { name: '暂停' }).click()
  await pauseRequest
  await expect(page.getByText('已暂停')).toBeVisible()
})
