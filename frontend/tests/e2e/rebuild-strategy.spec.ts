import { expect, test } from '@playwright/test'


const strategy = {
  id: 'strategy-version-1', name: 'A股多股动量模板', version: 1, status: 'draft', validation_status: 'valid',
  description: '多股组合、100股一手、T+1、只做多。', content_hash: 'content-hash', script_content: 'def initialize(context):\n    pass\n\ndef handle_data(context, data):\n    pass',
  parameter_schema: { lookback: { type: 'integer', default: 20 } }, data_dependencies: ['daily_bars'],
  dependency_manifest: { pool_snapshot_id: 5, factor_snapshot_id: 3 }, runtime_limits: { wall_seconds: 3 },
}


test('strategy center keeps BitPro catalogue and A-share lineage', async ({ page }) => {
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ auth_enabled: false, authenticated: true, role: 'admin', permissions: ['admin'] }) }))
  await page.route('**/api/strategies', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [strategy] }) }))
  await page.route('**/api/strategies/strategy-version-1', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(strategy) }))

  await page.goto('/strategy')
  await expect(page.getByRole('heading', { name: '策略中心' })).toBeVisible()
  await expect(page.getByLabel('搜索策略')).toBeVisible()
  await page.getByTestId('strategy-card').first().getByRole('button', { name: '详情' }).click()
  await expect(page.getByRole('heading', { name: '封存输入', exact: true })).toBeVisible()
  await expect(page.getByText('100股', { exact: true })).toBeVisible()
  await expect(page.getByText('T+1', { exact: true })).toBeVisible()
  await expect(page.getByText(/合约|永续|USDT/)).toHaveCount(0)
})
