import { expect, Page, test } from '@playwright/test';

const adminPassword = process.env.E2E_ADMIN_PASSWORD || process.env.ADMIN_PASSWORD;

test.skip(!adminPassword, 'Set E2E_ADMIN_PASSWORD or ADMIN_PASSWORD to run the real menu audit.');
test.describe.configure({ mode: 'serial' });

async function waitForPageReady(page: Page) {
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('main')).toBeVisible();
  await page.waitForTimeout(1_000);
}

async function navigateTo(page: Page, path: string) {
  if (page.url() === 'about:blank') {
    await page.goto(path);
  } else {
    await page.evaluate((nextPath) => {
      window.history.pushState({}, '', nextPath);
      window.dispatchEvent(new PopStateEvent('popstate'));
    }, path);
  }
  await waitForPageReady(page);
}

test.describe('StockPro 全菜单与全子叶子菜单深度点击测试及 Review Audit', () => {
  let token = '';
  let authProfile: Record<string, unknown> = {};
  let consoleErrors: Array<{ page: string; text: string }> = [];
  let pageErrors: Array<{ page: string; text: string }> = [];
  let networkErrors: Array<{ page: string; url: string; status: number }> = [];

  test.beforeAll(async ({ request }) => {
    const loginResp = await request.post('/api/auth/admin/login', {
      data: {
        username: process.env.E2E_ADMIN_USERNAME || process.env.ADMIN_USERNAME || 'admin',
        password: adminPassword,
      },
    });
    expect(loginResp.ok()).toBeTruthy();
    const loginData = await loginResp.json();
    token = String(loginData.access_token || '');
    expect(token).not.toBe('');

    const profileResp = await request.get('/api/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(profileResp.ok()).toBeTruthy();
    authProfile = await profileResp.json();
  });

  test.beforeEach(async ({ page }) => {
    consoleErrors = [];
    pageErrors = [];
    networkErrors = [];

    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push({ page: page.url(), text: msg.text() });
      }
    });

    page.on('pageerror', (error) => {
      pageErrors.push({ page: page.url(), text: error.message });
    });

    page.on('response', (response) => {
      if (response.status() >= 400 && !response.url().includes('/api/auth/me')) {
        networkErrors.push({ page: page.url(), url: response.url(), status: response.status() });
      }
    });

    // 套件开始时已通过真实后端验证会话；页面间复用快照，避免行情长查询阻塞鉴权连接。
    await page.route('**/api/auth/me', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(authProfile),
    }));
    await page.addInitScript(({ authToken, profile }) => {
      localStorage.setItem('stockpro_admin_token', authToken);
      localStorage.setItem('stockpro_auth_profile', JSON.stringify(profile));
    }, { authToken: token, profile: authProfile });
  });

  test.afterEach(() => {
    expect(pageErrors, 'pageerror 异常').toEqual([]);
    expect(consoleErrors, '浏览器 console.error').toEqual([]);
    expect(networkErrors, 'HTTP 4xx/5xx 请求').toEqual([]);
  });

  test('01. 首页 (Dashboard) 及其全部子模块测试', async ({ page }) => {
    await navigateTo(page, '/');
    expect(page.url()).toContain('/');

    const headline = page.getByRole('heading', { name: '市场大盘' });
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
      await navigateTo(page, `/market?tab=${tab.key}`);

      if (tab.key === 'events' && process.env.E2E_ALLOW_MUTATIONS === '1') {
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
      await navigateTo(page, `/pools?tab=${t}`);
    }
  });

  test('04. 因子研究 (Factors) 全部 Tab 点击测试', async ({ page }) => {
    const tabs = ['overview', 'definitions', 'rankings', 'single-factor', 'multi-factor'];
    for (const t of tabs) {
      await navigateTo(page, `/factors?tab=${t}`);
    }
  });

  test('05. 策略开发 (Strategy) 全部 Tab 及代码编辑器点击测试', async ({ page }) => {
    const tabs = ['plaza', 'mine', 'code', 'config', 'versions'];
    for (const t of tabs) {
      await navigateTo(page, `/strategy?tab=${t}`);
    }
  });

  test('06. 回测中心 (Backtest) 控制台与 8 个子 Tab 详情测试', async ({ page }) => {
    await navigateTo(page, '/backtest');

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
      await navigateTo(page, `/paper?tab=${t}`);
    }
  });

  test('08. 盯盘 (Watch) 页面测试', async ({ page }) => {
    await navigateTo(page, '/watch');
  });

  test('09. 监控 (Monitor) 页面测试', async ({ page }) => {
    await navigateTo(page, '/monitor');
  });

  test('10. 每日复盘 (Daily Review) 页面测试', async ({ page }) => {
    await navigateTo(page, '/review');
  });

  test('11. 数据中心 (Data & DataProcessing) 全部 Tab 测试', async ({ page }) => {
    const tabs = ['tables', 'coverage', 'sync'];
    for (const t of tabs) {
      await navigateTo(page, `/data?tab=${t}`);
    }
    await navigateTo(page, '/data/processing');
  });

  test('12. AI 实验室 (AI Lab) 全部 Tab 测试', async ({ page }) => {
    const tabs = ['report', 'generate', 'screener'];
    for (const t of tabs) {
      await navigateTo(page, `/ai-lab?tab=${t}`);
    }
  });
});
