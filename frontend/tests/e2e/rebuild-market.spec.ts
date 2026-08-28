import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('market exposes an honest A-share empty state without crypto semantics',async({page})=>{await installFinalFixtures(page);await page.goto('/market');await expect(page.getByRole('heading',{name:'行情'})).toBeVisible();await expect(page.getByText('暂无 K 线数据')).toBeVisible();await expect(page.getByText(/BTC|USDT|OKX|资金费率|K线数据加载中/)).toHaveCount(0)})

test('market selector searches Chinese name and renders it before code', async ({ page }) => {
  await installFinalFixtures(page)
  await page.goto('/market')

  await page.getByRole('button', { name: /贵州茅台.*600519\.SH/ }).click()
  const search = page.getByPlaceholder('搜索中文名称或股票代码...')
  await search.fill('平安')
  const option = page.getByTestId('symbol-option-000001.SZ')
  await expect(option).toBeVisible()
  const text = await option.innerText()
  expect(text.indexOf('平安银行')).toBeLessThan(text.indexOf('000001.SZ'))
})

test('market type and symbol controls keep equal responsive widths', async ({ page }) => {
  await installFinalFixtures(page)
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await page.goto('/market')
    await expect(page.getByTestId('symbol-search-trigger')).toBeVisible()
    const widths = await page.evaluate(() => ({
      marketType: document.querySelector('.market-type-toggle')?.getBoundingClientRect().width || 0,
      symbol: document.querySelector('[data-testid="symbol-search-trigger"]')?.getBoundingClientRect().width || 0,
    }))
    expect(widths.marketType).toBeGreaterThan(0)
    expect(Math.abs(widths.marketType - widths.symbol)).toBeLessThanOrEqual(1)
  }
})
