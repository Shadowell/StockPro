import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('AI lab keeps the BitPro workbench and A-share evidence boundary', async ({ page }) => { await installFinalFixtures(page); await page.goto('/ai-lab'); await expect(page.getByRole('heading',{name:'AI策略助手'})).toBeVisible(); for (const label of ['自动交易Agent','AI自主交易','新策略研发','现有策略优化']) await expect(page.getByText(label,{exact:true})).toHaveCount(1); await expect(page.getByText(/OKX持仓|自动实盘|USDT/)).toHaveCount(0) })

test('ARC keeps an explicit A-share zero-write state on narrow screens', async ({ page }) => {
  await installFinalFixtures(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/arc')
  await expect(page.getByRole('heading', { name: '启动研究' })).toBeVisible()
  await expect(page.getByLabel('标的')).toHaveValue('600519.SH')
  await expect(page.getByLabel('周期')).toHaveValue('1D')
  await expect(page.getByRole('button', { name: '启动研究' })).toBeDisabled()
  await expect(page.getByText(/ETH|BTC|USDT/)).toHaveCount(0)
  await expect(page.getByText(/不会创建任务、回测或 Paper/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
})
