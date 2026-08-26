import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('A-share spread and fundamental replacements keep honest source-backed empty states',async({page})=>{await installFinalFixtures(page);await page.goto('/arbitrage');await expect(page.getByText('A 股价差研究',{exact:true})).toBeVisible();await expect(page.getByText(/不生成虚假套利机会/)).toBeVisible();await page.goto('/onchain');await expect(page.getByText('A 股基本面与资金流',{exact:true})).toBeVisible();await expect(page.getByText(/不用模拟数据填充/)).toBeVisible()})
