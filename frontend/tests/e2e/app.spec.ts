import { test, expect, Page } from '@playwright/test';

const json = (data: unknown) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify(data),
});

const strategy = {
  id: 1,
  name: '双均线动量策略',
  description: 'Backtrader 多股组合策略',
  script_content: `import backtrader as bt

class DualMovingAverageStrategy(bt.Strategy):
    params = dict(fast_period=5, slow_period=20)

    def next(self):
        pass
`,
  interval_seconds: 60,
  enabled: true,
  is_running: false,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

async function mockCoreV2Routes(page: Page) {
  await page.route('**/api/v2/admin/task-status**', async (route) => {
    await route.fulfill(json({ is_running: false, total: 0, processed: 0, message: '' }));
  });
  await page.route('**/api/v2/market/overview**', async (route) => {
    await route.fulfill(
      json({
        indices: [
          { name: '上证指数', code: '000001', price: 3188.22, change_amount: 12.3, change_percent: 0.39 },
          { name: '深证成指', code: '399001', price: 9988.7, change_amount: -21.1, change_percent: -0.21 },
        ],
        hot_sectors: [{ name: '人工智能', change_percent: 4.2, up_count: 52, down_count: 8, leader_stock: '浦发银行' }],
        sentiment: { score: 72, status: '偏强', advancing: 2840, declining: 1800, unchanged: 190 },
        volume: { amount: 8600, unit: '亿', ratio: 1.18 },
        market_breadth: { up: 2840, down: 1800, flat: 190 },
        is_open: true,
        updated_at: new Date().toISOString(),
      })
    );
  });
  await page.route('**/api/v2/market/hot-concepts**', async (route) => {
    await route.fulfill(json([{ rank: 1, name: '人工智能', change_percent: 4.2, inflow: 12000, outflow: 6000, net_inflow: 6000 }]));
  });
  await page.route('**/api/v2/market/ths-hot**', async (route) => {
    await route.fulfill(json([{ rank: 1, code: 'SH_600000', name: '浦发银行', hot: 9800, change_percent: 6.1, price: 10.6, reason: '板块龙头', tags: '人工智能' }]));
  });
  await page.route('**/api/v2/market/hot-concept/leaders**', async (route) => {
    await route.fulfill(json([{ code: 'SH_600000', name: '浦发银行', price: 10.6, change_percent: 6.1, amount: 120000000, turnover: 3.2 }]));
  });
  await page.route('**/api/v2/market/hot-concept/intraday**', async (route) => {
    await route.fulfill(json([{ time: '09:30', open: 10, close: 10.6, high: 10.8, low: 9.9, volume: 1000000, amount: 10600000 }]));
  });
  await page.route('**/api/v2/market/lianban-ladder**', async (route) => {
    await route.fulfill(
      json({
        date: '20260604',
        prev_date: '20260603',
        levels: [
          {
            prev_level: 1,
            prev_count: 2,
            prev_items: [],
            today_level: 2,
            today_count: 1,
            today_items: [{ code: 'SH_600000', name: '浦发银行', price: 10.6, change_percent: 10.01, reason: '人工智能' }],
          },
        ],
      })
    );
  });
  await page.route('**/api/v2/market/message-stream**', async (route) => {
    await route.fulfill(
      json({
        updated_at: new Date().toISOString(),
        abnormal: {
          rules: [{ id: 'main-up', exchange: 'SH', threshold_pct: 9.8, name: '主板涨停异动' }],
          triggered: [{ code: 'SH_600000', name: '浦发银行', exchange: 'SH', rule_id: 'main-up', threshold_pct: 9.8, change_percent: 10.01, direction: 'UP' }],
          near: [],
        },
        mergers: [{ id: 'm1', time: '09:45', title: '并购重组预案披露', source: '公告', related_stocks: [{ code: 'SH_600000', name: '浦发银行' }] }],
        good_news: [{ id: 'g1', time: '10:01', title: '人工智能板块活跃', source: '财联社', related_stocks: [] }],
        bad_news: [],
        cailian_news: [{ id: 'c1', time: '10:08', title: '财联社快讯样例', source: '财联社', related_stocks: [] }],
        xueqiu_news: [],
        eastmoney_news: [],
      })
    );
  });
  await page.route('**/api/v2/market/short-line-indices**', async (route) => {
    await route.fulfill(json([{ code: 'LIMIT_UP', name: '涨停家数', price: 68, change_percent: 12.2, change_amount: 8 }]));
  });
  await page.route('**/api/v2/sectors/hot**', async (route) => {
    await route.fulfill(json([{ name: '人工智能', change_percent: 4.2, up_count: 52, down_count: 8, leader_stock: '浦发银行' }]));
  });
  await page.route('**/api/v2/charts/daily/**', async (route) => {
    await route.fulfill(json([{ date: '2026-01-08', open: 10, close: 10.6, high: 10.8, low: 9.9, volume: 1000000 }]));
  });
  await page.route('**/api/v2/charts/intraday/**', async (route) => {
    await route.fulfill(json([{ time: '09:30', price: 10.6, volume: 10000, amount: 106000 }]));
  });
  await page.route('**/api/v2/market/fundamentals/**', async (route) => {
    await route.fulfill(json({ code: 'SH_600000', name: '浦发银行', current_price: 10.6, change_percent: 6.1 }));
  });
  await page.route('**/api/v2/strategy/list**', async (route) => {
    await route.fulfill(json([strategy]));
  });
  await page.route('**/api/v2/strategy/auto-develop**', async (route) => {
    await route.fulfill(
      json({
        success: true,
        id: 99,
        generated_plan: 'A股自动开发计划：首板突破，多股组合，进入回测和模拟盘观察。',
        symbols: ['SH_600000', 'SZ_000001'],
        strategy: {
          ...strategy,
          id: 99,
          name: '本地生成-首板突破',
          description: '自动生成 Backtrader 策略',
          script_content: 'import backtrader as bt\\n\\nclass GeneratedAshareStrategy(bt.Strategy):\\n    def next(self):\\n        pass\\n',
        },
      })
    );
  });
  await page.route('**/api/v2/strategy/99', async (route) => {
    if (route.request().method() === 'PUT') {
      await route.fulfill(json({ ...strategy, id: 99, name: '本地生成-首板突破' }));
    } else {
      await route.continue();
    }
  });
  await page.route('**/api/v2/backtest/run**', async (route) => {
    await route.fulfill(
      json({
        engine: 'backtrader',
        status: 'completed',
        backtest_id: 7,
        strategy_id: 1,
        strategy_name: '双均线动量策略',
        symbols: ['SH_600000', 'SZ_000001'],
        symbol_names: { SH_600000: '浦发银行', SZ_000001: '平安银行' },
        start_date: '2026-01-01',
        end_date: '2026-01-08',
        initial_capital: 100000,
        final_capital: 112500,
        total_return: 12.5,
        annual_return: 42.1,
        max_drawdown: 3.2,
        sharpe: 1.8,
        win_rate: 66,
        total_trades: 4,
        equity_curve: [
          { date: '2026-01-01', equity: 100000 },
          { date: '2026-01-08', equity: 112500 },
        ],
        trades: [
          { date: '2026-01-02', symbol: 'SH_600000', name: '浦发银行', side: 'buy', price: 10, quantity: 3000, amount: 30000, fee: 9, pnl: 0, reason: 'strategy_entry' },
          { date: '2026-01-08', symbol: 'SH_600000', name: '浦发银行', side: 'sell', price: 12.5, quantity: 3000, amount: 37500, fee: 48, pnl: 7452, reason: 'strategy_exit' },
        ],
        created_at: new Date().toISOString(),
      })
    );
  });
  await page.route('**/api/v2/backtest/results**', async (route) => {
    await route.fulfill(json({ items: [], total: 0 }));
  });
  await page.route('**/api/v2/paper/accounts**', async (route) => {
    await route.fulfill(
      json({
        accounts: [
          {
            account_id: 3,
            strategy_id: 1,
            strategy_name: '双均线动量策略',
            name: '双均线动量策略 模拟盘',
            initial_capital: 100000,
            cash: 68000,
            equity: 103200,
            status: 'running',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        total: 1,
      })
    );
  });
  await page.route('**/api/v2/paper/run**', async (route) => {
    await route.fulfill(
      json({
        status: 'running',
        account_id: 8,
        strategy_id: 1,
        strategy_name: '双均线动量策略',
        name: '双均线动量策略 模拟盘',
        initial_capital: 100000,
        cash: 69800,
        equity: 101800,
        orders: [{ symbol: 'SH_600000', name: '浦发银行', side: 'buy', price: 10, quantity: 3000, amount: 30000, fee: 9, status: 'filled', reason: 'strategy_signal' }],
        positions: [{ symbol: 'SH_600000', name: '浦发银行', quantity: 3000, avg_price: 10, last_price: 10.6, market_value: 31800, pnl: 1800, pnl_pct: 6 }],
        equity_curve: [{ time: new Date().toISOString(), equity: 101800 }],
        events: [{ level: 'info', message: '模拟盘已启动', created_at: new Date().toISOString() }],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      })
    );
  });
  await page.route('**/api/v2/paper/8/refresh**', async (route) => {
    await route.fulfill(json({ status: 'running', account_id: 8, cash: 69800, equity: 102400, positions: [], orders: [], equity_curve: [{ time: new Date().toISOString(), equity: 102400 }], events: [{ level: 'info', message: '手动刷新完成', created_at: new Date().toISOString() }] }));
  });
  await page.route('**/api/v2/paper/8/stop**', async (route) => {
    await route.fulfill(json({ status: 'stopped', account_id: 8, events: [{ level: 'warning', message: '模拟盘已停止', created_at: new Date().toISOString() }] }));
  });
  await page.route('**/api/v2/data/status**', async (route) => {
    await route.fulfill(json({
      database: 'postgresql',
      status: 'ready',
      sqlite: 'disabled',
      migrated: false,
      tables: [{ name: 'kline_1d', rows: 244 }, { name: 'kline_history', rows: 244 }, { name: 'strategy_scripts', rows: 7 }],
      kline_coverage: [
        { exchange: 'cn', symbol: 'SH_600000', name: '浦发银行', timeframe: '1d', rows: 120, first_date: '2026-01-01', last_date: '2026-06-01', status: 'success' },
        { exchange: 'cn', symbol: 'SZ_000001', name: '平安银行', timeframe: '1d', rows: 124, first_date: '2026-01-01', last_date: '2026-06-01', status: 'success' },
      ],
      sync_jobs: [{ id: 5, job_name: 'kline-sync-20260604', status: 'success', total_items: 2, completed_items: 2, failed_items: 0 }],
    }));
  });
  await page.route('**/api/v2/data/config**', async (route) => {
    await route.fulfill(json({
      defaultSymbols: ['SH_600000', 'SZ_000001'],
      defaultTimeframes: ['1d'],
      defaultHistoryDays: 365,
    }));
  });
  await page.route('**/api/v2/data/schedule**', async (route) => {
    if (route.request().method() === 'PUT') {
      await route.fulfill(json({
        enabled: true,
        mode: 'all_ashare_daily',
        syncAllAshare: true,
        runHour: 18,
        runMinute: 10,
        intervalMinutes: 240,
        historyDays: 7,
        symbols: [],
        timeframes: ['1d'],
        nextRunAt: '2026-06-04T16:00:00',
        lastJobId: '42',
      }));
    } else {
      await route.fulfill(json({
        enabled: true,
        mode: 'all_ashare_daily',
        syncAllAshare: true,
        runHour: 18,
        runMinute: 10,
        intervalMinutes: 240,
        historyDays: 7,
        symbols: [],
        timeframes: ['1d'],
        nextRunAt: null,
      }));
    }
  });
  await page.route('**/api/v2/data/table-stats**', async (route) => {
    await route.fulfill(json({
      totalRecords: 244,
      totalPairs: 2,
      marketStats: {
        stock: { totalRecords: 244, totalPairs: 2, totalSymbols: 2 },
        spot: { totalRecords: 244, totalPairs: 2, totalSymbols: 2 },
        swap: { totalRecords: 0, totalPairs: 0, totalSymbols: 0 },
      },
      tables: [
        { tableName: 'kline_1d', exchange: 'cn', symbol: 'SH_600000', timeframe: '1d', recordCount: 120, firstTimestamp: 1767225600000, lastTimestamp: 1780272000000 },
        { tableName: 'kline_1d', exchange: 'cn', symbol: 'SZ_000001', timeframe: '1d', recordCount: 124, firstTimestamp: 1767225600000, lastTimestamp: 1780272000000 },
      ],
    }));
  });
  await page.route('**/api/v2/data/symbols**', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill(json({
        symbol: 'SZ_000001',
        added: true,
        defaultSymbols: ['SH_600000', 'SZ_000001'],
      }));
    } else {
      await route.fulfill(json({
        symbol: 'SH_600000',
        removed: true,
        defaultSymbols: ['SZ_000001'],
      }));
    }
  });
  await page.route('**/api/v2/data/delete-data**', async (route) => {
    await route.fulfill(json({ message: '已删除 SH_600000 1d 数据', deleted: 120 }));
  });
  await page.route('**/api/v2/stocks/search**', async (route) => {
    await route.fulfill(json([
      { code: 'SZ_000001', name: '平安银行', price: 12.4, change_percent: 1.2, reason: 'A股核心样例' },
      { code: 'SH_600000', name: '浦发银行', price: 10.6, change_percent: 6.1, reason: '已同步' },
    ]));
  });
  await page.route('**/api/v2/data/sync**', async (route) => {
    await route.fulfill(json({ success: true, message: 'K线历史同步任务已提交', job_id: 6 }));
  });
  await page.route('**/api/v2/data/start**', async (route) => {
    await route.fulfill(json({ success: true, message: '同步任务已启动', jobId: '6', job_id: 6 }));
  });
}

test('根路径展示 BitPro 风格大盘并只显示七个核心入口', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/');

  await expect(page.getByRole('heading', { name: '实时大盘' })).toBeVisible();
  await expect(page.getByText('上证指数')).toBeVisible();
  await expect(page.getByRole('link', { name: /大盘/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /行情/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /策略/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /回测/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /^模拟$/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /监控/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /数据/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /AI研发/ })).toHaveCount(0);
  await expect(page.locator('aside')).toHaveCSS('width', '64px');
});

