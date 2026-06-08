import { expect, Page, test } from '@playwright/test';

const useMockApi = process.env.MOCK_API !== 'false';
test.skip(!useMockApi, 'This suite is for mocked API mode. Set MOCK_API=false for real backend tests.');

const now = new Date('2026-06-08T09:30:00+08:00').toISOString();

const json = (data: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(data),
});

async function mockApi(page: Page) {
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) {
      return route.continue();
    }
    const method = request.method().toUpperCase();
    const path = url.pathname.replace(/^\/api/, '');

    if (method === 'POST' && path === '/auth/admin/login') {
      return route.fulfill(json({
        access_token: 'mock-admin-token',
        token_type: 'bearer',
        expires_in: 3600,
        username: 'admin',
      }));
    }

    if (method === 'GET' && path === '/auth/admin/me') {
      if (!request.headers().authorization) {
        return route.fulfill(json({ detail: 'Not authenticated' }, 401));
      }
      return route.fulfill(json({ username: 'admin' }));
    }

    if (method === 'GET' && path === '/market/overview') {
      return route.fulfill(json({
        indices: [
          { name: '上证指数', price: 3200.12, change_amount: 12.34, change_percent: 0.39 },
          { name: '深证成指', price: 10234.56, change_amount: -23.45, change_percent: -0.23 },
        ],
        sentiment: { score: 62, status: '偏强', advancing: 3200, declining: 1800, unchanged: 120 },
        volume: { amount: 10234, unit: '亿', ratio: 1.15 },
        is_open: true,
        last_update: now,
      }));
    }

    if (method === 'GET' && path === '/market/short-line-indices') {
      return route.fulfill(json([
        { code: 'ZT', name: '涨停家数', price: 42, change_percent: 0, change_amount: 0 },
        { code: 'MLB', name: '最高连板', price: 5, change_percent: 0, change_amount: 0 },
      ]));
    }

    if (method === 'GET' && path === '/market/hot-concepts') {
      return route.fulfill(json([
        { rank: 1, name: '人工智能', change_percent: 2.1, inflow: 1, outflow: 1, net_inflow: 200000000 },
        { rank: 2, name: '机器人', change_percent: 1.7, inflow: 1, outflow: 1, net_inflow: -50000000 },
      ]));
    }

    if (method === 'GET' && path === '/market/ths-hot') {
      return route.fulfill(json([
        { rank: 1, code: '600000', name: '浦发银行', hot: 10, change_percent: 1.2, price: 10, reason: '银行板块活跃', tags: '金融' },
      ]));
    }

    if (method === 'GET' && path === '/market/lianban-ladder') {
      return route.fulfill(json({
        date: '2026-06-08',
        prev_date: '2026-06-05',
        levels: [
          {
            prev_level: 2,
            prev_count: 1,
            prev_items: [],
            today_level: 3,
            today_count: 1,
            today_items: [{ code: '000001', name: '平安银行', change_percent: 9.99, price: 11.01 }],
          },
        ],
      }));
    }

    if (method === 'GET' && path === '/market/hot-concept/intraday') {
      return route.fulfill(json([
        { time: '09:30', open: 1, close: 1, high: 1, low: 1, volume: 1, amount: 1 },
      ]));
    }

    if (method === 'GET' && path === '/market/hot-concept/leaders') {
      return route.fulfill(json([
        { code: '600000', name: '浦发银行', price: 10, change_percent: 1.2, amount: 100, turnover: 1.1 },
      ]));
    }

    if (method === 'GET' && path === '/market/message-stream') {
      return route.fulfill(json({
        updated_at: now,
        abnormal: { rules: [], triggered: [], near: [] },
        mergers: [],
        good_news: [],
        bad_news: [],
        cailian_news: [],
        xueqiu_news: [],
        eastmoney_news: [],
      }));
    }

    if (method === 'GET' && path === '/market/calendar') {
      return route.fulfill(json([
        { event_key: 'e1', event_date: '2026-06-08', title: '交易日', category: 'calendar', market: 'A', source: 'fixture' },
      ]));
    }

    if (method === 'GET' && path === '/strategy/list') {
      return route.fulfill(json([
        {
          id: 1,
          name: '测试策略',
          description: '用于 E2E 的示例策略',
          script_content: 'print("hello")',
          interval_seconds: 60,
          enabled: true,
          is_running: false,
          created_at: now,
          updated_at: now,
        },
      ]));
    }

    if (method === 'GET' && path === '/backtest/results') {
      return route.fulfill(json({ items: [], total: 0 }));
    }

    if (method === 'GET' && path === '/paper/accounts') {
      return route.fulfill(json({ accounts: [], total: 0 }));
    }

    if (method === 'GET' && path === '/data/status') {
      return route.fulfill(json({ status: 'ok', storage: 'postgres', scheduler: { enabled: false } }));
    }

    if (method === 'GET' && path === '/data/config') {
      return route.fulfill(json({ defaultSymbols: ['600000.SH'], defaultTimeframes: ['1d'], defaultHistoryDays: 365 }));
    }

    if (method === 'GET' && path === '/data/schedule') {
      return route.fulfill(json({
        enabled: false,
        intervalMinutes: 60,
        historyDays: 365,
        symbols: ['600000.SH'],
        timeframes: ['1d'],
      }));
    }

    if (method === 'GET' && path === '/data/table-stats') {
      return route.fulfill(json({ totalRecords: 0, totalPairs: 0, tables: [] }));
    }

    return route.fulfill(json({ status: 'ok', data: [] }));
  });
}

async function loginAsAdmin(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem('stockpro_admin_token', 'mock-admin-token'));
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test('business pages require admin token', async ({ page }) => {
  await page.goto('/market');
  await expect(page).toHaveURL(/\/admin-login/);
});

test('single api shell keeps research, market, strategy and data navigation together', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/');

  await expect(page.getByText('StockPro').first()).toBeVisible();
  await expect(page.getByText('研究工坊').first()).toBeVisible();
  await expect(page.getByText('策略工厂').first()).toBeVisible();

  await expect(page.getByRole('link', { name: /行情终端|Market/ }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /策略开发|Strategy/ }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /数据中心|Data Center/ }).first()).toBeVisible();

  await page.goto('/market');
  await expect(page).toHaveURL(/\/market/);

  await page.goto('/strategy');
  await expect(page).toHaveURL(/\/strategy/);

  await page.goto('/data');
  await expect(page).toHaveURL(/\/data/);
});

test('legacy strategy routes redirect into the new flow', async ({ page }) => {
  await loginAsAdmin(page);

  await page.goto('/strategy-dev');
  await expect(page).toHaveURL(/\/strategy\?tab=code$/);

  await page.goto('/strategy-exec');
  await expect(page).toHaveURL(/\/paper\?tab=execution$/);

  await page.goto('/pulse');
  await expect(page).toHaveURL(/\/backtest\?tab=review$/);

  await page.goto('/trading');
  await expect(page).toHaveURL(/\/paper\?tab=trading$/);
});
