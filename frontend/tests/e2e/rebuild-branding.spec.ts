import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'

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

test('authenticated users exit from account settings instead of the sidebar', async ({ page }) => {
  await installFinalFixtures(page)
  await page.route('**/api/v2/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ auth_enabled: true, authenticated: true, role: 'admin', permissions: ['admin'] }),
    })
  })
  await page.route('**/api/v2/auth/logout', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ logged_out: true }) })
  })

  await page.goto('/')
  await expect(page.getByTestId('main-layout')).toBeVisible()
  await expect(page.getByTitle('退出登录')).toHaveCount(0)

  await page.getByRole('button', { name: '打开设置' }).click()
  await page.getByRole('button', { name: /账户与会话/ }).click()
  await expect(page.getByText('当前会话', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '退出登录' }).click()

  await expect(page.getByRole('heading', { name: '登录 StockPro' })).toBeVisible()
})
