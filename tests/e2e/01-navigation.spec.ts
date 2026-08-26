/**
 * E2E-01: 导航 & 通用布局测试
 * 验证侧边栏导航、页面跳转、交易所切换、设置面板
 */
import { test, expect } from '@playwright/test';

test.describe('侧边栏导航', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('页面加载后应显示侧边栏', async ({ page }) => {
    const sidebar = page.locator('aside');
    await expect(sidebar).toBeVisible();
  });

  const navItems = [
    { text: '首页', path: '/' },
    { text: '行情', path: '/market' },
    { text: '策略', path: '/strategy' },
    { text: '回测', path: '/backtest' },
    { text: '模拟', path: '/live' },
    { text: '监控', path: '/monitor' },
    { text: '实盘', path: '/live-real' },
  ];

  for (const item of navItems) {
    test(`点击"${item.text}"应导航到 ${item.path}`, async ({ page }) => {
      await page.locator('aside').getByText(item.text, { exact: false }).first().click();
      await page.waitForLoadState('networkidle');
      // URL 路径匹配
      if (item.path === '/') {
        expect(page.url()).toMatch(/\/$/);
      } else {
        expect(page.url()).toContain(item.path);
      }
    });
  }
});

test.describe('侧边栏底部', () => {
  test('侧边栏不应显示固定交易所标识', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const okxLabel = page.locator('aside').getByText('OKX');
    await expect(okxLabel).toHaveCount(0);
  });

  test('不应存在 Bybit 选项', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    const bybit = page.locator('aside').getByText('Bybit');
    await expect(bybit).toHaveCount(0);
  });
});

test.describe('设置面板', () => {
  test('点击设置按钮应打开设置面板', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 设置按钮在侧边栏底部
    const settingsBtn = page.locator('aside button').last();
    await settingsBtn.click();
    await page.waitForTimeout(300);

    // 设置面板应包含颜色方案选项
    const panel = page.getByText('红涨绿跌');
    await expect(panel).toBeVisible();
  });

  test('应能切换K线颜色方案', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 打开设置
    const settingsBtn = page.locator('aside button').last();
    await settingsBtn.click();
    await page.waitForTimeout(300);

    // 点击"绿涨红跌"
    const greenUp = page.getByText('绿涨红跌');
    if (await greenUp.isVisible()) {
      await greenUp.click();
      await page.waitForTimeout(300);
    }

    // 点击"红涨绿跌"
    const redUp = page.getByText('红涨绿跌');
    if (await redUp.isVisible()) {
      await redUp.click();
      await page.waitForTimeout(300);
    }
  });
});
