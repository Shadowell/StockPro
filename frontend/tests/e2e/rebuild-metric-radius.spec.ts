import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'

test('all compact metric cards have visible rounded corners', async ({ page }) => {
  await installFinalFixtures(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  let inspected = 0
  for (const route of ['/', '/factorlab', '/review', '/arc', '/onchain']) {
    await page.goto(route)
    await expect(page.locator('[data-operator-page]')).toBeVisible()
    const cards = page.locator('[data-metric-card]')
    const count = await cards.count()
    inspected += count
    for (let index = 0; index < count; index += 1) {
      const radii = await cards.nth(index).evaluate((element) => {
        const style = getComputedStyle(element)
        return [style.borderTopLeftRadius, style.borderTopRightRadius, style.borderBottomRightRadius, style.borderBottomLeftRadius]
          .map((value) => Number.parseFloat(value))
      })
      expect(radii.every((radius) => Number.isFinite(radius) && radius >= 8)).toBeTruthy()
    }
  }
  expect(inspected).toBeGreaterThan(10)
})
