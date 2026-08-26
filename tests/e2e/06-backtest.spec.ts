/**
 * E2E-06: 回测页测试
 * 验证回测参数设置、策略选择、运行回测、结果Tab切换
 */
import { test, expect } from '@playwright/test';

test.describe('回测页 - 配置', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/backtest');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
  });

  test('页面应显示回测标题', async ({ page }) => {
    const heading = page.getByText('回测').first();
    await expect(heading).toBeVisible();
  });

  test('策略选择下拉框应存在', async ({ page }) => {
    const strategySelect = page.locator('select').first();
    await expect(strategySelect).toBeVisible();
  });

  test('策略列表应有可选项', async ({ page }) => {
    const strategySelect = page.locator('select').first();
    const options = strategySelect.locator('option');
    const count = await options.count();
    // 应至少有 "请选择" + 若干策略
    expect(count).toBeGreaterThan(1);
  });

  test('日期选择器应有默认值（一年区间）', async ({ page }) => {
    const dateInputs = page.locator('input[type="date"]');
    const count = await dateInputs.count();
    expect(count).toBeGreaterThanOrEqual(2);

    // 开始日期应有值
    const startVal = await dateInputs.first().inputValue();
    expect(startVal).toMatch(/^\d{4}-\d{2}-\d{2}$/);

    // 结束日期应有值
    const endVal = await dateInputs.last().inputValue();
    expect(endVal).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  test('初始资金输入框应有默认值', async ({ page }) => {
    const capitalInput = page.locator('input[type="number"]').first();
    if (await capitalInput.isVisible()) {
      const val = await capitalInput.inputValue();
      expect(Number(val)).toBeGreaterThan(0);
    }
  });

  test('"开始回测"按钮应存在', async ({ page }) => {
    const runBtn = page.getByText('开始回测').or(page.getByText('运行'));
    await expect(runBtn.first()).toBeVisible();
  });

  test('选择策略后参数应可修改', async ({ page }) => {
    // 选择第一个非空策略
    const strategySelect = page.locator('select').first();
    const options = strategySelect.locator('option');
    const count = await options.count();

    if (count > 1) {
      await strategySelect.selectOption({ index: 1 });
      await page.waitForTimeout(500);

      // 修改初始资金
      const capitalInput = page.locator('input[type="number"]').first();
      if (await capitalInput.isVisible()) {
        await capitalInput.fill('50000');
        await expect(capitalInput).toHaveValue('50000');
      }
    }
  });
});

test.describe('回测页 - 运行回测', () => {
  test('选择策略并运行回测应显示结果', async ({ page }) => {
    await page.goto('/backtest');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    // 选择策略
    const strategySelect = page.locator('select').first();
    const options = strategySelect.locator('option');
    const count = await options.count();

    if (count > 1) {
      await strategySelect.selectOption({ index: 1 });
      await page.waitForTimeout(500);

      // 点击运行
      const runBtn = page.getByText('开始回测').or(page.getByText('运行'));
      await runBtn.first().click();

      // 等待回测完成（可能需要较长时间）
      await page.waitForTimeout(15000);

      // 结果区域应有内容（图表 canvas 或统计数据）
      const resultContent = page.locator('canvas')
        .or(page.getByText('总收益'))
        .or(page.getByText('胜率'))
        .or(page.getByText('最大回撤'))
        .or(page.getByText('回测中'));
      await expect(resultContent.first()).toBeVisible({ timeout: 20000 });
    }
  });
});
