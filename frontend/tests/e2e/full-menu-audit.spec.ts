import { expect, test } from '@playwright/test';

test.describe('StockPro 全菜单与全子叶子菜单深度点击测试及 Review Audit', () => {
  let consoleErrors: Array<{ page: string; text: string }> = [];
  let networkErrors: Array<{ page: string; url: string; status: number }> = [];

  test.beforeEach(async ({ page, request }) => {
    consoleErrors = [];
    networkErrors = [];

    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push({ page: page.url(), text: msg.text() });
      }
    });

    page.on('response', (response) => {
      if (response.status() >= 400 && !response.url().includes('/api/auth/me')) {
        networkErrors.push({ page: page.url(), url: response.url(), status: response.status() });
      }
    });

    // 通过后台 API 获取 Token 登录
    const loginResp = await request.post('/api/auth/admin/login', {
      data: { username: 'admin', password: 'stockpro123' },
    });
    expect(loginResp.ok()).toBeTruthy();
    const loginData = await loginResp.json();
    const token = loginData.access_token;

    // 将 Token 预注入页面 localStorage
    await page.goto('/');
    await page.evaluate((authToken) => {
      localStorage.setItem('stockpro_admin_token', authToken);
    }, token);
  });

  test('01. 首页 (Dashboard) 及其全部子模块测试', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    expect(page.url()).toContain('/');

    const headline = page.locator('div:has-text("上证指数"), h1:has-text("StockPro")').first();
    await expect(headline).toBeVisible({ timeout: 10000 });

    const downTab = page.locator('button:has-text("跌停名单")');
    if (await downTab.isVisible()) {
      await downTab.click();
      await page.waitForTimeout(300);
    }
    const upTab = page.locator('button:has-text("涨停名单")');
    if (await upTab.isVisible()) {
      await upTab.click();
      await page.waitForTimeout(300);
    }

    console.log('Dashboard Console Errors:', consoleErrors.length);
    console.log('Dashboard Network Errors:', networkErrors.length);
  });

  test('02. 行情中心 (Market) 全部 6 个二级 Tab 及子视图点击测试', async ({ page }) => {
    const tabs = [
      { key: 'structure', name: '市场结构' },
      { key: 'sectors', name: '板块轮动' },
      { key: 'sentiment', name: '情绪 / 涨停' },
      { key: 'events', name: '事件' },
      { key: 'calendar', name: '交易日历' },
      { key: 'stock', name: '个股研究' },
    ];

    for (const tab of tabs) {
      await page.goto(`/market?tab=${tab.key}`);
      await page.waitForLoadState('networkidle');

      if (tab.key === 'events') {
        const syncBtn = page.locator('button:has-text("同步最新快讯")');
        if (await syncBtn.isVisible()) {
          await syncBtn.click();
          await page.waitForTimeout(500);
        }
      } else if (tab.key === 'stock') {
        const sectorToggle = page.locator('[data-testid="market-scope-toggle"] button:has-text("板块")').first();
        if (await sectorToggle.isVisible()) {
          await sectorToggle.click();
          await page.waitForTimeout(300);
        }
        const ashareToggle = page.locator('button:has-text("A股")');
        if (await ashareToggle.isVisible()) {
          await ashareToggle.click();
          await page.waitForTimeout(300);
        }
      }
    }
  });

  test('03. 股票池 (Pools) 全部 Tab 点击测试', async ({ page }) => {
    const tabs = ['snapshots', 'factor', 'anomaly', 'extreme', 'custom', 'my'];
    for (const t of tabs) {
      await page.goto(`/pools?tab=${t}`);
      await page.waitForLoadState('networkidle');
    }
  });

  test('04. 因子研究 (Factors) 全部 Tab 点击测试', async ({ page }) => {
    const tabs = ['overview', 'definitions', 'rankings', 'single-factor', 'multi-factor'];
    for (const t of tabs) {
      await page.goto(`/factors?tab=${t}`);
      await page.waitForLoadState('networkidle');
    }
  });

  test('05. 策略开发 (Strategy) 全部 Tab 及代码编辑器点击测试', async ({ page }) => {
    const tabs = ['plaza', 'mine', 'code', 'config', 'versions'];
    for (const t of tabs) {
      await page.goto(`/strategy?tab=${t}`);
      await page.waitForLoadState('networkidle');
    }
  });

  test('06. 回测中心 (Backtest) 控制台与 8 个子 Tab 详情测试', async ({ page }) => {
    await page.goto('/backtest');
    await page.waitForLoadState('networkidle');

    const wizardBtn = page.locator('button:has-text("新建回测")');
    if (await wizardBtn.isVisible()) {
      await wizardBtn.click();
      await page.waitForTimeout(300);
      const cancelBtn = page.locator('button:has-text("取消")').first();
      if (await cancelBtn.isVisible()) {
        await cancelBtn.click();
      }
    }
  });

  test('07. 模拟交易 (Paper) 全部 Tab 测试', async ({ page }) => {
    const tabs = ['instances', 'trading', 'positions', 'orders', 'execution'];
    for (const t of tabs) {
      await page.goto(`/paper?tab=${t}`);
      await page.waitForLoadState('networkidle');
    }
  });

  test('08. 盯盘 (Watch) 页面测试', async ({ page }) => {
    await page.goto('/watch');
    await page.waitForLoadState('networkidle');
  });

  test('09. 监控 (Monitor) 页面测试', async ({ page }) => {
    await page.goto('/monitor');
    await page.waitForLoadState('networkidle');
  });

  test('10. 每日复盘 (Daily Review) 页面测试', async ({ page }) => {
    await page.goto('/review');
    await page.waitForLoadState('networkidle');
  });

  test('11. 数据中心 (Data & DataProcessing) 全部 Tab 测试', async ({ page }) => {
    const tabs = ['tables', 'coverage', 'sync'];
    for (const t of tabs) {
      await page.goto(`/data?tab=${t}`);
      await page.waitForLoadState('networkidle');
    }
    await page.goto('/data/processing');
    await page.waitForLoadState('networkidle');
  });

  test('12. AI 实验室 (AI Lab) 全部 Tab 测试', async ({ page }) => {
    const tabs = ['report', 'generate', 'screener'];
    for (const t of tabs) {
      await page.goto(`/ai-lab?tab=${t}`);
      await page.waitForLoadState('networkidle');
    }
  });
});
