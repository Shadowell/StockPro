import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'

const routes: [string, string][] = [
  ['/', '市场大盘'],
  ['/market', 'A股行情'],
  ['/pools', '股票池'],
  ['/factors', '因子库'],
  ['/strategy', '策略中心'],
  ['/backtest', '回测'],
  ['/paper', '模拟盘'],
  ['/watch', '盯盘'],
  ['/signals', '信号中心'],
  ['/monitor', '监控'],
  ['/review', '复盘中心'],
  ['/data', '数据管理中心'],
  ['/ai-lab', 'AI策略助手'],
]

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`all owner routes satisfy operator shell at ${viewport.width}`, async ({ page }) => {
    test.setTimeout(360_000)
    const pageErrors: string[] = []
    const serverErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    page.on('response', (response) => {
      if (response.url().includes('/api/') && response.status() >= 500) {
        serverErrors.push(`${response.status()} ${new URL(response.url()).pathname}`)
      }
    })
    if (process.env.MOCK_API !== 'false') {
      await installFinalFixtures(page)
    }
    await page.setViewportSize(viewport)

    if (process.env.MOCK_API === 'false') {
      await page.goto('/')
      if (await page.getByRole('heading', { name: '登录 StockPro' }).isVisible()) {
        await page.getByLabel('密码').fill(process.env.E2E_ADMIN_PASSWORD || 'stockpro123')
        await page.getByRole('button', { name: '进入工作台' }).click()
        await expect(page.getByTestId('main-layout')).toBeVisible({ timeout: 60_000 })
      }
    }

    for (const [route, heading] of routes) {
      await page.goto(route)
      await expect(page.getByTestId('main-layout')).toBeVisible({ timeout: 60_000 })
      await expect(page.locator('[data-operator-page]')).toBeVisible({ timeout: 60_000 })
      await expect(page.getByRole('heading', { name: heading }).first()).toBeVisible({ timeout: 60_000 })
      await page.waitForTimeout(300)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
    }
    expect(pageErrors).toEqual([])
    expect(serverErrors).toEqual([])
  })
}
