import { expect, test } from '@playwright/test'


const strategy = { id: 'strategy-1', legacy_strategy_id: 1, name: 'A股动量', version: 1, validation_status: 'valid', description: '封存股票池动量策略', content_hash: 'hash-1', script_content: 'def initialize(context):\n    pass\n\ndef handle_data(context, data):\n    pass', data_dependencies: ['daily_bars'] }
const paper = { id: 'paper-1', name: 'A股动量模拟', lifecycle_status: 'running', health_state: 'healthy', initial_cash: '1000000', equity: '1100000', total_pnl: '100000', return_rate: '0.1', trade_count: 3, position_count: 1, heartbeat_at: '2026-08-21T12:00:00Z' }


test('strategy backtest paper is the only execution mainline', async ({ page }) => {
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ auth_enabled: false, authenticated: true, role: 'admin', permissions: ['admin'] }) }))
  await page.route('**/api/strategies*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [strategy] }) }))
  await page.route('**/api/backtest/configuration', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ strategy_versions: [strategy], dataset_snapshots: [], universe_snapshots: [], factor_snapshots: [], pool_snapshots: [], cost_models: [], protocols: [] }) }))
  await page.route('**/api/backtest/runs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))
  await page.route('**/api/backtest/jobs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))
  await page.route('**/api/paper/instances?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [paper], total: 1, scope: 'audit' }) }))

  await page.goto('/strategy')
  await page.getByTestId('strategy-card').first().getByRole('button', { name: '回测' }).click()
  await expect(page).toHaveURL(/\/backtest\?strategy_version_id=1/)
  await page.getByRole('button', { name: '创建回测实例' }).click()
  await expect(page.getByText('快速预检不可晋级')).toBeVisible()

  await page.goto('/paper')
  await expect(page.getByText('仅模拟', { exact: true })).toBeVisible()
  await expect(page.getByTestId('paper-instance-card')).toHaveCount(1)
  await expect(page.getByText(/真实下单|实盘账户/)).toHaveCount(0)
})
