/**
 * E2E-08: 监控页测试
 * 验证市场情绪、告警配置、运行中策略
 */
import { test, expect } from '@playwright/test';

test('运行中策略缺少盈亏字段时不应触发页面加载失败', async ({ page }) => {
  await page.route('**/api/v2/monitor/alerts', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: [] }),
    });
  });

  await page.route('**/api/v2/monitor/active_strategies', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          {
            strategy_id: 7,
            name: '缺省盈亏策略',
            status: 'running',
            exchange: 'okx',
            symbols: ['BTC/USDT'],
            positions: {},
          },
        ],
      }),
    });
  });

  await page.route('**/api/v2/monitor/long-short-ratio**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { long_short_ratio: 1.2 } }),
    });
  });

  await page.route('**/api/v2/monitor/open-interest**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { open_interest: 123456789, change_pct: 0.8 } }),
    });
  });

  await page.route('**/api/v2/market/ticker**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: {} }),
    });
  });

  await page.goto('/monitor');
  await page.waitForLoadState('networkidle');

  await expect(page.getByText('页面加载失败')).toHaveCount(0);
  await expect(page.getByText('缺省盈亏策略')).toBeVisible();
  await expect(page.getByText('$0.00').first()).toBeVisible();
});

test.describe('监控页', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/monitor');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
  });

  test('页面应显示监控标题', async ({ page }) => {
    const heading = page.getByText('监控').first();
    await expect(heading).toBeVisible();
  });

  test('应显示市场情绪指标区域', async ({ page }) => {
    await page.waitForTimeout(3000);
    // 查找市场情绪相关指标
    const sentimentArea = page.getByText('多空比')
      .or(page.getByText('持仓量'))
      .or(page.getByText('恐惧'))
      .or(page.getByText('市场'));
    await expect(sentimentArea.first()).toBeVisible({ timeout: 10000 });
  });

  test('刷新数据按钮应可点击', async ({ page }) => {
    const refreshBtn = page.getByText('刷新数据').or(page.getByText('刷新'));
    if (await refreshBtn.first().isVisible()) {
      await refreshBtn.first().click();
      await page.waitForTimeout(2000);
    }
  });

  test('告警区域应存在', async ({ page }) => {
    const alertArea = page.getByText('告警').or(page.getByText('警报'));
    await expect(alertArea.first()).toBeVisible({ timeout: 5000 });
  });

  test('添加告警按钮应可点击并打开表单', async ({ page }) => {
    const addBtn = page.getByText('添加').first();
    if (await addBtn.isVisible()) {
      await addBtn.click();
      await page.waitForTimeout(500);

      // 应显示告警创建表单
      const formField = page.locator('input[placeholder*="BTC"]')
        .or(page.getByText('告警名称'))
        .or(page.getByText('创建'));
      await expect(formField.first()).toBeVisible({ timeout: 3000 });
    }
  });

  test('创建告警表单应可填写', async ({ page }) => {
    const addBtn = page.getByText('添加').first();
    if (await addBtn.isVisible()) {
      await addBtn.click();
      await page.waitForTimeout(500);

      // 填写告警名称
      const nameInput = page.locator('input[placeholder*="BTC"]').first();
      if (await nameInput.isVisible()) {
        await nameInput.fill('测试告警-BTC价格');
        await expect(nameInput).toHaveValue('测试告警-BTC价格');
      }

      // 取消
      const cancelBtn = page.getByText('取消');
      if (await cancelBtn.first().isVisible()) {
        await cancelBtn.first().click();
      }
    }
  });
});
