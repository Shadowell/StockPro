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
          { name: '上证指数', price: 4110.81, change_amount: 4.56, change_percent: 0.11 },
          { name: '深证成指', price: 16051.32, change_amount: 197.12, change_percent: 1.24 },
          { name: '创业板指', price: 4251.42, change_amount: 59.23, change_percent: 1.41 },
          { name: '科创50', price: 1989.43, change_amount: 73.21, change_percent: 3.82 },
        ],
        sentiment: { score: 50, status: '中性', advancing: 3200, declining: 1800, unchanged: 120 },
        volume: { amount: 10234, unit: '亿', ratio: 1.15, sh_amount: 4200, sz_amount: 5800, bj_amount: 234 },
        market_breadth: { up: 3200, down: 1800, flat: 120 },
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
        { rank: 1, name: '低空经济', change_percent: 6.1, inflow: 1, outflow: 1, net_inflow: 200000000 },
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

    if (method === 'GET' && path.startsWith('/charts/daily/')) {
      return route.fulfill(json([
        { date: '2026-06-01', open: 10, high: 10.6, low: 9.8, close: 10.2, volume: 1200000 },
        { date: '2026-06-02', open: 10.2, high: 10.9, low: 10.1, close: 10.7, volume: 1500000 },
        { date: '2026-06-03', open: 10.7, high: 11.1, low: 10.5, close: 10.9, volume: 1800000 },
      ]));
    }

    if (method === 'GET' && path.startsWith('/charts/intraday/')) {
      return route.fulfill(json([
        { time: '09:30', price: 10.2, volume: 10000 },
        { time: '10:00', price: 10.5, volume: 18000 },
        { time: '14:55', price: 10.9, volume: 26000 },
      ]));
    }

    if (method === 'GET' && path.startsWith('/market/fundamentals/')) {
      return route.fulfill(json({
        symbol: '600000',
        code: '600000',
        name: '浦发银行',
        current_price: 10.9,
        change_percent: 1.2,
        pe_dynamic: 6.8,
        pb: 0.55,
        turnover_rate: 1.1,
        volume_ratio: 1.2,
        total_market_cap: 280000000000,
        updated_at: now,
      }));
    }

    if (method === 'GET' && path === '/stocks/search') {
      return route.fulfill(json([
        { code: '600000', name: '浦发银行', market: 'SH' },
        { code: '000001', name: '平安银行', market: 'SZ' },
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

test('single api shell keeps overview, research, strategy and admin navigation together', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/');

  await expect(page.getByText('StockPro AI').first()).toBeVisible();
  await expect(page.getByText('数据中台')).toHaveCount(0);
  await expect(page.getByText('研究工坊').first()).toBeVisible();
  await expect(page.getByText('策略工厂').first()).toBeVisible();

  await expect(page.getByRole('link', { name: /总览看板|Overview/ }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /市场概览|Market Overview/ }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /策略开发|Strategy Dev/ }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /管理后台|Admin Console/ }).first()).toBeVisible();

  await page.goto('/market');
  await expect(page).toHaveURL(/\/market/);

  await page.goto('/strategy');
  await expect(page).toHaveURL(/\/strategy/);

  await page.goto('/data');
  await expect(page).toHaveURL(/\/data/);

  await page.goto('/data/processing');
  await expect(page.getByText('Data Hub V1')).toHaveCount(0);
  await expect(page.getByText(/当前以/)).toHaveCount(0);
  await expect(page.getByRole('button', { name: /数据资产|Data Assets/ })).toBeVisible();
});

