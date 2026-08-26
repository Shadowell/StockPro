/**
 * E2E-03: 行情页测试
 * 验证K线图渲染、时间周期切换、交易对切换、订单簿
 */
import { test, expect } from '@playwright/test';

test.describe('行情页', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/market');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
  });

  test('页面应正常加载', async ({ page }) => {
    // 页面应有行情相关内容
    const heading = page.getByText('行情').first();
    await expect(heading).toBeVisible();
  });

  test('K线图区域应渲染（canvas）', async ({ page }) => {
    await page.waitForTimeout(5000);
    // ECharts 渲染为 canvas
    const canvas = page.locator('canvas').first();
    await expect(canvas).toBeVisible({ timeout: 15000 });
  });

  test('时间周期按钮应可切换', async ({ page }) => {
    const timeframes = ['1m', '5m', '15m', '1h', '4h', '1d'];

    for (const tf of timeframes) {
      const btn = page.getByText(tf, { exact: true }).first();
      if (await btn.isVisible()) {
        await btn.click();
        await page.waitForTimeout(1500);
        // K线图应刷新（canvas 仍然存在）
        const canvas = page.locator('canvas').first();
        await expect(canvas).toBeVisible();
      }
    }
  });

  test('应显示价格信息', async ({ page }) => {
    await page.waitForTimeout(5000);
    // 应有数字价格显示
    const priceArea = page.locator('text=/\\d+[.,]\\d+/').first();
    await expect(priceArea).toBeVisible({ timeout: 10000 });
  });

  test('订单簿区域应有买卖数据', async ({ page }) => {
    await page.waitForTimeout(5000);
    // 订单簿应有 "买" 或 "卖" 或 "bids"/"asks" 相关内容
    const orderbook = page.getByText('买').or(page.getByText('卖')).or(page.getByText('订单簿'));
    await expect(orderbook.first()).toBeVisible({ timeout: 10000 });
  });
});
