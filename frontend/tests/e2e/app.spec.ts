import { test, expect, Page } from '@playwright/test';

const useMockApi = process.env.MOCK_API !== 'false';
test.skip(!useMockApi, 'This suite is for mocked API mode. Set MOCK_API=true.');

const json = (data: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(data),
});

const now = new Date('2026-04-01T09:30:00+08:00').toISOString();

const marketOverviewFixture = {
  indices: [
    { name: '上证指数', price: 3200.12, change_amount: 12.34, change_percent: 0.39 },
    { name: '深证成指', price: 10234.56, change_amount: -23.45, change_percent: -0.23 },
  ],
  sentiment: {
    score: 62,
    status: '偏强',
    advancing: 3200,
    declining: 1800,
    unchanged: 120,
  },
  volume: {
    amount: 10234,
    unit: '亿',
    ratio: 1.15,
    sh_amount: 5123,
    sz_amount: 4987,
    bj_amount: 124,
  },
  is_open: true,
  last_update: now,
};

const hotConceptsFixture = [
  { rank: 1, name: '人工智能', change_percent: 2.1, inflow: 1, outflow: 1, net_inflow: 200000000 },
  { rank: 2, name: '机器人', change_percent: 1.7, inflow: 1, outflow: 1, net_inflow: -50000000 },
];

const thsHotFixture = [
  { rank: 1, code: '600000', name: '浦发银行', hot: 10, change_percent: 1.2, price: 10, reason: '银行板块活跃', tags: '金融' },
  { rank: 2, code: '000001', name: '平安银行', hot: 9, change_percent: 0.8, price: 11, reason: '成交放量', tags: '金融' },
];

const lianbanFixture = {
  date: '2026-04-01',
  prev_date: '2026-03-31',
  levels: [
    {
      prev_level: 2,
      prev_count: 1,
      prev_items: [{ code: '000001', name: '平安银行', change_percent: 9.99, price: 11.01 }],
      today_level: 3,
      today_count: 1,
      today_items: [{ code: '000001', name: '平安银行', change_percent: 9.99, price: 11.01 }],
    },
  ],
};

const messageStreamFixture = {
  updated_at: now,
  abnormal: {
    rules: [
      { id: 'sh_sz_main_10', exchange: 'SH/SZ', threshold_pct: 10, name: '沪深主板涨跌停板' },
      { id: 'star_chinext_20', exchange: 'STAR/CHINEXT', threshold_pct: 20, name: '科创/创业涨跌停板' },
      { id: 'bj_30', exchange: 'BJ', threshold_pct: 30, name: '北交所涨跌幅限制' },
    ],
    triggered: [
      {
        code: '600000',
        name: '浦发银行',
        exchange: 'SH',
        rule_id: 'sh_sz_main_10',
        threshold_pct: 10,
        change_percent: 10.0,
        direction: 'UP',
      },
    ],
    near: [],
  },
  mergers: [{ id: 'm1', time: '10:01', title: '并购重组示例公告', source: 'fixture', related_stocks: [] }],
  good_news: [{ id: 'g1', time: '09:00', title: '利好示例新闻', source: 'fixture', sentiment: 'good', related_stocks: [] }],
  bad_news: [{ id: 'b1', time: '09:30', title: '利空示例新闻', source: 'fixture', sentiment: 'bad', related_stocks: [] }],
  cailian_news: [{ id: 'cl1', time: '10:00', title: '财联社示例新闻', source: '财联社', related_stocks: [] }],
  xueqiu_news: [{ id: 'xq1', time: '10:30', title: '雪球热门讨论', source: '雪球', related_stocks: [] }],
  eastmoney_news: [{ id: 'em1', time: '11:00', title: '东财快讯', source: '东方财富', related_stocks: [] }],
};

const strategyFixture = [
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
];

const dailySectorStatsFixture = [
  {
    date: '2026-04-01',
    sectors: [
      { name: '人工智能', change_percent: 4.2, leader_stock: '中科曙光', rank: 1 },
      { name: '机器人', change_percent: 3.7, leader_stock: '鸣志电器', rank: 2 },
    ],
  },
  {
    date: '2026-03-31',
    sectors: [{ name: '算力', change_percent: 3.1, leader_stock: '浪潮信息', rank: 1 }],
  },
];

