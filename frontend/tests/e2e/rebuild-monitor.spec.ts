import { expect, test } from '@playwright/test'

test('monitor separates lifecycle from health evidence', async ({ page }) => {
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ auth_enabled: false, authenticated: true, role: 'admin', permissions: ['admin'] }) }))
  await page.route('**/api/monitor/summary*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ overall_status: 'warning', services: [{ service_code: 'paper_runtime', status: 'warning', freshness: 'stale', observed_at: '2026-08-20T00:00:00Z' }], data: { dataset: { status: 'sealed' }, market: null }, strategy_health: [{ id: 'paper-1', name: 'A股模拟', lifecycle_status: 'running', health_state: 'stale', heartbeat_age_seconds: 90000 }], active_alerts: [], notifications: [{ status: 'delivered', count: 3 }], source_label: 'PostgreSQL runtime and health evidence', source_updated_at: '2026-08-20T00:00:00Z' }) }))
  await page.goto('/monitor')
  await expect(page.getByRole('heading', { name: '监控' })).toBeVisible()
  const row = page.locator('[data-paper-instance-id="paper-1"]')
  await expect(row).toContainText('running')
  await expect(row).toContainText('stale')
  await expect(page.getByText('生命周期与健康分离')).toBeVisible()
  await expect(page.getByText(/USDT|交易所连接|真实账户/)).toHaveCount(0)
})
