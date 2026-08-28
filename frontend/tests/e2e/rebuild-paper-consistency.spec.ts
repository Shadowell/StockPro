import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'

const INSTANCE_ID = 1452658566
const ACCOUNT_ID = `paper:${INSTANCE_ID}`
const SYMBOL = '920000.BJ'

async function installPaperConsistencyFixtures(page: Parameters<typeof installFinalFixtures>[0]) {
  await installFinalFixtures(page)
  await page.route('**/api/v2/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const strategy = {
      id: INSTANCE_ID,
      name: '[A股][日线][动量] 最小研究链',
      description: 'A股 Paper',
      status: 'running',
      exchange: 'CN',
      symbols: [SYMBOL],
      total_pnl: -29.7621,
      return_pct: -0.00297621,
      equity: 999970.2379,
      initial_capital: 1000000,
      balance: 900763.2379,
      unrealized_pnl: 0,
      positions: {
        [SYMBOL]: { size: 7300, amount: 7300, entry_price: 13.59, mark_price: 13.59, notional: 99207, unrealized_pnl: 0, mark_price_source: 'paper_position_last_price', mark_price_at: '2026-08-27T14:55:00+08:00', side: 'long' },
      },
      total_trades: 1,
      config: { is_paper_trading: true, asset_class: 'stock', strategy_type: 'momentum', timeframe: '1d', initial_capital: 1000000 },
    }
    const position = { symbol: SYMBOL, name: '安徽凤凰', currency: 'CNY', asset_type: 'stock', side: 'long', amount: 7300, base_amount: 7300, free: 7300, notional: 99207, entry_price: 13.59, mark_price: 13.59, mark_price_source: 'paper_position_last_price', mark_price_at: '2026-08-27T14:55:00+08:00', unrealized_pnl: 0, paper_instance_id: INSTANCE_ID }
    let data: unknown

    if (path === '/api/v2/live/strategies') data = { strategies: [strategy] }
    else if (path === '/api/v2/live/instances') data = { items: [strategy] }
    else if (path === '/api/v2/live/candidates') data = []
    else if (path === '/api/v2/live/dashboard') data = {
      system: { state: 'running', exchange: 'CN', symbol: SYMBOL, symbols: [SYMBOL], timeframe: '1d', strategy: strategy.name, strategy_id: INSTANCE_ID, dry_run: true, mode: 'paper' },
      equity: { initial: 1000000, current: 999970.2379, peak: 1000000, change: -29.7621, change_pct: -0.00297621 },
      performance: { total_pnl: -29.7621, total_pnl_pct: -0.00297621, total_trades: 1, max_drawdown: 0, win_rate: 0, profit_factor: 0, sharpe_ratio: 0 },
      risk: { circuit_breaker: false, current_drawdown: 0, daily_loss: 0 },
      positions: [{ ...position, size: 7300, quantity: 7300 }], account: { total_equity: 999970.2379, cash: 900763.2379, market_value: 99207, unrealized_pnl: 0, position_count: 1 }, recent_events: [], feishu: { enabled: false },
    }
    else if (path === '/api/v2/live/trades') data = [{ id: 'trade-1', trade_id: 'trade-1', order_id: 'order-1', symbol: SYMBOL, side: 'buy', price: 13.59, quantity: 7300, amount: 99207, commission: 29.7621, fee: 29.7621, timestamp: Date.parse('2026-08-27T01:30:00+08:00'), datetime: '2026-08-27T01:30:00+08:00' }]
    else if (path === '/api/v2/live/events') data = { events: [] }
    else if (path === '/api/v2/live/equity_curve') data = [{ timestamp: Date.parse('2026-08-27T15:00:00+08:00'), equity: 999970.2379, drawdown: 0 }]
    else if (path === '/api/v2/live/accounts') data = { accounts: [{ account_id: ACCOUNT_ID, name: strategy.name, exchange: 'CN', exchange_alias: 'A股', is_default: true, configured: true, enabled: true, testnet: true, display_only: true, can_trade: false }] }
    else if (path === `/api/v2/live/accounts/${ACCOUNT_ID}/positions`) data = { account_id: ACCOUNT_ID, exchange: 'CN', positions: [position] }
    else if (path === `/api/v2/live/accounts/${ACCOUNT_ID}/orders/history`) data = { account_id: ACCOUNT_ID, exchange: 'CN', orders: [{ id: 'order-1', symbol: SYMBOL, side: 'buy', type: 'market', price: 13.59, amount: 7300, filled: 7300, remaining: 0, status: 'filled', created_timestamp: Date.parse('2026-08-27T01:30:00+08:00'), created_datetime: '2026-08-27T01:30:00+08:00' }] }
    else if (path === '/api/v2/live/watchlist') data = { account_id: ACCOUNT_ID, exchange: 'CN', items: [{ symbol: SYMBOL, source_strategy_id: INSTANCE_ID, source_strategy_name: strategy.name, last_side: 'buy', last_action: 'buy', last_price: 13.59, last_quantity: 7300, last_notional_usdt: 99207, last_execution_at: '2026-08-27T01:30:00+08:00', order_count: 1 }] }
    else if (path === '/api/v2/live/watchlist/market') data = { account_id: ACCOUNT_ID, exchange: 'CN', symbol: SYMBOL, timeframe: '1d', ticker: { symbol: SYMBOL, last: 13.59, mark_price: 13.59, open: 13.59, high: 13.59, low: 13.59, volume: 0, change_percent: 0, source: 'paper_position_mark', source_updated_at: '2026-08-27T14:55:00+08:00', data_status: 'fallback' }, klines: [], orderbook: { bids: [], asks: [] }, recent_trades: [], positions: [position] }
    else if (path === '/api/v2/live/watchlist/markers') data = { account_id: ACCOUNT_ID, exchange: 'CN', symbol: SYMBOL, markers: [{ id: 1, label: 'B', side: 'buy', action: 'buy', symbol: SYMBOL, price: 13.59, quantity: 7300, timestamp: Date.parse('2026-08-27T01:30:00+08:00'), datetime: '2026-08-27T01:30:00+08:00', source_strategy_id: INSTANCE_ID, source_strategy_name: strategy.name, subscription_id: INSTANCE_ID, live_order_id: 'order-1' }] }
    else if (path === '/api/v2/monitor/active_strategies' || path === '/api/v2/monitor/running-strategies') data = [strategy]
    else return route.fallback()

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
  })
}