test('desktop shell matches the StockPro AI server console style', async ({ page }) => {
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto('/');

  const sidebar = page.getByRole('complementary');
  await expect(sidebar.getByText('StockPro AI')).toBeVisible();
  await expect(sidebar.getByText('数据中台')).toHaveCount(0);
  await expect(sidebar.getByText('研究工坊')).toBeVisible();
  await expect(sidebar.getByText('策略工厂')).toBeVisible();
  await expect(sidebar.getByText('执行风控')).toBeVisible();
  await expect(sidebar.getByText('系统管理')).toBeVisible();
  await expect(sidebar.getByRole('link', { name: /总览看板/ })).toBeVisible();
  const researchGroup = sidebar.locator('section').filter({ hasText: '研究工坊' });
  await expect(researchGroup.getByRole('link').first()).toContainText('总览看板');
  await expect(sidebar.getByRole('link', { name: /管理后台/ })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: /回测中心/ })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: /复盘中心/ })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: /模拟\/实盘交易/ })).toBeVisible();
  const riskBox = await sidebar.getByText('执行风控').boundingBox();
  const adminBox = await sidebar.getByRole('link', { name: /管理后台/ }).boundingBox();
  expect(adminBox?.y ?? 0).toBeGreaterThan(riskBox?.y ?? 0);

  const topbar = page.getByTestId('stockpro-ai-topbar');
  await expect(topbar).toBeVisible();
  const topbarLabels = ['上证指数', '深证成指', '创业板指', '科创50'];
  const topbarXs = await Promise.all(
    topbarLabels.map(async (label) => (await topbar.getByText(label).boundingBox())?.x ?? 0),
  );
  expect(topbarXs).toEqual([...topbarXs].sort((left, right) => left - right));
  await expect(page.getByText('已休市')).toBeVisible();
  await expect(page.getByText('量化交易中枢')).toHaveCount(0);
  const marketIndexSection = page.getByRole('heading', { name: '市场指数' }).locator('xpath=ancestor::section[1]');
  await expect(marketIndexSection).toBeVisible();
  const marketIndexXs = await Promise.all(
    topbarLabels.map(async (label) => (await marketIndexSection.getByText(label).boundingBox())?.x ?? 0),
  );
  expect(marketIndexXs).toEqual([...marketIndexXs].sort((left, right) => left - right));
});

test('backtest center is separated from daily market review center', async ({ page }) => {
  await loginAsAdmin(page);

  await page.goto('/backtest');
  await expect(page.getByTestId('stockpro-ai-topbar').getByRole('heading', { name: '回测中心' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '回测实例控制台' })).toBeVisible();

  await page.goto('/review');
  await expect(page.getByTestId('stockpro-ai-topbar').getByRole('heading', { name: '复盘中心' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '今日盘面复盘' })).toBeVisible();
  await expect(page.getByText('市场温度')).toBeVisible();
  await expect(page.getByRole('heading', { name: '板块轮动' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '连板梯队' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '今日复盘结论' })).toBeVisible();
  await expect(page.getByText('低空经济').first()).toBeVisible();
});

test('research overview includes the market overview and analysis board', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/research/overview');

  await expect(page.getByRole('heading', { name: '市场概览与分析' })).toBeVisible();
  await expect(page.getByText('上证指数').last()).toBeVisible();
  await expect(page.getByText('深证成指').last()).toBeVisible();
  await expect(page.getByText('开市中')).toBeVisible();
  await expect(page.getByRole('button', { name: /热门概念板块/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /同花顺热榜/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /连板梯队/ })).toBeVisible();
  await expect(page.getByText('Data Hub Freshness')).toBeVisible();
  await expect(page.getByText('板块日频数据')).toBeVisible();
  await expect(page.getByText('市场指数实时快照')).toBeVisible();
  await expect(page.getByText('全市场实时快照')).toBeVisible();
  await expect(page.getByText('短线指标实时快照')).toBeVisible();
  await expect(page.getByText('RED', { exact: true })).toHaveCount(4);
  await expect(page.getByText('低空经济').first()).toBeVisible();
  await expect(page.getByText('成分股')).toBeVisible();
});

test('dashboard shows the realtime market cockpit by default', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/');

  await expect(page.getByTestId('stockpro-ai-topbar').getByRole('heading', { name: '实时大盘' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '市场指数' })).toBeVisible();
  await expect(page.getByText('上证指数').last()).toBeVisible();
  await expect(page.getByText('强势股', { exact: true })).toBeVisible();
  await expect(page.getByText('市场情绪', { exact: true }).last()).toBeVisible();
  await expect(page.getByText('成交额', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '短线指标', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '热门板块', exact: true })).toBeVisible();
  await expect(page.getByText('查看全部')).toBeVisible();
});

