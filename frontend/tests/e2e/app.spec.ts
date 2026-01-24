import { test, expect } from '@playwright/test';

const json = (data: unknown) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify(data),
});

test('NewsCalendar 页面可渲染并切换消息流 tab', async ({ page }) => {
  await page.route('**/api/v1/market/message-stream**', async (route) => {
    await route.fulfill(
      json({
        updated_at: new Date().toISOString(),
        abnormal: {
          rules: [
            { id: 'sh_sz_main_10', exchange: 'SH/SZ', threshold_pct: 10, name: '沪深主板涨跌停板' },
            { id: 'star_chinext_20', exchange: 'STAR/CHINEXT', threshold_pct: 20, name: '科创/创业涨跌停板' },
            { id: 'bj_30', exchange: 'BJ', threshold_pct: 30, name: '北交所涨跌幅限制' },
          ],
          triggered: [
            { code: '600000', name: '浦发银行', exchange: 'SH', rule_id: 'sh_sz_main_10', threshold_pct: 10, change_percent: 10.0, direction: 'UP' },
          ],
          near: [],
        },
        mergers: [
          { id: 'm1', time: '10:01', title: '并购重组示例公告', source: 'fixture', related_stocks: [{ code: '600000', name: '浦发银行' }] },
        ],
        good_news: [{ id: 'g1', time: '09:00', title: '利好示例新闻', source: 'fixture', sentiment: 'good', related_stocks: [] }],
        bad_news: [{ id: 'b1', time: '09:30', title: '利空示例新闻', source: 'fixture', sentiment: 'bad', related_stocks: [] }],
        cailian_news: [{ id: 'cl1', time: '10:00', title: '财联社示例新闻', source: '财联社', related_stocks: [] }],
        xueqiu_news: [{ id: 'xq1', time: '10:30', title: '雪球热门讨论', source: '雪球', related_stocks: [] }],
        eastmoney_news: [{ id: 'em1', time: '11:00', title: '东财快讯', source: '东方财富', related_stocks: [] }],
      })
    );
  });
  await page.route('**/api/v1/market/calendar**', async (route) => {
    await route.fulfill(
      json([
        { event_key: 'e1', event_date: new Date().toISOString().slice(0, 10), title: '月末交易日', category: '结算', market: 'A', source: 'fixture', details: null },
      ])
    );
  });

  await page.goto('/news-calendar');
  await expect(page.getByRole('heading', { name: /消息流/ })).toBeVisible();
  await expect(page.getByText('股市日历').first()).toBeVisible();
  await expect(page.getByText('触发异动')).toBeVisible();
  await expect(page.getByText('+10.00%')).toBeVisible();

  await page.getByRole('button', { name: '并购重组' }).click();
  await expect(page.getByText('并购重组示例公告')).toBeVisible();

  await page.getByRole('button', { name: '利好' }).click();
  await expect(page.getByText('利好示例新闻')).toBeVisible();

  await page.getByRole('button', { name: '利空' }).click();
  await expect(page.getByText('利空示例新闻')).toBeVisible();
});

test('Home 页面渲染正常', async ({ page }) => {
  await page.route('**/api/v1/stocks/filter**', async (route) => {
    await route.fulfill(
      json({
        stocks: [
          { code: '600000', name: '浦发银行', current_price: 10.0, change_percent: 1.2, volume: 1, market_cap: 1, is_short: false },
        ],
        total_count: 1,
        filter_time: new Date().toISOString(),
      })
    );
  });
  
  await page.goto('/');
  await expect(page.getByText('Stock Analysis Pro')).toBeVisible();
  await expect(page.getByText('Strategy Filter')).toBeVisible();
});

test('路由：Market / Analysis / AI 均可进入', async ({ page }) => {
  await page.route('**/api/v1/market/hot-concepts**', async (route) => {
    await route.fulfill(json([{ rank: 1, name: '人工智能', change_percent: 2.1, inflow: 1, outflow: 1, net_inflow: 0 }]));
  });
  await page.route('**/api/v1/market/ths-hot**', async (route) => {
    await route.fulfill(json([{ rank: 1, code: '600000', name: '浦发银行', hot: 10, change_percent: 1.2, price: 10, reason: '', tags: '' }]));
  });
  await page.route('**/api/v1/market/lianban-ladder**', async (route) => {
    await route.fulfill(json({ date: null, prev_date: null, levels: [] }));
  });
  await page.route('**/api/v1/analysis/sentiment**', async (route) => {
    await route.fulfill(json([]));
  });
  await page.route('**/api/v1/admin/task-status**', async (route) => {
    await route.fulfill(json({ is_running: false, total: 0, processed: 0, message: '' }));
  });

  await page.goto('/market');
  await expect(page.getByRole('button', { name: '热门概念板块' })).toBeVisible();

  await page.goto('/analysis');
  await expect(page.getByText('Data Processing & Analysis')).toBeVisible();

  await page.goto('/ai');
  await expect(page.getByText('AI 分析')).toBeVisible();
});

test('MarketOverview：选择概念默认龙头股，概念 Tab 可拖拽并持久化', async ({ page }) => {
  await page.route('**/api/v1/market/hot-concepts**', async (route) => {
    await route.fulfill(json([{ rank: 1, name: '人工智能', change_percent: 2.1, inflow: 1, outflow: 1, net_inflow: 0 }]));
  });
  await page.route('**/api/v1/market/hot-concept/leaders**', async (route) => {
    await route.fulfill(
      json([
        { code: '600000', name: '浦发银行', price: 10.0, change_percent: 1.2, amount: 100, turnover: 1.1 },
      ])
    );
  });
  await page.route('**/api/v1/market/hot-concept/intraday**', async (route) => {
    await route.fulfill(json([{ time: '09:30', open: 1, close: 1, high: 1, low: 1, volume: 1, amount: 1 }]));
  });
  await page.route('**/api/v1/market/ths-hot**', async (route) => {
    await route.fulfill(json([]));
  });
  await page.route('**/api/v1/market/lianban-ladder**', async (route) => {
    await route.fulfill(json({ date: null, prev_date: null, levels: [] }));
  });

  await page.goto('/market');
  await page.getByText('人工智能').first().click();

  await expect(page.getByRole('row', { name: /600000\s+浦发银行/i })).toBeVisible();

  const tabButtons = page.locator('button[title="拖动可调整顺序"]');
  await expect(tabButtons).toHaveCount(2);
  await expect(tabButtons.nth(0)).toContainText('龙头股');
  await expect(tabButtons.nth(1)).toContainText('分时K线');

  await tabButtons.nth(1).dragTo(tabButtons.nth(0));
  await expect(tabButtons.nth(0)).toContainText('分时K线');
  await expect(tabButtons.nth(1)).toContainText('龙头股');

  await page.reload();

  const tabButtons2 = page.locator('button[title="拖动可调整顺序"]');
  await expect(tabButtons2.nth(0)).toContainText('分时K线');
  await expect(tabButtons2.nth(1)).toContainText('龙头股');
});