test('大盘模块恢复市场概览、市场情绪和消息流三个子模块', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/');

  await expect(page.getByRole('heading', { name: '大盘模块' })).toBeVisible();
  await expect(page.getByRole('button', { name: /市场概览与分析/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /市场情绪分析/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /消息流/ })).toBeVisible();
  await expect(page.getByText('热门概念板块').first()).toBeVisible();

  await page.getByRole('button', { name: /市场情绪分析/ }).click();
  await expect(page.getByRole('heading', { name: '市场情绪分析' })).toBeVisible();
  await expect(page.getByText('市场情绪指数')).toBeVisible();

  await page.getByRole('button', { name: /消息流/ }).click();
  await expect(page.getByRole('heading', { name: '消息流' })).toBeVisible();
  await expect(page.getByText('7x24 实时快讯')).toBeVisible();
});

test('旧路由兼容跳转到新的核心页面', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/strategy-dev');
  await expect(page).toHaveURL(/\/strategy$/);

  await page.goto('/strategy-backtest');
  await expect(page).toHaveURL(/\/backtest$/);

  await page.goto('/strategy-paper');
  await expect(page).toHaveURL(/\/paper$/);

  await page.goto('/strategy-exec');
  await expect(page).toHaveURL(/\/paper$/);
});

test('策略页只做策略生成和编辑，不混放回测或模拟盘', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/strategy');
  await expect(page.getByRole('heading', { name: '策略中心' })).toBeVisible();
  await expect(page.getByRole('button', { name: /我的策略/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /策略广场/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'AI 写策略' })).toBeVisible();
  await expect(page.getByRole('button', { name: '新建策略' })).toBeVisible();
  await expect(page.getByRole('button', { name: /运行中/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /暂停/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /未启动/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /A股/ })).toBeVisible();
  await expect(page.getByPlaceholder('搜索策略...')).toBeVisible();
  await expect(page.getByTestId('strategy-card')).toHaveCount(1);
  await expect(page.getByText('双均线动量策略')).toBeVisible();
  await expect(page.getByText('Backtrader 多股组合策略')).toBeVisible();
  await expect(page.getByRole('button', { name: /实例控制台/ })).toBeVisible();
  await expect(page.getByText('A股').first()).toBeVisible();
  await expect(page.getByText('1D').first()).toBeVisible();
  await expect(page.getByRole('button', { name: '运行回测' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '启动模拟盘' })).toHaveCount(0);
  await expect(page.getByText('Backtrader 策略类')).toHaveCount(0);

  await page.getByRole('button', { name: 'AI 写策略' }).click();
  await expect(page.getByText('自动开发完成')).toBeVisible();
  await expect(page.getByRole('textbox', { name: '策略名称' })).toHaveValue('本地生成-首板突破');
  await expect(page.getByText('class GeneratedAshareStrategy').first()).toBeVisible();
});

