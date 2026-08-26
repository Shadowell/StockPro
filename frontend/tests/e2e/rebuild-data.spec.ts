import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('data center exposes the BitPro A-share management workspace', async ({ page }) => { await installFinalFixtures(page); await page.goto('/data'); await expect(page.getByRole('heading',{name:'数据管理中心'})).toBeVisible(); for(const label of ['总记录数','同步状态','数据质量','同步任务明细']) await expect(page.getByText(label,{exact:true}).first()).toBeVisible(); await expect(page.getByText(/SQLite|USDT|OKX/)).toHaveCount(0) })

test('data center renders Chinese name before public A-share code', async ({ page }) => {
  await installFinalFixtures(page)
  await page.goto('/data')

  const card = page.getByTestId('data-symbol-600519.SH')
  await expect(card).toBeVisible()
  const text = await card.innerText()
  expect(text.indexOf('贵州茅台')).toBeGreaterThanOrEqual(0)
  expect(text.indexOf('贵州茅台')).toBeLessThan(text.indexOf('600519.SH'))
  await expect(page.getByText('后续同步名单 2 个', { exact: false })).toBeVisible()
})
