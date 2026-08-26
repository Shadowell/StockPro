import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('factor lab keeps null-safe A-share evidence without page-load mutations', async ({ page }) => { await installFinalFixtures(page); const writes:string[]=[]; page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method()))writes.push(r.url())}); await page.goto('/factorlab'); await expect(page.getByRole('heading',{name:'因子库与实验'})).toBeVisible(); await expect(page.getByText(/USDT|OKX|资金费率/)).toHaveCount(0); expect(writes).toEqual([]) })
