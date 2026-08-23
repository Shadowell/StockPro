import { expect, test } from '@playwright/test'


test('stock pool page keeps directory members evidence and sealed snapshots', async ({ page }) => {
  let mutationCount = 0
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ auth_enabled: false, authenticated: true, role: 'admin', permissions: ['admin'] }) }))
  await page.route('**/api/pools', (route) => {
    if (route.request().method() !== 'GET') mutationCount += 1
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ id: 'pool-1', name: '质量股票池', pool_type: 'screener', status: 'active', rule_version: 1, snapshot_count: 1, current_member_count: 2, latest_generation_id: 'gen-1', latest_trade_date: '2026-08-21' }] }) })
  })
  await page.route('**/api/pools/pool-1', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'pool-1', name: '质量股票池', pool_type: 'screener', status: 'active', rule_version: 1, rule_hash: 'rule-hash', config: { logic: 'all', conditions: [] } }) }))
  await page.route('**/api/pools/pool-1/members*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ id: 1, ordinal: 1, symbol: '600519.SH', name: '贵州茅台', score: 0.9, reason: '质量筛选', evidence_hash: 'evidence-hash', valid_from: '2026-08-21' }] }) }))
  await page.route('**/api/pools/pool-1/snapshots', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ id: 5, status: 'sealed', manifest_hash: 'manifest-hash', member_count: 1, trade_date: '2026-08-21' }] }) }))

  await page.goto('/pools')

  await expect(page.getByRole('heading', { name: '股票池' })).toBeVisible()
  await expect(page.getByText('质量股票池', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: '成员与证据' })).toBeVisible()
  await expect(page.getByText('贵州茅台')).toBeVisible()
  await expect(page.getByText('sealed', { exact: true })).toBeVisible()
  expect(mutationCount).toBe(0)
})
