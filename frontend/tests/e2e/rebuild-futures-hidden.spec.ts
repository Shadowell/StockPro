import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('futures remains hidden until a separate contract ships',async({page})=>{await installFinalFixtures(page);await page.goto('/');await expect(page.getByRole('navigation').getByText('期货',{exact:true})).toHaveCount(0);await page.goto('/futures');await expect(page).toHaveURL('/')})