test('策略详情页复刻 BitPro 详情态', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/strategy');
  await page.getByRole('button', { name: /详情/ }).first().click();

  await expect(page.getByRole('button', { name: /返回/ })).toBeVisible();
  await expect(page.getByRole('button', { name: '编辑策略' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '双均线动量策略' })).toBeVisible();
  await expect(page.getByText('A股').first()).toBeVisible();
  await expect(page.getByText('1D').first()).toBeVisible();
  await expect(page.getByText('核心选股与交易逻辑')).toBeVisible();
  await expect(page.getByText('核心选股', { exact: true })).toBeVisible();
  await expect(page.getByText('交易逻辑', { exact: true })).toBeVisible();
  await expect(page.getByText('策略描述')).toBeVisible();
  await expect(page.getByText('交易范围')).toBeVisible();
  await expect(page.getByText('Backtrader 多股组合策略')).toBeVisible();
});

test('回测页可运行 Backtrader 多股组合并展示指标曲线和交易明细', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/backtest');
  await expect(page.getByRole('heading', { name: '回测实例控制台' })).toBeVisible();
  await expect(page.getByText('回测历史').first()).toBeVisible();
  await expect(page.getByTestId('backtest-history-table')).toBeVisible();
  await expect(page.getByPlaceholder('搜索回测实例、策略、标的...')).toHaveCount(0);
  await expect(page.getByTestId('backtest-instance-card')).toHaveCount(0);
  await expect(page.getByText('回测参数')).toHaveCount(0);
  await page.getByRole('button', { name: '创建回测实例' }).click();
  await expect(page.getByText('创建回测实例').first()).toBeVisible();
  await expect(page.getByText('选择策略', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('配置参数')).toBeVisible();
  await expect(page.getByText('执行回测')).toBeVisible();
  await page.getByRole('button', { name: '下一步' }).click();
  await page.getByRole('button', { name: '下一步' }).click();
  await page.getByRole('button', { name: '开始回测' }).click();

  await expect(page.getByTestId('backtest-history-table')).toBeVisible();
  await expect(page.getByText('双均线动量策略').first()).toBeVisible();
  await expect(page.getByText('+12.50%')).toBeVisible();
  await expect(page.getByText('回撤').first()).toBeVisible();
  await expect(page.getByText('浦发银行 SH_600000').first()).toBeVisible();
  await expect(page.getByRole('button', { name: /查看/ }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /删除历史/ }).first()).toBeVisible();
  await expect(page.getByText('风险评级')).toHaveCount(0);
  await expect(page.getByText('成本拖累')).toHaveCount(0);
  await expect(page.getByText('样本效率')).toHaveCount(0);
});

