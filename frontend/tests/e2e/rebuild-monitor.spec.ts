import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('monitor exposes Paper lifecycle and health evidence',async({page})=>{await installFinalFixtures(page);await page.goto('/monitor');await expect(page.getByRole('heading',{name:'监控中心'})).toBeVisible();await expect(page.getByRole('heading',{name:'模拟盘总览'})).toBeVisible()})
