import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('review reads A-share evidence without page-load assembly',async({page})=>{await installFinalFixtures(page);const writes:string[]=[];page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method()))writes.push(r.url())});await page.goto('/review');await expect(page.getByRole('heading',{name:'复盘中心'})).toBeVisible();await expect(page.getByText(/USDT|OKX|资金费率/)).toHaveCount(0);expect(writes).toEqual([])})