async function mockApi(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method().toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, '');

    if (method === 'GET' && path === '/market/overview') return route.fulfill(json(marketOverviewFixture));
    if (method === 'GET' && path === '/admin/task-status') {
      return route.fulfill(json({ is_running: false, total: 0, processed: 0, message: '', task_id: null }));
    }
    if (method === 'GET' && path === '/stocks/filter') {
      return route.fulfill(
        json({
          stocks: [
            { code: '600000', name: '浦发银行', current_price: 10.0, change_percent: 1.2, volume: 1, market_cap: 1, is_short: false },
          ],
          total_count: 1,
          filter_time: now,
        })
      );
    }
    if (method === 'GET' && path === '/sectors/hot') {
      return route.fulfill(json([{ id: '1', name: '人工智能', change_percent: 6.1, up_count: 22, down_count: 3, leader_stock: '中科曙光' }]));
    }
    if (method === 'GET' && path === '/market/short-line-indices') {
      return route.fulfill(
        json([
          { code: 'ZT', name: '涨停家数', price: 42, change_percent: 0, change_amount: 0 },
          { code: 'MLB', name: '最高连板', price: 5, change_percent: 0, change_amount: 0 },
        ])
      );
    }
    if (method === 'GET' && path === '/market/hot-concepts') return route.fulfill(json(hotConceptsFixture));
    if (method === 'GET' && path === '/market/ths-hot') return route.fulfill(json(thsHotFixture));
    if (method === 'GET' && path === '/market/lianban-ladder') return route.fulfill(json(lianbanFixture));
    if (method === 'GET' && path === '/market/hot-concept/intraday') {
      return route.fulfill(json([{ time: '09:30', open: 1, close: 1, high: 1, low: 1, volume: 1, amount: 1 }]));
    }
    if (method === 'GET' && path === '/market/hot-concept/leaders') {
      return route.fulfill(json([{ code: '600000', name: '浦发银行', price: 10.0, change_percent: 1.2, amount: 100, turnover: 1.1 }]));
    }
    if (method === 'GET' && path === '/analysis/sentiment') return route.fulfill(json([]));
    if (method === 'GET' && path.startsWith('/charts/daily/')) {
      return route.fulfill(
        json([
          { date: '2026-03-31', open: 9.8, close: 10.0, high: 10.1, low: 9.7, volume: 100000 },
          { date: '2026-04-01', open: 10.0, close: 10.2, high: 10.3, low: 9.9, volume: 120000 },
        ])
      );
    }
    if (method === 'GET' && path.startsWith('/charts/intraday/')) {
      return route.fulfill(
        json([
          { time: '09:30', price: 10.0, volume: 1000, amount: 10000, pre_close: 9.9, trade_date: '2026-04-01' },
          { time: '09:31', price: 10.1, volume: 1500, amount: 15150 },
        ])
      );
    }
    if (method === 'GET' && path.startsWith('/market/fundamentals/')) {
      return route.fulfill(
        json({
          code: '600000',
          name: '浦发银行',
          current_price: 10.2,
          change_percent: 1.2,
          total_market_cap: 100000000000,
          float_market_cap: 80000000000,
          turnover_rate: 1.1,
          volume_ratio: 1.2,
          pe_dynamic: 10.5,
          pb: 1.1,
          amplitude: 2.3,
          updated_at: now,
        })
      );
    }
    if (method === 'GET' && path === '/market/message-stream') return route.fulfill(json(messageStreamFixture));
    if (method === 'POST' && path === '/market/message-stream/sync') return route.fulfill(json({ status: 'success', count: 1 }));
    if (method === 'GET' && path === '/market/calendar') {
      return route.fulfill(
        json([{ event_key: 'e1', event_date: '2026-04-01', title: '月末交易日', category: '结算', market: 'A', source: 'fixture', details: null }])
      );
    }
    if (method === 'GET' && path === '/stocks/search') {
      return route.fulfill(json([{ code: '600000', name: '浦发银行', price: 10.0, change_percent: 1.2 }]));
    }
    if (method === 'GET' && path === '/strategy/list') return route.fulfill(json(strategyFixture));
    if (method === 'GET' && /^\/strategy\/\d+\/latest-result$/.test(path)) return route.fulfill(json({ message: 'no result' }));
    if (method === 'GET' && path === '/database/tables') {
      return route.fulfill(json([{ name: 'stock_history', columns: ['code', 'date', 'close'], rowCount: 2 }]));
    }
    if (method === 'GET' && path.startsWith('/database/table/')) {
      return route.fulfill(json({ columns: ['code', 'date', 'close'], rows: [{ code: '600000', date: '2026-04-01', close: 10.2 }], rowCount: 1 }));
    }
    if (method === 'POST' && path === '/database/query') {
      return route.fulfill(json({ columns: ['code', 'date', 'close'], rows: [{ code: '600000', date: '2026-04-01', close: 10.2 }], rowCount: 1 }));
    }
    if (method === 'GET' && path === '/batch-import/status') {
      return route.fulfill(json({ is_running: false, progress: 0, task_id: null, total: 0, processed: 0 }));
    }
    if (method === 'GET' && path === '/batch-import/ma-data/stats') {
      return route.fulfill(json({ success: true, stats: { stock_count: 10, record_count: 1000, start_date: '2026-01-01', end_date: '2026-04-01' } }));
    }
    if (method === 'GET' && path === '/factors/definitions') {
      return route.fulfill(
        json({
          status: 'success',
          data: [
            {
              id: 1,
              factor_code: 'PE_TTM',
              factor_name: '市盈率(TTM)',
              category: '估值因子',
              subcategory: null,
              description: '估值指标',
              formula: null,
              data_source: 'fixture',
              update_frequency: 'daily',
              unit: null,
            },
          ],
        })
      );
    }
    if (method === 'GET' && path === '/factors/stats') {
      return route.fulfill(json({ status: 'success', data: { factor_count: 1, data_count: 100, latest_date: '2026-04-01', stock_count: 1, category_stats: { '估值因子': 1 } } }));
    }
    if (method === 'GET' && path === '/market/pulse/daily-stats') return route.fulfill(json(dailySectorStatsFixture));

    if (method === 'POST') return route.fulfill(json({ status: 'success' }));
    if (method === 'PUT') return route.fulfill(json({ status: 'success' }));
    if (method === 'DELETE') return route.fulfill(json({ success: true }));
    return route.fulfill(json({}, 200));
  });
}