test('回测结果详情页复刻 BitPro 详情态', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/backtest');
  await page.getByRole('button', { name: '创建回测实例' }).click();
  await page.getByRole('button', { name: '下一步' }).click();
  await page.getByRole('button', { name: '下一步' }).click();
  await page.getByRole('button', { name: '开始回测' }).click();
  await page.getByRole('button', { name: '查看' }).click();

  await expect(page.getByRole('button', { name: /返回/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: '双均线动量策略' }).first()).toBeVisible();
  await expect(page.getByText('历史记录').first()).toBeVisible();
  await expect(page.getByText('2026-01-01 至 2026-01-08').first()).toBeVisible();
  await expect(page.getByTestId('backtest-detail-metrics')).toBeVisible();
  await expect(page.getByText('累计收益').first()).toBeVisible();
  await expect(page.getByText('年化收益率').first()).toBeVisible();
  await expect(page.getByText('基准收益率').first()).toBeVisible();
  await expect(page.getByText('阿尔法').first()).toBeVisible();
  await expect(page.getByText('贝塔').first()).toBeVisible();
  await expect(page.getByText('索提诺比率').first()).toBeVisible();
  await expect(page.getByText('最大回撤').first()).toBeVisible();
  await expect(page.getByText('回测配置')).toHaveCount(0);
  await expect(page.getByText('成本模型')).toHaveCount(0);
  await expect(page.getByText('概要').first()).toBeVisible();
  await expect(page.getByText('绩效').first()).toBeVisible();
  await expect(page.getByText('交易记录').first()).toBeVisible();
  await expect(page.getByText('资金曲线')).toBeVisible();
  await page.getByRole('button', { name: '交易记录' }).click();
  await expect(page.getByText('默认按时间倒序显示')).toHaveCount(0);
  await expect(page.getByRole('columnheader', { name: '成交金额' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '手续费' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '原因' })).toHaveCount(0);
  await expect(page.getByText('浦发银行 SH_600000').first()).toBeVisible();
});

