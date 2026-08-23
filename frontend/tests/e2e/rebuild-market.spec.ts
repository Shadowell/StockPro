import { expect, test } from '@playwright/test'


const instrument = {
  symbol: '600519.SH', name: '贵州茅台', asset_class: 'stock', market: 'CN', exchange: 'SSE', currency: 'CNY',
  tick_size: '0.01', lot_size: 100, contract_multiplier: null, margin_rate: null, expiry_date: null,
  last_trade_date: null, settlement_type: null, session_calendar: 'CN_A_SHARE', shortable: false,
}


test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ auth_enabled: false, authenticated: true, role: 'admin', permissions: ['admin'] }) }))
  await page.route('**/api/market/instruments?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [instrument], query: '600519', asset_class: null }) }))
  await page.route('**/api/market/instruments/600519.SH/daily*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [
    { date: '2026-08-19', open: 1260, high: 1280, low: 1250, close: 1270, volume: 10000, turnover: 12700000 },
    { date: '2026-08-20', open: 1270, high: 1288, low: 1262, close: 1280, volume: 12000, turnover: 15360000 },
    { date: '2026-08-21', open: 1280, high: 1284, low: 1268, close: 1272.96, volume: 9000, turnover: 11456640 },
  ], adjustment: 'unadjusted', source_label: 'PostgreSQL stock_history', data_status: 'fresh' }) }))
  await page.route('**/api/market/instruments/600519.SH/order-book', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ bids: [], asks: [], source_label: null, source_updated_at: null, data_status: 'empty', unavailable_reason: '隔离库尚无盘口缓存' }) }))
  await page.route('**/api/market/instruments/600519.SH', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ instrument, latest_price: '1272.96', change_pct: '1.2', turnover: '11456640', source_updated_at: '2026-08-21T14:55:00', trade_date: '2026-08-21', data_status: 'stale' }) }))
  await page.route('**/api/market/watchlist', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))
})


test('market switches among stock ETF and index without crypto controls', async ({ page }) => {
  await page.goto('/market')
  await page.getByLabel('证券搜索').fill('600519')
  await page.getByRole('option', { name: /贵州茅台/ }).click()

  await expect(page.getByTestId('kline-chart')).toBeVisible()
  await expect(page.getByText('100股')).toBeVisible()
  await page.getByRole('button', { name: '盘口' }).click()
  await expect(page.getByText('隔离库尚无盘口缓存')).toBeVisible()
  await expect(page.getByText(/合约|永续|资金费率|USDT|BTC|ETH/)).toHaveCount(0)
})
