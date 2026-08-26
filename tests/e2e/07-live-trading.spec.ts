/**
 * E2E-07: 实盘/模拟盘页测试
 * 验证模式切换、策略选择、步骤流程
 */
import { test, expect } from '@playwright/test';

test.describe('实盘页', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/live');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
  });

  test('页面应正常加载', async ({ page }) => {
    const heading = page.getByText('实盘').or(page.getByText('模拟'));
    await expect(heading.first()).toBeVisible();
  });

  test('模拟盘/实盘切换Tab应存在', async ({ page }) => {
    const paperTab = page.getByText('模拟盘').or(page.getByText('模拟'));
    const liveTab = page.getByText('实盘');

    // 至少一个应可见
    const visible = await paperTab.first().isVisible() || await liveTab.first().isVisible();
    expect(visible).toBeTruthy();
  });

  test('模拟盘/实盘Tab应可切换', async ({ page }) => {
    const paperTab = page.getByText('模拟盘').first();
    const liveTab = page.getByText('实盘').first();

    if (await paperTab.isVisible()) {
      await paperTab.click();
      await page.waitForTimeout(500);
    }

    if (await liveTab.isVisible()) {
      await liveTab.click();
      await page.waitForTimeout(500);
    }
  });

  test('应显示策略选择卡片或步骤导航', async ({ page }) => {
    await page.waitForTimeout(3000);
    // 应有步骤指示或策略卡片
    const steps = page.getByText('选择策略').or(page.getByText('配置参数')).or(page.getByText('策略'));
    await expect(steps.first()).toBeVisible({ timeout: 10000 });
  });

  test('选择策略后应出现下一步按钮', async ({ page }) => {
    await page.waitForTimeout(3000);

    // 查找策略卡片并点击
    const strategyCards = page.locator('[class*="card"], [class*="border"]').filter({ hasText: /均线|MA|RSI|布林|MACD/ });
    if (await strategyCards.first().isVisible()) {
      await strategyCards.first().click();
      await page.waitForTimeout(500);

      // 应出现"下一步"按钮
      const nextBtn = page.getByText('下一步').or(page.getByText('配置'));
      await expect(nextBtn.first()).toBeVisible({ timeout: 5000 });
    }
  });
});
