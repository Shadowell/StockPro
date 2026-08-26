import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('strategy center keeps BitPro catalogue and A-share lineage',async({page})=>{await installFinalFixtures(page);await page.goto('/strategy');await expect(page.getByRole('heading',{name:'策略中心'})).toBeVisible();await expect(page.getByLabel('搜索策略')).toBeVisible();for(const label of ['股票','ETF','动量趋势','均值回归','多因子','事件驱动'])await expect(page.getByText(label,{exact:true}).first()).toBeVisible();await expect(page.getByText(/BTC|USDT|OKX|永续/)).toHaveCount(0)})
