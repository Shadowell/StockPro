import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('signal center audits and watch observes without order actions',async({page})=>{await installFinalFixtures(page);await page.goto('/signals');await expect(page.getByRole('heading',{name:'信号中心'})).toBeVisible();await expect(page.getByRole('button',{name:/买入|卖出|下单/})).toHaveCount(0);await page.goto('/watch');await expect(page.getByRole('heading',{name:'盯盘'})).toBeVisible();await expect(page.getByText(/USDT|永续|强平|保证金/)).toHaveCount(0)})
