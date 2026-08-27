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

test('admin can start the half-year all-stock daily sync', async ({ page }) => {
  await installFinalFixtures(page)
  let requestPayload: Record<string, unknown> | undefined
  await page.route('**/api/v2/sync/history/sync-all', async (route) => {
    requestPayload = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          run_id: 18,
          status: 'success',
          sync_scope: 'history',
          instrument_count: 5500,
          daily_count: 660000,
          trade_date_count: 120,
        },
      }),
    })
  })

  await page.goto('/data')
  const button = page.getByTestId('ashare-history-sync-button')
  await expect(button).toBeEnabled()
  await button.click()
  await expect(page.getByTestId('ashare-history-sync-feedback')).toContainText('660.0K')
  expect(requestPayload).toEqual({ history_days: 180 })
})

test('data center safely expands a sync job with missing optional fields', async ({ page }) => {
  await installFinalFixtures(page)
  await page.route('**/api/v2/sync/jobs**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ jobs: [{ status: 'completed', exchange: 'CN' }, {}] }),
    })
  })

  const pageErrors: string[] = []
  const consoleErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/data')
  await page.getByRole('button', { name: /同步任务明细/ }).click()

  await expect(page.getByText('任务 —', { exact: true })).toHaveCount(2)
  await expect(page.getByText('页面加载失败')).toHaveCount(0)
  expect(pageErrors).toEqual([])
  expect(consoleErrors).toEqual([])

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await page.getByRole('button', { name: /同步任务明细/ }).click()

  await expect(page.getByText('任务 —', { exact: true })).toHaveCount(2)
  await expect(page.getByText('页面加载失败')).toHaveCount(0)
  expect(pageErrors).toEqual([])
  expect(consoleErrors).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})
