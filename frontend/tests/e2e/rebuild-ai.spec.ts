import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('AI lab keeps the BitPro workbench and A-share evidence boundary', async ({ page }) => { await installFinalFixtures(page); await page.goto('/ai-lab'); await expect(page.getByRole('heading',{name:'AI策略助手'})).toBeVisible(); for (const label of ['自动交易Agent','AI自主交易','新策略研发','现有策略优化']) await expect(page.getByText(label,{exact:true})).toHaveCount(1); await expect(page.getByText(/OKX持仓|自动实盘|USDT/)).toHaveCount(0) })
