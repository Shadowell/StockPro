import { expect, test } from '@playwright/test'


test('factor lab keeps pending metrics null and does not overclaim validation', async ({ page }) => {
  let mutationCount = 0
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ auth_enabled: false, authenticated: true, role: 'admin', permissions: ['admin'] }) }))
  await page.route('**/api/factors', (route) => { if (route.request().method() !== 'GET') mutationCount += 1; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ id: 1, factor_code: 'momentum_20d', factor_name: '20日动量', category: 'momentum', research_status: 'exploratory', validation_status: 'valid', version_no: 1, active_version_id: 11, last_trade_date: '2026-08-21', coverage: 0.96, rank_ic: null }] }) }) })
  await page.route('**/api/factors/momentum_20d/metrics', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ factor: { factor_code: 'momentum_20d', factor_name: '20日动量' }, items: [{ metric_code: 'coverage', metric_value: 0.96, pending_reason: null }, { metric_code: 'rank_ic', metric_value: null, pending_reason: '等待未来收益成熟' }] }) }))
  await page.route('**/api/factor-runs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))
  await page.route('**/api/factor-correlations*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))
  await page.route('**/api/factor-snapshots*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))

  await page.goto('/factors')

  await expect(page.getByRole('heading', { name: '因子库' })).toBeVisible()
  await expect(page.getByText('20日动量', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: '指标诊断' })).toBeVisible()
  await expect(page.getByText('等待未来收益成熟')).toBeVisible()
  await expect(page.getByText('已验证', { exact: true })).toHaveCount(0)
  expect(mutationCount).toBe(0)
})
