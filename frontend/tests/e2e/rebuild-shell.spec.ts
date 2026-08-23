import { expect, test } from '@playwright/test'


test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        auth_enabled: false,
        authenticated: true,
        role: 'admin',
        permissions: ['admin'],
      }),
    })
  })
  await page.route('**/api/market/overview', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        indices: [], breadth: null, turnover: null, limit_ecology: null, sector_flows: [],
        source_label: 'PostgreSQL market cache', source_updated_at: null, trade_date: null, data_status: 'empty',
      }),
    })
  })
  await page.route('**/api/strategies', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))
  await page.route('**/api/paper/instances?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0, scope: 'audit' }) }))
  await page.route('**/api/backtest/runs*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))
})


test('shell remains mounted and only approved A-share routes are visible', async ({ page }, testInfo) => {
  await page.goto('/')
  const shell = page.getByTestId('main-layout')
  await expect(shell).toBeVisible()

  const navigation = page.getByRole('navigation')
  for (const label of [
    '首页',
    '行情',
    '股票池',
    '因子',
    '策略',
    '回测',
    '模拟',
    '盯盘',
    '信号',
    '监控',
    '复盘',
    '数据',
    'AI研发',
  ]) {
    await expect(navigation.getByText(label, { exact: true })).toBeVisible()
  }
  for (const hidden of ['实盘', '链上', 'ARC', '套利', '期货']) {
    await expect(navigation.getByText(hidden, { exact: true })).toHaveCount(0)
  }

  await shell.evaluate((element) => element.setAttribute('data-shell-probe', 'mounted'))
  await navigation.getByText('策略', { exact: true }).click()
  await expect(page).toHaveURL(/\/strategy$/)
  await expect(shell).toBeVisible()
  await expect(shell).toHaveAttribute('data-shell-probe', 'mounted')
  await expect(page.getByRole('heading', { name: '策略中心' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('shell-desktop.png'), fullPage: true })
})


test('shell keeps the workspace readable at a narrow viewport', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/paper')

  await expect(page.getByTestId('main-layout')).toBeVisible()
  await expect(page.getByRole('heading', { name: '模拟盘' })).toBeVisible()
  await expect(page.getByText('仅模拟', { exact: true })).toBeVisible()
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('shell-narrow.png'), fullPage: true })
})
