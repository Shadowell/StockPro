import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('backtest console keeps BitPro workflow and sealed A-share controls', async ({ page }) => { await installFinalFixtures(page); await page.goto('/backtest'); await expect(page.getByRole('heading',{name:'回测',exact:true})).toBeVisible(); await expect(page.getByRole('button',{name:'创建回测实例'})).toBeDisabled(); await expect(page.getByRole('button',{name:'创建批量回测实例'})).toBeDisabled(); await expect(page.getByText(/USDT|OKX|永续|杠杆/)).toHaveCount(0) })

test('single-day backtest separates fills, closed trades, and orders', async ({ page }) => {
  await installFinalFixtures(page)
  const summary = {
    id: 2118348412, strategy_id: 0, strategy_name: '单日最小链路', status: 'completed',
    timeframe: '1d', start_date: '2026-08-26', end_date: '2026-08-26',
    initial_capital: 1000000, final_capital: 999970.2379, total_return: null,
    max_drawdown: null, sharpe_ratio: null, win_rate: null, total_fees: 29.7621,
    total_trades: 1, fill_count: 1, closed_trade_count: 0, order_count: 0,
    sample_days: 1, metric_status: 'insufficient_sample',
    metric_unavailable_reason: '回测仅覆盖 1 个自然日，无法形成收益、风险或基准判决',
    data_quality_status: 'insufficient_sample', data_quality_message: '回测仅覆盖 1 个自然日',
    created_at: '2026-08-27T10:29:29+08:00',
  }
  await page.route('**/api/v2/backtest/results*', (route) => route.fulfill({ json: { success: true, data: [summary] } }))
  await page.route('**/api/v2/backtest/result/2118348412', (route) => route.fulfill({ json: { success: true, data: {
    ...summary,
    trades: [{ symbol: '920000.BJ', timestamp: 1787702400000, side: 'buy', price: 13.59, quantity: 7300, amount: 99207, fee: 29.7621, pnl: 0, reason: 'sample' }],
    equity_curve: [{ timestamp: 1787702400000, equity: 999970.2379 }],
  } } }))
  await page.goto('/backtest')
  await page.getByText('单日最小链路', { exact: true }).first().click()
  await expect(page.getByText('研究指标样本不足', { exact: true })).toBeVisible()
  await expect(page.locator('[data-metric-label="成交数"]')).toContainText('1 笔')
  await expect(page.locator('[data-metric-label="闭合交易"]')).toContainText('0 笔')
  await expect(page.locator('[data-metric-label="委托数"]')).toContainText('0 笔')
  await expect(page.getByText('920000.BJ', { exact: true }).last()).toBeVisible()
  await expect(page.getByText('¥999970.24', { exact: true })).toBeVisible()
  await expect(page.getByText('收益为正', { exact: true })).toHaveCount(0)
})
