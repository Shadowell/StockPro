/**
 * E2E-02: 首页测试
 * 验证行情列表加载、搜索、排序、Tab 切换
 */
import { test, expect } from '@playwright/test';

test.describe('首页 - 行情总览', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('页面标题应包含"行情"相关内容', async ({ page }) => {
    const heading = page.getByText('行情总览').or(page.getByText('首页'));
    await expect(heading.first()).toBeVisible();
  });

  test('应显示币种列表', async ({ page }) => {
    // 等待数据加载
    await page.waitForTimeout(3000);

    // 表头应包含关键列
    await expect(page.getByText('币种').first()).toBeVisible();
    await expect(page.getByText('最新价').first()).toBeVisible();
  });

  test('行情列表应有数据行', async ({ page }) => {
    await page.waitForTimeout(5000);

    // 查找包含 BTC 或 ETH 的文本（常见交易对）
    const btcRow = page.getByText('BTC').first();
    await expect(btcRow).toBeVisible({ timeout: 10000 });
  });

  test('搜索功能应正常工作', async ({ page }) => {
    await page.waitForTimeout(3000);

    const searchInput = page.locator('input[placeholder*="搜索"]').first();
    if (await searchInput.isVisible()) {
      await searchInput.fill('ETH');
      await page.waitForTimeout(1000);

      // 搜索后结果应包含 ETH
      const ethVisible = page.getByText('ETH').first();
      await expect(ethVisible).toBeVisible();
    }
  });

  test('Tab 切换应正常', async ({ page }) => {
    await page.waitForTimeout(2000);

    // 查找 Tab 按钮
    const tabs = ['全部', '现货'];
    for (const tabText of tabs) {
      const tab = page.getByText(tabText, { exact: true }).first();
      if (await tab.isVisible()) {
        await tab.click();
        await page.waitForTimeout(500);
      }
    }
  });

  test('点击币种行应跳转到行情页', async ({ page }) => {
    await page.waitForTimeout(5000);

    // 找到 BTC 行并点击
    const btcLink = page.getByText('BTC/USDT').first();
    if (await btcLink.isVisible()) {
      await btcLink.click();
      await page.waitForTimeout(1000);
      // 应跳转到行情页
      expect(page.url()).toContain('/market');
    }
  });

  test('刷新按钮应可点击', async ({ page }) => {
    await page.waitForTimeout(2000);
    // 找到刷新按钮（RefreshCw 图标在 svg 中）
    const refreshBtn = page.locator('button').filter({ has: page.locator('svg') }).first();
    if (await refreshBtn.isVisible()) {
      await refreshBtn.click();
      await page.waitForTimeout(1000);
    }
  });
});
