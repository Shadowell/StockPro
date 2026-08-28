import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('strategy center keeps BitPro catalogue and A-share lineage',async({page})=>{await installFinalFixtures(page);await page.goto('/strategy');await expect(page.getByRole('heading',{name:'策略中心'})).toBeVisible();await expect(page.getByLabel('搜索策略')).toBeVisible();for(const label of ['股票','ETF','动量趋势','均值回归','多因子','事件驱动'])await expect(page.getByText(label,{exact:true}).first()).toBeVisible();await expect(page.getByText(/BTC|USDT|OKX|永续/)).toHaveCount(0)})

test('sample strategy detail exposes one-version audit evidence and Paper link', async ({ page }) => {
  await installFinalFixtures(page)
  const strategy = {
    id: 'c10c9805-5b0c-534d-860f-c860f0659eaa', name: '[A股][日线][动量] 最小研究链',
    description: '用于验证 A 股数据、回测、成交与 Paper 关联的最小审计样例，不构成投资建议，也不是正式候选策略。',
    script_content: "def generate_signals(rows):\n    return sorted(rows, key=lambda row: row['daily_return'], reverse=True)\n",
    config: { asset_class: 'stock', timeframe: '1d', version: 1, validation_status: 'valid', symbols: ['920000.BJ', '920001.BJ', '920002.BJ'] },
    status: 'running', exchange: 'CN', symbols: ['920000.BJ', '920001.BJ', '920002.BJ'],
    version_id: 'c10c9805-5b0c-534d-860f-c860f0659eaa', version: 1, content_hash: '57f66708',
    strategy_api_version: 'stockpro.v1', validation_status: 'valid', validated_at: '2026-08-27T10:29:29+08:00',
    is_sample: true, disclaimer: '样例 / 非投资建议',
    audit_summary: {
      selection_logic: '固定使用最新 sealed 回测股票池（3 只），按 daily_return 从高到低排序。',
      entry_logic: '排序结果生成 candidate/buy 记录；最近样例成交为买入 920000.BJ。',
      exit_logic: '未实现。当前策略代码没有卖出、止损或退出信号。',
      rebalance_logic: '日线调用时重排候选；未声明定时调仓。',
      risk_constraints: ['Paper 单标的最大仓位 10%', '平台执行 T+1、100 股整手和交易成本约束'],
      universe_symbols: ['920000.BJ', '920001.BJ', '920002.BJ'],
      latest_execution_reason: '按 stock_history 真实收盘价生成的最小审计样例成交。',
    },
    linked_backtest: { id: 2118348412, uuid: 'bt', status: 'success', start_date: '2026-08-26', end_date: '2026-08-26', fill_count: 1, closed_trade_count: 0, order_count: 0, equity_point_count: 1, metric_status: 'insufficient_sample' },
    linked_paper: { id: 1452658566, uuid: 'paper', status: 'running', runtime_version: 'minimal-research-chain.v1', symbols: ['920000.BJ'], capacity_limits: { max_position_weight: 0.1 }, feed_config: { mode: 'local_snapshot' }, console_path: '/live?mode=paper&instance_id=1452658566' },
    created_at: '2026-08-27T10:29:29+08:00', updated_at: '2026-08-27T10:29:29+08:00',
  }
  await page.route('**/api/v2/strategies*', (route) => route.fulfill({ json: { success: true, data: { items: [strategy], total: 1, page: 1, per_page: 60, pages: 1, status_counts: { all: 1, running: 1 }, asset_counts: { all: 1, stock: 1, etf: 0 }, type_counts: { all: 1, other: 1 }, timeframe_counts: { all: 1, '1d': 1 }, capital_counts: { all: 1, '1000000CNY': 1 } } } }))
  await page.goto('/strategy')
  await expect(page.getByRole('button', { name: '实例控制台' })).toBeEnabled()
  await page.getByRole('button', { name: '详情' }).click()
  for (const text of ['样例 / 非投资建议', '核心标的', '入场逻辑', '退出逻辑', '调仓规则', '风险约束', 'v1', '验证通过', '#2118348412 · success', '#1452658566 · running', '920000.BJ', '版本代码', '版本参数']) {
    await expect(page.getByText(text, { exact: false }).first()).toBeVisible()
  }
  await expect(page.getByText(/尚未补充核心标的说明|尚未补充交易逻辑说明|Minimal audited sample/)).toHaveCount(0)
  await page.getByRole('button', { name: '实例控制台' }).click()
  await expect(page).toHaveURL(/\/live\?mode=paper&instance_id=1452658566/)
})
