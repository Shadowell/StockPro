import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('backtest console keeps BitPro workflow and sealed A-share controls', async ({ page }) => { await installFinalFixtures(page); await page.goto('/backtest'); await expect(page.getByRole('heading',{name:'回测',exact:true})).toBeVisible(); await expect(page.getByRole('button',{name:'创建回测实例'})).toBeDisabled(); await expect(page.getByRole('button',{name:'创建批量回测实例'})).toBeDisabled(); await expect(page.getByText(/USDT|OKX|永续|杠杆/)).toHaveCount(0) })
