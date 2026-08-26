import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('capability shell keeps current research pages and futures hidden', async ({ page }) => { await installFinalFixtures(page); await page.goto('/'); const nav=page.getByRole('navigation'); for(const label of ['数据','因子','基本面','AI研发','自主研究']) await expect(nav.getByText(label,{exact:true})).toBeVisible(); await expect(nav.getByText('期货',{exact:true})).toHaveCount(0); await page.goto('/futures'); await expect(page).toHaveURL('/') })
