import { expect, test } from '@playwright/test'


const overview = {
  indices: [
    { symbol: '000001.SH', name: '上证指数', value: '3927.18', change_pct: '0.01', source_updated_at: '2026-08-21T14:55:00' },
    { symbol: '399001.SZ', name: '深证成指', value: '14354.31', change_pct: '0.45', source_updated_at: '2026-08-21T14:55:00' },
    { symbol: '399006.SZ', name: '创业板指', value: '3626.3', change_pct: '1.12', source_updated_at: '2026-08-21T14:55:00' },
    { symbol: '000688.SH', name: '科创50', value: '1717.68', change_pct: '-0.01', source_updated_at: '2026-08-21T14:55:00' },
  ],
  breadth: { rise_count: 2505, flat_count: 176, fall_count: 2860 },
  turnover: { amount: '8650000000000', unit: 'CNY' },
  limit_ecology: { limit_up_count: 54, limit_down_count: 13, max_streak: 3, broken_board_rate: '25' },
  sector_flows: [],
  source_label: 'PostgreSQL market cache + sealed evidence',
  source_updated_at: '2026-08-22T21:48:56+08:00',
  trade_date: '2026-08-21',
  data_status: 'partial',
}


test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/me', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ auth_enabled: false, authenticated: true, role: 'admin', permissions: ['admin'] }),
  }))
  await page.route('**/api/market/overview', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(overview),
  }))
})


test('home keeps BitPro density with A-share facts', async ({ page }) => {
  await page.goto('/')

  for (const heading of ['主要指数', '市场宽度', '涨停生态', '板块资金', '主线状态']) {
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
  }
  await expect(page.getByText('2,505')).toBeVisible()
  await expect(page.getByText('54', { exact: true })).toBeVisible()
  await expect(page.getByText(/BTC|ETH|资金费率|永续/)).toHaveCount(0)
})


test('home remains readable on a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '主要指数' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
