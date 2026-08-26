import { expect, test } from '@playwright/test'

test('authentication gate keeps the source layout with StockPro A-share branding', async ({ page }) => {
  await page.route('**/api/v2/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ auth_enabled: true, authenticated: false, role: null, permissions: [] }),
    })
  })

  await page.goto('/')

  await expect(page).toHaveTitle('StockPro - A股量化研究与模拟交易平台')
  await expect(page.getByRole('heading', { name: '登录 StockPro' })).toBeVisible()
  await expect(page.getByRole('img', { name: 'StockPro' })).toBeVisible()
  await expect(page.getByText('BitPro', { exact: true })).toHaveCount(0)
})