test.beforeEach(async ({ page }) => {
  if (useMockApi) {
    await mockApi(page);
  }
});

test('所有页面路由可访问并完成基础渲染', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  const routes = [
    { path: '/', title: '实时大盘', marker: '短线指标' },
    { path: '/market', title: '市场概览与分析', marker: '热门概念板块' },
    { path: '/sentiment', title: '市场情绪分析', marker: '市场情绪指数' },
    { path: '/ai', title: '智能选股', marker: '一键智能分析' },
    { path: '/news', title: '消息流', marker: '7x24 实时快讯' },
    { path: '/news-calendar', title: '消息流', marker: '7x24 实时快讯' },
    { path: '/calendar', title: '交易日历', marker: '交易日历' },
    { path: '/strategy-dev', title: '策略开发', marker: 'Python 策略编辑器' },
    { path: '/strategy-exec', title: '实时策略盯盘', marker: '筛选结果汇总' },
    { path: '/factors', title: '因子库', marker: '因子总数' },
    { path: '/pulse', title: '复盘中心', marker: '每日显示' },
    { path: '/trading', title: '模拟/实盘交易', marker: '账户概览' },
  ] as const;

  for (const route of routes) {
    await test.step(`访问 ${route.path}`, async () => {
      await page.goto(route.path, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('header h2')).toContainText(route.title, { timeout: 15000 });
      await expect(page.getByText(route.marker).first()).toBeVisible({ timeout: 15000 });
    });
  }

  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('消息流页面可切换所有 tab', async ({ page }) => {
  await page.goto('/news?tab=abnormal');
  await expect(page.getByText('触发异动')).toBeVisible();
  await expect(page.getByText('+10.00%')).toBeVisible();

  await page.getByRole('button', { name: '并购重组' }).click();
  await expect(page.getByText('并购重组示例公告')).toBeVisible();

  await page.getByRole('button', { name: '利好' }).click();
  await expect(page.getByText('利好示例新闻')).toBeVisible();

  await page.getByRole('button', { name: '利空' }).click();
  await expect(page.getByText('利空示例新闻')).toBeVisible();

  await page.getByRole('button', { name: '财联社' }).click();
  await expect(page.getByText('财联社示例新闻')).toBeVisible();

  await page.getByRole('button', { name: '雪球' }).click();
  await expect(page.getByText('雪球热门讨论')).toBeVisible();

  await page.getByRole('button', { name: '东财' }).click();
  await expect(page.getByText('东财快讯')).toBeVisible();
});
