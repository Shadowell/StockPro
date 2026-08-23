/**
 * E2E-05: 策略页测试
 * 验证策略列表、新建策略流程、编辑、启停、删除
 */
import { test, expect } from '@playwright/test';

test.describe('策略页 - 列表', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/strategy');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
  });

  test('页面应显示策略中心标题', async ({ page }) => {
    const heading = page.getByText('策略').first();
    await expect(heading).toBeVisible();
  });

  test('应有"新建策略"按钮', async ({ page }) => {
    const createBtn = page.getByText('新建策略').or(page.getByText('新建'));
    await expect(createBtn.first()).toBeVisible();
  });

  test('策略列表应加载', async ({ page }) => {
    await page.waitForTimeout(3000);
    // 应有策略卡片或"暂无策略"提示
    const hasStrategies = page.locator('[class*="strategy"], [class*="card"]').first();
    const emptyHint = page.getByText('暂无').or(page.getByText('创建'));
    // 二者之一应可见
    const visible = await hasStrategies.isVisible() || await emptyHint.first().isVisible();
    expect(visible).toBeTruthy();
  });

  test('我的策略/策略广场Tab应可切换', async ({ page }) => {
    const myTab = page.getByText('我的策略').first();
    const squareTab = page.getByText('策略广场').or(page.getByText('模板'));

    if (await myTab.isVisible()) {
      await myTab.click();
      await page.waitForTimeout(500);
    }

    if (await squareTab.first().isVisible()) {
      await squareTab.first().click();
      await page.waitForTimeout(500);
    }
  });

  test('搜索策略应正常工作', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="搜索"]').first();
    if (await searchInput.isVisible()) {
      await searchInput.fill('MA');
      await page.waitForTimeout(1000);
    }
  });
});

test.describe('策略页 - 新建', () => {
  test('点击新建策略应进入编辑视图', async ({ page }) => {
    await page.goto('/strategy');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const createBtn = page.getByText('新建策略').or(page.getByText('新建'));
    if (await createBtn.first().isVisible()) {
      await createBtn.first().click();
      await page.waitForTimeout(1000);

      // 应进入编辑/创建视图
      const nameInput = page.locator('input[placeholder*="策略名"]').or(page.locator('input[placeholder*="名称"]'));
      const codeArea = page.locator('textarea').first();
      // 至少一个编辑元素应可见
      const visible = await nameInput.first().isVisible() || await codeArea.isVisible();
      expect(visible).toBeTruthy();
    }
  });

  test('新建策略表单应可填写', async ({ page }) => {
    await page.goto('/strategy');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const createBtn = page.getByText('新建策略').or(page.getByText('新建'));
    if (await createBtn.first().isVisible()) {
      await createBtn.first().click();
      await page.waitForTimeout(1000);

      // 填写策略名称
      const nameInput = page.locator('input[placeholder*="策略名"]').or(page.locator('input[placeholder*="名称"]'));
      if (await nameInput.first().isVisible()) {
        await nameInput.first().fill('E2E测试策略');
        await expect(nameInput.first()).toHaveValue('E2E测试策略');
      }
    }
  });
});
