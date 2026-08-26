import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('Paper dashboard renders an honest empty state without reset',async({page})=>{await installFinalFixtures(page);await page.goto('/live');await expect(page.getByText('策略实例控制台')).toBeVisible();await expect(page.getByText('模拟：只做 PaperBroker / 模拟成交，不触碰真实资金。')).toBeVisible();await expect(page.getByRole('button',{name:/清空|重置/})).toHaveCount(0);await expect(page.getByText(/USDT|杠杆|强平|OKX/)).toHaveCount(0)})
