import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'

const LIVE_PREFS_KEY = 'bitpro_live_trading_prefs_v2'

test('Paper dashboard renders an honest empty state without reset',async({page})=>{await installFinalFixtures(page);await page.goto('/live');await expect(page.getByText('策略实例控制台')).toBeVisible();await expect(page.getByText('模拟：只做 PaperBroker / 模拟成交，不触碰真实资金。')).toBeVisible();await expect(page.getByRole('button',{name:/清空|重置/})).toHaveCount(0);await expect(page.getByText(/USDT|杠杆|强平|OKX/)).toHaveCount(0)})

test('stale persisted instance leaves the loading spinner and shows the empty console', async ({ page }) => {
  await page.addInitScript((key) => {
    localStorage.setItem(
      key,
      JSON.stringify({
        v: 2,
        tradeMode: 'paper',
        view: 'detail',
        activeInstanceId: 'live:strategy:1249282388',
      }),
    )
  }, LIVE_PREFS_KEY)
  await installFinalFixtures(page)
  await page.goto('/live')
  await expect(page.getByText('策略实例控制台')).toBeVisible()
  await expect(page.getByText('正在加载实例控制台')).toHaveCount(0)
  await expect(page.getByText('暂无运行中实例。点击「创建新策略实例」启动策略。')).toBeVisible()
})

test('missing strategyId query returns to the empty console instead of spinning', async ({ page }) => {
  await installFinalFixtures(page)
  await page.goto('/live?mode=paper&strategyId=1249282388')
  await expect(page.getByText('策略实例控制台')).toBeVisible()
  await expect(page.getByText('正在加载实例控制台')).toHaveCount(0)
  await expect(page.getByText('暂无运行中实例。点击「创建新策略实例」启动策略。')).toBeVisible()
})
