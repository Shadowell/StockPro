import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('review reads A-share evidence without page-load assembly',async({page})=>{await installFinalFixtures(page);const writes:string[]=[];page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method()))writes.push(r.url())});await page.goto('/review');await expect(page.getByRole('heading',{name:'复盘中心'})).toBeVisible();await expect(page.getByText(/USDT|OKX|资金费率/)).toHaveCount(0);expect(writes).toEqual([])})

test('review excludes insufficient samples from quality ranking across windows', async ({ page }) => {
  await installFinalFixtures(page)
  await page.route('**/api/v2/review/summary*', (route) => {
    const window = new URL(route.request().url()).searchParams.get('window') || '24h'
    const gates = window === '30d' ? [20, 20, 10, 27.5] : window === '7d' ? [5, 5, 3, 35] : [2, 2, 1, 50]
    const row = {
      strategy_id: 0, name: '单日最小链路', group_key: 'ashare:stock:1d', score: null,
      return_pct: null, max_drawdown_pct: null, win_rate: null, profit_factor: null,
      trade_count: 1, closed_trade_count: 0, order_count: 0, sample_count: 1,
      coverage_start: '2026-08-26', coverage_end: '2026-08-26',
      sample_health_status: 'insufficient_sample', sample_health_pct: gates[3], missing_ratio_pct: 75,
      health_components: {}, diagnostics: ['trading_days', 'equity_points', 'closed_trades'],
      tags: ['A股', '1D', '样本不足'], verdict: '样本不足/不可判定',
    }
    const data = {
      overview: {
        review_window: window, bucket: '1h', strategy_count: 1, sample_strategy_count: 0,
        insufficient_strategy_count: 1, overall_return_pct: null, median_return_pct: null,
        max_drawdown_pct: null, observe_count: 0, review_count: 0, sample_health_pct: gates[3],
        sample_health_status: 'insufficient_sample',
        health_denominator: { min_trading_days: gates[0], min_equity_points: gates[1], min_closed_trades: gates[2], component_count: 4 },
        coverage_start: '2026-08-26', coverage_end: '2026-08-26', equity_sample_count: 1,
        closed_trade_count: 0, fill_count: 1,
      },
      groups: [{ group_key: 'ashare:stock:1d', asset_class: 'stock', timeframe: '1d', strategy_type: 'mixed', capital_version: 'CNY', strategy_count: 1, sample_strategy_count: 0, return_pct: null, max_drawdown_pct: null, win_rate: null, profit_factor: null, trade_count: 1, closed_trade_count: 0, score: null, verdict: '样本不足/不可判定', strategies: [row] }],
      leaderboard: { observe: [], review: [], insufficient: [row] }, heatmap: [],
      tags: [{ label: '样本不足', count: 1 }],
      diagnostics: ['闭合交易为 0，胜率、盈亏比和策略评分不可判定', '小时权益桶为 0：当前只有日线证据'],
      next_actions: [`补齐至少 ${gates[0]} 个交易日和 ${gates[1]} 个权益点`],
    }
    return route.fulfill({ json: { success: true, data } })
  })
  await page.goto('/review')
  await expect(page.getByText('样本不足/不可判定', { exact: true }).last()).toBeVisible()
  await expect(page.getByText('1 策略 · 0 可判定', { exact: true })).toBeVisible()
  await expect(page.getByText(/覆盖 2026-08-26 至 2026-08-26/)).toBeVisible()
  await expect(page.getByText(/闭合交易为 0/)).toBeVisible()
  await expect(page.getByText('50 分', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '7D' }).click()
  await expect(page.getByText(/每策略门槛：日 ≥ 5/)).toBeVisible()
  await page.getByRole('button', { name: '30D' }).click()
  await expect(page.getByText(/每策略门槛：日 ≥ 20/)).toBeVisible()
})
