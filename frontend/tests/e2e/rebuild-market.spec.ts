import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('market exposes an honest A-share empty state without crypto semantics',async({page})=>{await installFinalFixtures(page);await page.goto('/market');await expect(page.getByRole('heading',{name:'行情'})).toBeVisible();await expect(page.getByText('暂无 K 线数据')).toBeVisible();await expect(page.getByText(/BTC|USDT|OKX|资金费率|K线数据加载中/)).toHaveCount(0)})
