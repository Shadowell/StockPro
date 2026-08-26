import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('market exposes A-share controls without crypto semantics',async({page})=>{await installFinalFixtures(page);await page.goto('/market');await expect(page.getByRole('heading',{name:'行情'})).toBeVisible();await expect(page.getByText(/BTC|USDT|OKX|资金费率/)).toHaveCount(0)})
