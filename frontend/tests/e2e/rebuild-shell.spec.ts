import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'

test.beforeEach(async ({ page }) => installFinalFixtures(page))

test('shell remains mounted and exposes the current A-share owner routes', async ({ page }, testInfo) => {
  await page.goto('/')
  const shell = page.getByTestId('main-layout')
  const navigation = page.getByRole('navigation')
  await expect(shell).toBeVisible()
  for (const label of ['首页', '行情', '策略', '回测', '模拟', '盯盘', '资金流', '监控', '复盘', '数据', '因子', '基本面', 'AI研发', '自主研究']) {
    await expect(navigation.getByText(label, { exact: true })).toBeVisible()
  }
  for (const hidden of ['实盘', '期货', 'OKX', 'USDT']) await expect(navigation.getByText(hidden, { exact: true })).toHaveCount(0)
  await shell.evaluate((element) => element.setAttribute('data-shell-probe', 'mounted'))
  await navigation.getByText('策略', { exact: true }).click()
  await expect(page).toHaveURL(/\/strategy$/)
  await expect(shell).toHaveAttribute('data-shell-probe', 'mounted')
  await expect(page.getByRole('heading', { name: '策略中心' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('shell-desktop.png'), fullPage: true })
})

test('A-share research replacements are reachable while unknown futures stays hidden', async ({ page }) => {
  await page.goto('/arbitrage')
  await expect(page.getByRole('heading', { name: 'A 股价差研究' })).toBeVisible()
  await page.goto('/onchain')
  await expect(page.getByRole('heading', { name: 'A 股基本面与资金流' })).toBeVisible()
  await page.goto('/arc')
  await expect(page.getByRole('heading', { name: '自主研究' })).toBeVisible()
  await page.goto('/futures')
  await expect(page).toHaveURL('/')
  await expect(page.getByRole('navigation').getByText('期货', { exact: true })).toHaveCount(0)
})

test('shell keeps the Paper workspace readable at a narrow viewport', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/live')
  await expect(page.getByTestId('main-layout')).toBeVisible()
  await expect(page.getByText('模拟：只做 PaperBroker / 模拟成交，不触碰真实资金。')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('shell-narrow.png'), fullPage: true })
})
