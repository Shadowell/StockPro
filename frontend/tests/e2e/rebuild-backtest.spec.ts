import { expect, test } from '@playwright/test'


test('backtest console keeps BitPro workflow and A-share evidence', async ({ page }) => {
  let eagerEvidenceRequests = 0
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ auth_enabled: false, authenticated: true, role: 'admin', permissions: ['admin'] }) }))
  await page.route('**/api/strategies*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ id: 'sv-1', legacy_strategy_id: 1, name: 'A股动量', description: 'T+1 多股动量', status: 'stopped', script_content: '', config: { timeframe: '1d', asset_class: 'stock' }, symbols: ['600000.SH'], created_at: '2026-08-25T00:00:00Z', updated_at: '2026-08-25T00:00:00Z' }] }) }))
  await page.route('**/api/backtest/runs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ id: 'run-1', name: '动量回测', status: 'success', run_mode: 'full', strategy_name: 'A股动量', strategy_version: 1, start_date: '2025-01-01', end_date: '2026-01-01', initial_cash: '1000000', promotion_status: 'not_eligible', metrics: { strategy_return: 0.12, sharpe: 1.1, maximum_drawdown: 0.08 } }] }) }))
  await page.route('**/api/backtest/runs/run-1', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'run-1', name: '动量回测', status: 'success', run_mode: 'full', strategy_version_id: 'sv-1', strategy_name: 'A股动量', start_date: '2025-01-01', end_date: '2026-01-01', initial_cash: '1000000', metrics: { strategy_return: 0.12, sharpe: 1.1, maximum_drawdown: 0.08 } }) }))
  await page.route('**/api/backtest/runs/run-1/**', (route) => { eagerEvidenceRequests += 1; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }) })
  await page.route('**/api/backtest/jobs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))
  await page.route('**/api/backtest/configuration', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ strategy_versions: [{ id: 'sv-1', name: 'A股动量', version: 1 }], dataset_snapshots: [{ id: 10, name: '日线封存', status: 'sealed' }], universe_snapshots: [{ id: 8, name: 'A股Universe', status: 'sealed' }], factor_snapshots: [], pool_snapshots: [{ id: 5, name: '质量池', status: 'sealed' }], cost_models: [{ id: 'cost-1', name: 'A股标准成本' }], protocols: [{ id: 'protocol-1', name: '完整研究协议' }] }) }))
  await page.route('**/api/market/instruments/000300.SH/daily*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], adjustment: 'unadjusted', source_label: 'fixture', data_status: 'empty' }) }))

  await page.goto('/backtest')
  await expect(page.getByRole('heading', { name: '回测', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '创建批量回测实例' })).toBeVisible()
  await expect(page.getByRole('searchbox', { name: '搜索回测实例' })).toBeVisible()
  await expect(page.getByTestId('backtest-history-table')).toBeVisible()
  await page.getByTestId('backtest-history-table').getByRole('button', { name: '打开详情' }).first().click()
  await expect(page.getByRole('heading', { name: 'A股动量' })).toBeVisible()
  expect(eagerEvidenceRequests).toBe(0)
  await page.getByRole('button', { name: '返回' }).click()
  await page.getByRole('button', { name: '创建回测实例' }).click()
  for (const step of ['选择策略', '配置参数', '确认运行']) await expect(page.getByText(step, { exact: true }).first()).toBeVisible()
  await expect(page.getByText('T+1', { exact: true })).toBeVisible()
  await expect(page.getByText('100股', { exact: true })).toBeVisible()
})
