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
