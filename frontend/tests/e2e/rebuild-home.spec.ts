import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('home exposes abnormal windows and an alert-only event stream',async({page})=>{await installFinalFixtures(page);await page.goto('/');await expect(page.getByText('异动边缘',{exact:true}).first()).toBeVisible();await expect(page.getByText('3日 +16.0% / 20% · 80%').first()).toBeVisible();await expect(page.getByText('告警事件流',{exact:true})).toBeVisible();await expect(page.getByText('3日异动边缘',{exact:true})).toBeVisible();await expect(page.getByText(/orders_created=0/)).toBeVisible();await page.getByRole('button',{name:'监控中心'}).click();await expect(page).toHaveURL(/\/monitor/)})
test('home abnormal symbol drilldown goes to the StockPro market page',async({page})=>{await installFinalFixtures(page);await page.goto('/');await page.getByText('贵州茅台（600519.SH）',{exact:true}).first().click();await expect(page).toHaveURL(/\/market/)})
test('home keeps the A-share market overview foundation readable', async ({ page }) => {
  await installFinalFixtures(page)
  await page.goto('/')
  for (const heading of ['市场大盘', 'A 股市场基础层', '指数行情', '市场宽度 · 涨跌分布', '趋势强度', '成交与换手', '排行榜']) {
    await expect(page.getByRole('heading', { name: heading, exact: true }).first()).toBeVisible()
  }
  await expect(page.getByText(/资金费率|杠杆情绪|多空拥挤|USDT|OKX/)).toHaveCount(0)
})

test('home remains readable on a narrow viewport', async ({ page }) => {
  await installFinalFixtures(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '市场大盘' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '指数行情' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
})
