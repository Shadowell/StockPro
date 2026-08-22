import { test, expect } from '@playwright/test';

test.describe('交易页已屏蔽', () => {
  test('/trading 应重定向到首页', async ({ page }) => {
    await page.goto('/trading');
    await page.waitForLoadState('networkidle');

    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator('aside').getByText('交易', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: '交易', exact: true })).toHaveCount(0);
  });
});
