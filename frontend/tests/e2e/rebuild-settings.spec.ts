import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'

test('settings domains load truthful StockPro configuration without failed requests', async ({ page }) => {
  await installFinalFixtures(page)
  const failedResponses: string[] = []
  const consoleErrors: string[] = []
  page.on('response', (response) => {
    if (response.status() >= 400) failedResponses.push(`${response.status()} ${response.url()}`)
  })
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/data')
  await page.getByRole('button', { name: '打开设置' }).click()

  await page.getByRole('button', { name: /AI 与模型/ }).click()
  await expect(page.getByText(/DashScope · OpenAI 兼容 HTTP/)).toBeVisible()
  await expect(page.getByRole('button', { name: '测试连接' }).first()).toBeDisabled()
  await expect(page.getByText('凭据未配置', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: /Agent 接入/ }).click()
  await expect(page.getByText('X-StockPro-MCP-Token', { exact: true })).toBeVisible()
  await expect(page.getByText('STOCKPRO_MCP_API_TOKEN', { exact: true })).toBeVisible()
  await expect(page.getByText(/兼容旧名.*X-BitPro-MCP-Token.*BITPRO_MCP_API_TOKEN/)).toBeVisible()

  await page.getByRole('button', { name: /访问权限/ }).click()
  await expect(page.getByText('访客邀请码管理', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: /通知通道/ }).click()
  await expect(page.getByText('飞书 Webhook', { exact: true })).toBeVisible()
  await expect(page.getByText('Not Found', { exact: true })).toHaveCount(0)

  expect(failedResponses).toEqual([])
  expect(consoleErrors).toEqual([])
})
