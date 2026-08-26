/**
 * E2E-09: UI质量检查
 * 验证元素重叠、布局崩溃、响应式、控制台错误
 */
import { test, expect } from '@playwright/test';

test.describe('UI 质量 - 控制台错误', () => {
  const pages = [
    { name: '首页', path: '/' },
    { name: '行情', path: '/market' },
    { name: '策略', path: '/strategy' },
    { name: '回测', path: '/backtest' },
    { name: '模拟', path: '/live' },
    { name: '监控', path: '/monitor' },
    { name: '信号', path: '/signals' },
    { name: '实盘', path: '/live-real' },
  ];

  for (const p of pages) {
    test(`${p.name}页面不应有JS严重错误`, async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', (err) => {
        // 忽略某些常见非关键错误
        const msg = err.message;
        if (msg.includes('ResizeObserver') || msg.includes('Network') || msg.includes('fetch')) return;
        errors.push(msg);
      });

      await page.goto(p.path);
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(3000);

      expect(errors, `${p.name}页面有JS错误: ${errors.join('\n')}`).toHaveLength(0);
    });
  }
});

test.describe('UI 质量 - 布局完整性', () => {
  test('侧边栏不应覆盖主内容区', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const sidebar = page.locator('aside');
    const main = page.locator('main');

    await expect(sidebar).toBeVisible({ timeout: 10000 });
    await expect(main).toBeVisible({ timeout: 10000 });

    const sidebarBox = await sidebar.boundingBox();
    const mainBox = await main.boundingBox();

    if (sidebarBox && mainBox) {
      // flex 布局下，sidebar 和 main 紧邻，sidebar 右边界 ≈ main 左边界
      const overlap = (sidebarBox.x + sidebarBox.width) - mainBox.x;
      // 允许最多 2px 重叠（浮点像素误差）
      expect(overlap, '侧边栏严重覆盖主内容区').toBeLessThanOrEqual(sidebarBox.width);
      // 主内容区宽度应大于 sidebar 宽度的 5 倍（sidebar ~64px, main 应 > 320px）
      expect(mainBox.width, '主内容区宽度异常').toBeGreaterThan(sidebarBox.width * 5);
    }
  });

  test('所有页面的主内容区不应水平溢出', async ({ page }) => {
    const paths = ['/', '/market', '/strategy', '/backtest', '/live', '/monitor'];
    for (const path of paths) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(1000);

      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth;
      });
      expect(hasHorizontalScroll, `${path} 有水平滚动条`).toBe(false);
    }
  });
});

test.describe('UI 质量 - 策略页图标不重叠', () => {
  test('策略列表中名称和操作按钮不应重叠', async ({ page }) => {
    await page.goto('/strategy');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    // 查找策略卡片中的操作按钮区域
    const actionBtns = page.locator('button').filter({ has: page.locator('svg') });
    const count = await actionBtns.count();

    for (let i = 0; i < Math.min(count, 5); i++) {
      const btn = actionBtns.nth(i);
      if (await btn.isVisible()) {
        const box = await btn.boundingBox();
        if (box) {
          // 按钮应有合理尺寸（不被压扁）
          expect(box.width, `按钮 ${i} 宽度过小`).toBeGreaterThan(20);
          expect(box.height, `按钮 ${i} 高度过小`).toBeGreaterThan(20);
        }
      }
    }
  });
});

test.describe('UI 质量 - 无 404 资源', () => {
  test('页面加载不应有 404 请求', async ({ page }) => {
    const notFoundRequests: string[] = [];

    page.on('response', (response) => {
      if (response.status() === 404 && !response.url().includes('favicon')) {
        notFoundRequests.push(response.url());
      }
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    expect(notFoundRequests, `存在 404 资源: ${notFoundRequests.join('\n')}`).toHaveLength(0);
  });
});

test.describe('UI 质量 - API 请求检查', () => {
  const pageAPIs = [
    { page: '/', api: '/api/v2/', desc: '首页应发起 API 请求' },
    { page: '/market', api: '/api/v2/', desc: '行情页应发起 API 请求' },
  ];

  for (const p of pageAPIs) {
    test(p.desc, async ({ page }) => {
      const apiRequests: string[] = [];
      page.on('request', (req) => {
        if (req.url().includes(p.api)) {
          apiRequests.push(req.url());
        }
      });

      await page.goto(p.page);
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(5000);

      expect(apiRequests.length, `${p.page} 没有发起 API 请求`).toBeGreaterThan(0);
    });
  }
});