test('Paper live watch and monitor reconcile one account snapshot', async ({ page }) => {
  await installPaperConsistencyFixtures(page)
  const failedResponses: string[] = []
  const consoleErrors: string[] = []
  const writes: string[] = []
  page.on('request', (request) => {
    if (!['GET', 'HEAD'].includes(request.method())) writes.push(`${request.method()} ${request.url()}`)
  })
  page.on('response', (response) => {
    if (response.status() >= 400) failedResponses.push(`${response.status()} ${response.url()}`)
  })
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto(`/live?strategyId=${INSTANCE_ID}`)
  await expect(page.getByText('7,300', { exact: true })).toBeVisible()
  await expect(page.getByText(/1 个持仓/)).toHaveCount(2)
  await expect(page.getByText('当前没有 A 股持仓')).toHaveCount(0)
  await expect(page.getByText(/Paper 持仓快照/)).toBeVisible()
  await expect(page.getByText('29.7621', { exact: true })).toBeVisible()
  await expect(page.getByText('成交 trade-1 · 委托 order-1', { exact: true })).toBeVisible()
  await expect(page.getByText('¥900,763.24', { exact: true })).toBeVisible()

  await page.goto('/watch')
  const positionsPanel = page.getByTestId('ashare-positions-panel')
  await expect(positionsPanel.getByText('安徽凤凰', { exact: true })).toBeVisible()
  await expect(positionsPanel.getByText(SYMBOL, { exact: true })).toBeVisible()
  await expect(page.getByText('Paper 持仓最新价回退', { exact: false })).toBeVisible()
  await expect(page.getByText(/13\.59/).first()).toBeVisible()

  await page.goto('/monitor')
  await expect(page.getByText('¥999,970.24', { exact: true })).toBeVisible()
  await expect(page.getByText('¥900,763.24', { exact: true })).toBeVisible()
  await expect(page.getByText('¥99,207', { exact: true })).toHaveCount(2)

  expect(writes).toEqual([])
  expect(failedResponses).toEqual([])
  expect(consoleErrors).toEqual([])
})