test('dashboard falls back to top hot concepts when no sector is above five percent', async ({ page }) => {
  await page.route('**/api/market/hot-concepts**', (route) => route.fulfill(json([
    { rank: 1, name: '存储芯片', change_percent: 3.12, inflow: 10, outflow: 3, net_inflow: 7 },
    { rank: 2, name: '中芯国际概念', change_percent: 2.8, inflow: 8, outflow: 9, net_inflow: -1 },
  ])));
  await loginAsAdmin(page);
  await page.goto('/');

  await expect(page.getByRole('heading', { name: '热门板块 TOP5' })).toBeVisible();
  await expect(page.getByText('存储芯片')).toBeVisible();
  await expect(page.getByText('暂无热门板块数据')).toHaveCount(0);
});

test('primary pages expose usable A-share research workflow anchors', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await loginAsAdmin(page);
  await page.setViewportSize({ width: 1440, height: 960 });

  const pages = [
    { path: '/', title: '实时大盘', anchors: ['市场指数', '短线指标', '热门板块'] },
    { path: '/market', title: '市场概览', anchors: ['行情终端', 'K线图表', '个股分析'] },
    { path: '/research/overview', title: '市场概览', anchors: ['市场概览与分析', '热门概念板块', '连板梯队'] },
    { path: '/sentiment', title: '市场情绪', anchors: ['市场情绪指数', '上涨家数', '板块资金流向'] },
    { path: '/news', title: '消息中心', anchors: ['7x24 实时快讯', '异动 / 并购重组 / 利好 / 利空'] },
    { path: '/ai', title: '智能选股', anchors: ['AI 智能分析', '技术面、基本面、消息面'] },
    { path: '/factors', title: '因子研究', anchors: ['因子总数', '因子定义', '因子排名'] },
    { path: '/calendar', title: '交易日历', anchors: ['交易日历', '近期', '本月'] },
    { path: '/strategy', title: '策略开发', anchors: ['策略中心', 'A股策略约束', '100股整数手'] },
    { path: '/backtest', title: '回测中心', anchors: ['回测实例控制台', 'A股回测约束', '涨跌停 / 停牌'] },
    { path: '/review', title: '复盘中心', anchors: ['今日盘面复盘', '板块轮动', '连板梯队'] },
    { path: '/paper', title: '模拟/实盘交易', anchors: ['策略实例控制台', '实盘前置约束', 'T+1 / 100股'] },
    { path: '/monitor', title: '运行风控', anchors: ['监控中心', '运行风控检查', '涨跌停风险'] },
    { path: '/data', title: '管理后台', anchors: ['数据管理中心', '同步覆盖矩阵', 'A股数据维护面板'] },
    { path: '/data/processing', title: '管理后台', anchors: ['数据资产', '生产任务', '质量治理'] },
  ];

  for (const item of pages) {
    await page.goto(item.path);
    await expect(page.getByTestId('stockpro-ai-topbar').getByRole('heading', { name: item.title })).toBeVisible();
    for (const anchor of item.anchors) {
      await expect(page.getByText(anchor).first(), `${item.path} should show ${anchor}`).toBeVisible();
    }
  }

  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('legacy strategy routes redirect into the new flow', async ({ page }) => {
  await loginAsAdmin(page);

  await page.goto('/strategy-dev');
  await expect(page).toHaveURL(/\/strategy\?tab=code$/);

  await page.goto('/strategy-exec');
  await expect(page).toHaveURL(/\/paper\?tab=execution$/);

  await page.goto('/pulse');
  await expect(page).toHaveURL(/\/review$/);

  await page.goto('/trading');
  await expect(page).toHaveURL(/\/paper\?tab=trading$/);
});