test('模拟页可按 BitPro 向导启动、刷新、停止模拟盘并展示运行指标', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/paper');
  await expect(page.getByText('模拟盘', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('heading', { name: '策略实例控制台' })).toBeVisible();
  await expect(page.getByText('管理多路模拟实例')).toBeVisible();
  await expect(page.getByRole('button', { name: '创建新模拟实例' })).toBeVisible();
  await expect(page.getByRole('button', { name: /全部 1/ }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /A股 1/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /创建时间/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /收益率/ })).toBeVisible();
  await expect(page.getByText('模拟账户概览')).toBeVisible();
  await expect(page.getByText('运行中账户')).toBeVisible();
  await expect(page.getByText('账户总权益')).toBeVisible();
  await expect(page.getByPlaceholder('搜索策略、标的、周期...')).toHaveCount(0);
  await expect(page.getByText('策略类型')).toHaveCount(0);
  const instanceGrid = page.getByTestId('paper-instance-grid');
  await expect(instanceGrid).toBeVisible();
  await expect
    .poll(async () => {
      const template = await instanceGrid.evaluate((element) => window.getComputedStyle(element).gridTemplateColumns);
      return template.split(/\s+/).filter(Boolean).length;
    })
    .toBe(4);
  await expect(page.getByTestId('paper-instance-card')).toHaveCount(1);
  await expect(page.getByText('双均线动量策略 模拟盘')).toBeVisible();
  await expect(page.getByText('收益金额').first()).toBeVisible();
  await expect(page.getByText('收益率').first()).toBeVisible();
  await expect(page.getByText('胜率').first()).toBeVisible();
  await expect(page.getByText('盈亏比').first()).toBeVisible();
  await expect(page.getByText('交易次数').first()).toBeVisible();
  await expect(page.getByText('风险状态')).toHaveCount(0);
  await expect(page.getByText('现金占比')).toHaveCount(0);
  await expect(page.getByText('持仓数')).toHaveCount(0);
  await expect(page.getByTestId('paper-card-primary-action').first()).toHaveText('详情');

  await page.getByRole('button', { name: '创建新模拟实例' }).click();
  const wizard = page.getByTestId('paper-create-wizard');
  await expect(wizard.getByText('创建向导')).toBeVisible();
  await expect(wizard.getByTestId('paper-wizard-step-1')).toHaveText('选择策略');
  await expect(wizard.getByTestId('paper-wizard-step-2')).toHaveText('运行参数');
  await expect(wizard.getByTestId('paper-wizard-step-3')).toHaveText('飞行检查');
  await expect(wizard.getByTestId('paper-wizard-step-4')).toHaveText('运行监控');
  await expect(wizard.getByText('选择交易策略')).toBeVisible();
  await expect(wizard.getByText('双均线动量策略', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一步 · 运行参数' }).click();
  await expect(page.getByText('运行参数确认')).toBeVisible();
  await expect(wizard.getByText('初始资金', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一步 · 飞行检查' }).click();
  await expect(wizard.getByRole('heading', { name: '飞行检查' })).toBeVisible();
  await expect(wizard.getByText('PaperBroker', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一步 · 运行监控' }).click();
  await expect(wizard.getByRole('heading', { name: '运行监控预览' })).toBeVisible();
  await expect(wizard.getByText('启动后进入实例详情页')).toBeVisible();
  await page.getByRole('button', { name: '启动模拟实例' }).click();
  await expect(page.getByText('模拟盘已启动').first()).toBeVisible();
  await expect(page.getByTestId('paper-instance-card')).toHaveCount(2);
  await expect(page.getByText('+¥1,800.00').first()).toBeVisible();
  await expect(page.getByText('浦发银行 SH_600000').first()).toBeVisible();

  const newInstanceCard = page.locator('[data-account-id="8"]');
  await expect(newInstanceCard.getByTestId('paper-card-primary-action')).toHaveText('详情');
  await expect(newInstanceCard.getByRole('button', { name: '刷新' })).toHaveCount(0);
  await expect(newInstanceCard.getByRole('button', { name: '关闭交易' })).toHaveCount(0);
  await newInstanceCard.getByRole('button', { name: '详情' }).click();
  await page.getByRole('button', { name: '刷新' }).click();
  await expect(page.getByText('¥102,400.00')).toBeVisible();
  await page.getByRole('button', { name: '关闭交易' }).click();
  await expect(page.getByText('已停止').first()).toBeVisible();
});

test('模拟实例详情页复刻 BitPro 详情态', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/paper');
  await page.getByRole('button', { name: '创建新模拟实例' }).click();
  await page.getByRole('button', { name: '下一步 · 运行参数' }).click();
  await page.getByRole('button', { name: '下一步 · 飞行检查' }).click();
  await page.getByRole('button', { name: '下一步 · 运行监控' }).click();
  await page.getByRole('button', { name: '启动模拟实例' }).click();
  await page.locator('[data-account-id="8"]').getByRole('button', { name: '详情' }).click();

  await expect(page.getByRole('button', { name: /返回控制台/ })).toBeVisible();
  await expect(page.getByText('模拟 · 只做 PaperBroker / 模拟成交，不触碰真实资金。')).toBeVisible();
  await expect(page.getByText('实例监控')).toBeVisible();
  await expect(page.getByRole('heading', { name: '双均线动量策略 模拟盘' })).toBeVisible();
  await expect(page.getByText('实例状态')).toHaveCount(0);
  await expect(page.getByText('运行标的')).toHaveCount(0);
  await expect(page.getByText('资金口径')).toHaveCount(0);
  await expect(page.getByText('执行约束')).toHaveCount(0);
  await expect(page.getByText('A股交易约束已启用')).toHaveCount(0);
  await expect(page.getByText('账户总额')).toBeVisible();
  await expect(page.getByText('总盈亏')).toBeVisible();
  await expect(page.getByText('收益率')).toBeVisible();
  await expect(page.getByText('总交易')).toBeVisible();
  await expect(page.getByText('最大回撤')).toBeVisible();
  await expect(page.getByText('运行时间')).toBeVisible();
  await expect(page.getByText('买卖点 K线复盘')).toBeVisible();
  await expect(page.getByText('成交点时间线')).toBeVisible();
  await expect(page.getByText('B · 10.00').first()).toBeVisible();
  await expect(page.getByText('账户曲线')).toBeVisible();
  await expect(page.getByText('当前持仓')).toBeVisible();
  await expect(page.getByText('成交与事件')).toBeVisible();
  await expect(page.getByText('策略运行诊断日志')).toBeVisible();
  await expect(page.getByText('清空')).toBeVisible();
  await expect(page.getByText('核心选股与交易逻辑')).toBeVisible();
  await expect(page.getByText('浦发银行 SH_600000').first()).toBeVisible();
});

test('行情页复刻 BitPro 行情工作区', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/market');
  await expect(page.getByRole('heading', { name: '行情' })).toBeVisible();
  await expect(page.getByText('市场列表')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'AI 预测' })).toBeVisible();
  await expect(page.getByRole('button', { name: '选择股票' })).toBeVisible();
  await expect(page.getByText('订单簿').first()).toBeVisible();
  await expect(page.locator('canvas').first()).toBeVisible();

  await page.getByRole('button', { name: '选择股票' }).click();
  await expect(page.getByPlaceholder('搜索股票 / 代码')).toBeVisible();
  await expect(page.getByText('热门')).toBeVisible();
  await expect(page.getByText('浦发银行').first()).toBeVisible();

  await page.getByRole('button', { name: 'AI 预测' }).click();
  await expect(page.getByText('预测偏差分析（视觉预览）')).toBeVisible();
});

test('行情、监控、数据页核心内容可用', async ({ page }) => {
  test.setTimeout(90_000);
  await mockCoreV2Routes(page);

  await page.goto('/market');
  await expect(page.getByRole('heading', { name: '行情' })).toBeVisible();
  await expect(page.getByText('市场列表')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'AI 预测' })).toBeVisible();
  await expect(page.getByRole('button', { name: '选择股票' })).toBeVisible();
  await expect(page.getByText('浦发银行').first()).toBeVisible();
  await expect(page.getByText('订单簿').first()).toBeVisible();
  await expect(page.locator('canvas').first()).toBeVisible();

  await page.goto('/monitor');
  await expect(page.getByRole('heading', { name: '监控中心' })).toBeVisible();
  await expect(page.getByText('模拟盘监控')).toBeVisible();
  await expect(page.getByText('103,200').first()).toBeVisible();
  await page.getByRole('button', { name: '详情' }).first().click();
  await expect(page.getByRole('heading', { name: '双均线动量策略 模拟盘' })).toBeVisible();
  await expect(page.getByText('账户总额')).toBeVisible();
  await expect(page.getByText('风控状态')).toBeVisible();

  await page.goto('/data');
  await expect(page.getByRole('heading', { name: '数据管理中心' })).toBeVisible();
  await expect(page.getByText(/PostgreSQL · A股/)).toBeVisible();
  await expect(page.getByText('数据健康度')).toBeVisible();
  await expect(page.getByText('同步质量诊断')).toBeVisible();
  await expect(page.getByText('成功率')).toBeVisible();
  await expect(page.getByText('覆盖缺口', { exact: true })).toBeVisible();
  await expect(page.getByText('同步任务明细')).toBeVisible();
  await expect(page.getByText('同步覆盖矩阵')).toBeVisible();
  await expect(page.getByText('浦发银行 SH_600000').first()).toBeVisible();
  await expect(page.getByRole('button', { name: '定时同步' })).toBeVisible();
  await page.getByRole('button', { name: '定时同步' }).click();
  await expect(page.getByRole('heading', { name: '定时同步设置' })).toBeVisible();
  await expect(page.getByText('全部 A股股票，来源为实时股票池缓存；缓存为空时自动从行情服务刷新。')).toBeVisible();
  await page.getByLabel('启用定时同步').check();
  await page.getByRole('button', { name: '保存设置' }).click();
  await expect(page.getByText('定时同步已保存')).toBeVisible();
  await page.getByRole('button', { name: '增加股票' }).click();
  await expect(page.getByRole('heading', { name: '增加股票' })).toBeVisible();
  await page.getByPlaceholder('搜索股票代码或名称...').fill('平安');
  await page.getByRole('button', { name: /平安银行 SZ_000001/ }).click();
  await expect(page.getByText('添加后同步历史数据')).toBeVisible();
  await page.getByRole('button', { name: /^添加$/ }).click();
  await expect(page.getByText('股票已添加')).toBeVisible();
  await page.getByRole('button', { name: '删除股票' }).click();
  await expect(page.getByRole('heading', { name: '删除股票' })).toBeVisible();
  await page.getByRole('button', { name: /浦发银行 SH_600000/ }).click();
  await page.getByRole('button', { name: '移除' }).click();
  await expect(page.getByText('股票已从后续同步名单移除')).toBeVisible();
  await page.getByRole('button', { name: '删除数据' }).click();
  await expect(page.getByRole('heading', { name: '删除历史数据' })).toBeVisible();
  await page.getByRole('button', { name: /浦发银行 SH_600000/ }).click();
  await page.getByRole('button', { name: '确认删除数据' }).click();
  await expect(page.getByText('历史数据已删除')).toBeVisible();
  await page.getByRole('button', { name: '自定义同步' }).click();
  await page.getByRole('button', { name: '开始同步' }).click();
  await expect(page.getByText('K线历史同步任务已提交')).toBeVisible();
});

test('数据页接近 BitPro 数据管理完整流程', async ({ page }) => {
  await mockCoreV2Routes(page);

  await page.goto('/data');
  await expect(page.getByRole('heading', { name: '数据管理中心' })).toBeVisible();
  await expect(page.getByText('数据表统计')).toBeVisible();
  await expect(page.getByText('kline_1d').first()).toBeVisible();
  await expect(page.getByText('244').first()).toBeVisible();

  await page.getByRole('button', { name: '删除数据' }).click();
  await expect(page.getByRole('heading', { name: '删除历史数据' })).toBeVisible();
  await page.getByRole('button', { name: /浦发银行 SH_600000/ }).click();
  await page.getByRole('button', { name: '确认删除数据' }).click();
  await expect(page.getByText('历史数据已删除')).toBeVisible();
});
