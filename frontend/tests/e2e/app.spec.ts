import { expect, Page, test } from '@playwright/test';

const useMockApi = process.env.MOCK_API !== 'false';
test.skip(!useMockApi, 'This suite is for mocked API mode. Set MOCK_API=false for real backend tests.');

const now = new Date('2026-06-08T09:30:00+08:00').toISOString();

const factor = {
  id: 61,
  factor_code: 'momentum_20d',
  factor_name: '20日动量',
  category: 'momentum',
  description: '基于封存日线的20日价格动量',
  direction: 1,
  research_status: 'exploratory',
  enabled: true,
  active_version_id: 2,
  version_no: 1,
  content_hash: '0123456789abcdef',
  validation_status: 'valid',
  last_trade_date: '2025-01-02',
  publication_state: 'published',
  dataset_snapshot_id: 9,
  universe_snapshot_id: 1,
  knowledge_cutoff_at: '2026-07-16T02:53:33Z',
  coverage: 1,
  rank_ic: null,
  icir: null,
  long_short_return: null,
  turnover: null,
  decay: null,
};

const factorRun = {
  id: 101,
  factor_version_id: 2,
  factor_code: factor.factor_code,
  factor_name: factor.factor_name,
  version_no: 1,
  trade_date: '2025-01-02',
  dataset_snapshot_id: 9,
  universe_snapshot_id: 1,
  knowledge_cutoff_at: factor.knowledge_cutoff_at,
  status: 'published',
  input_count: 20,
  output_count: 20,
  missing_count: 0,
  value_hash: 'abcdef0123456789',
};

const factorMetrics = [
  { metric_code: 'coverage', metric_value: 1 },
  { metric_code: 'mean', metric_value: 0.15 },
  { metric_code: 'std', metric_value: 1.03 },
  { metric_code: 'skewness', metric_value: 0.2 },
  { metric_code: 'kurtosis', metric_value: 2.9 },
  { metric_code: 'missing_rate', metric_value: 0 },
  { metric_code: 'outlier_rate', metric_value: 0.05 },
  { metric_code: 'size_exposure', metric_value: -0.18 },
  { metric_code: 'industry_exposure', metric_value: null, metric_payload: { 银行: -0.32, 电子: 0.41 } },
  { metric_code: 'ic', horizon: 1, metric_value: null, pending_reason: '至少需要下一个交易日收盘数据' },
  { metric_code: 'rank_ic', horizon: 1, metric_value: null, pending_reason: '至少需要下一个交易日收盘数据' },
].map((item) => ({
  compute_run_id: factorRun.id,
  trade_date: factorRun.trade_date,
  dataset_snapshot_id: factorRun.dataset_snapshot_id,
  universe_snapshot_id: factorRun.universe_snapshot_id,
  knowledge_cutoff_at: factorRun.knowledge_cutoff_at,
  factor_version_id: factorRun.factor_version_id,
  version_no: 1,
  metric_payload: {},
  pending_reason: null,
  horizon: null,
  ...item,
}));

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

    if (method === 'GET' && path === '/workflow/capabilities') {
      return route.fulfill(json({
        contract_version: 'stockpro-workflow-v1',
        behavioral_baseline: 'bitpro',
        execution_scope: 'paper_only',
        checked_at: now,
        auth_modes: [
          { id: 'admin', status: 'available', write_access: true },
          { id: 'guest', status: 'not_implemented', write_access: false },
          { id: 'agent', status: 'not_implemented', write_access: false },
        ],
        feature_gates: {
          async_backtest_jobs: { status: 'available', storage: 'postgresql', controls: ['poll', 'logs', 'cancel', 'retry'] },
          real_broker: { status: 'not_implemented', enabled: false },
        },
        domain_guardrails: ['A股交易日历', 'T+1 可卖约束', '100 股整数手'],
        stages: [
          { id: 'strategy', label: '策略', route: '/strategy', status: 'available', requires: [], evidence: [] },
          { id: 'backtest', label: '回测', route: '/backtest', status: 'available', requires: [], evidence: ['job_id', 'run_id', 'logs'] },
          { id: 'paper', label: '模拟', route: '/paper', status: 'available', requires: [], evidence: [] },
          { id: 'watch', label: '观察', route: '/watch', status: 'partial', requires: [], evidence: [] },
          { id: 'monitor', label: '监控', route: '/monitor', status: 'partial', requires: [], evidence: [] },
          { id: 'review', label: '复盘', route: '/review', status: 'available', requires: [], evidence: [] },
        ],
      }));
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
        data_status: {
          stock_snapshot_state: 'fresh',
          stock_snapshot_count: 5120,
          stock_snapshot_updated_at: now,
          index_snapshot_state: 'fresh',
          index_snapshot_count: 4,
          index_snapshot_updated_at: now,
          source_label: 'PostgreSQL realtime cache',
        },
        is_open: true,
        last_update: now,
        response_generated_at: now,
      }));
    }

    if (method === 'GET' && path === '/market/research-context') {
      const metrics = [
        ['rise_count', '上涨家数', 3200], ['fall_count', '下跌家数', 1800], ['flat_count', '平盘家数', 120],
        ['limit_up_count', '涨停数', 56], ['limit_down_count', '跌停数', 4], ['broken_board_count', '炸板数', 9],
        ['seal_rate', '封板率', 86.15], ['highest_board', '最高板', 6], ['red_market_ratio', '红盘率', 62.5],
        ['rise_fall_ratio', '涨跌比', 1.78], ['new_high_count', '新高数', null], ['new_low_count', '新低数', null],
      ].map(([metric_code, label, value]) => ({ metric_code, label, value, unit: metric_code === 'seal_rate' || metric_code === 'red_market_ratio' ? '%' : null, definition: `${label}定义`, source_label: value === null ? null : 'tushare_limit_list_d', publication_state: value === null ? 'unavailable' : 'published', missing_reason: value === null ? '未封存' : null }));
      return route.fulfill(json({
        publication_state: 'published',
        snapshot: { id: 1, trade_date: '2025-01-02', snapshot_type: 'post_close', session_label: '盘后', freshness: 'stale', source_map: { up: 'tushare_limit_list_d', kpl_list: 'tushare_kpl_list' }, status: 'published', content_hash: '14d6e3d18b4c08342d28025493cbe3d9' },
        sentiment: { metrics, market_temperature: { value: null, formula_version: 'market-temperature.v1', weights: { breadth: 0.25 }, missing_components: ['liquidity_participation'], publication_state: 'unavailable' } },
        limit_ecosystem: { source_label: 'tushare_limit_list_d', highest_board: 6, ladder: [{ level: '1板', count: 43, members: [{ symbol: '000017.SZ', name: '深中华A' }] }, { level: '2板', count: 10, members: [{ symbol: '002184.SZ', name: '海得控制' }] }, { level: '3板', count: 2, members: [] }, { level: '4板', count: 0, members: [] }, { level: '5+板', count: 3, members: [{ symbol: '000759.SZ', name: '中百集团' }] }], pools: { up: [], down: [], broken: [] }, promotion_elimination: [{ from_level: 1, cohort_size: 20, promoted_count: 10, eliminated_count: 10 }] },
        sector_evidence: { classification_system: 'tushare_limit_industry', items: [{ sector_name: '商业百货', limit_up_count: 8, ladder_participation: 3, leader_symbol: '600693.SH', return_1d: null, net_flow: null, source_label: 'tushare_limit_list_d' }] },
        heat_rankings: [{ rank: 1, symbol: '600000.SH', name: '浦发银行', source_label: 'tushare_kpl_list' }],
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
        { date: '2025-01-01', open: 9.7, high: 10.1, low: 9.6, close: 9.9, volume: 900000 },
        { date: '2025-01-02', open: 9.9, high: 10.3, low: 9.8, close: 10.1, volume: 1000000 },
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

    if (method === 'GET' && path === '/factors/research/library') {
      return route.fulfill(json({ items: [factor] }));
    }

    if (method === 'GET' && path === '/factor-compute-runs') {
      return route.fulfill(json({ items: [factorRun] }));
    }

    if (method === 'GET' && path === '/factor-correlations') {
      return route.fulfill(json({ items: [] }));
    }

    if (method === 'GET' && /^\/factors\/\d+\/metrics$/.test(path)) {
      return route.fulfill(json({ factor, metrics: factorMetrics }));
    }

    if (method === 'GET' && /^\/factors\/\d+\/values$/.test(path)) {
      return route.fulfill(json({
        items: [{
          trade_date: factorRun.trade_date,
          symbol: '600000.SH',
          raw_value: 0.12,
          processed_value: 0.88,
          rank: 1,
          percentile: 1,
          quantile: 5,
          quality_flags: {},
          compute_run_id: factorRun.id,
          factor_version_id: factorRun.factor_version_id,
          dataset_snapshot_id: factorRun.dataset_snapshot_id,
          universe_snapshot_id: factorRun.universe_snapshot_id,
          knowledge_cutoff_at: factorRun.knowledge_cutoff_at,
        }],
      }));
    }

    if (method === 'POST' && path === '/factor-schedules/run-daily') {
      return route.fulfill(json({ status: 'reused', factor_snapshot_id: 3 }));
    }

    if (method === 'POST' && path === '/factors') {
      return route.fulfill(json({ factor, version: { validation: { valid: true, errors: [] } } }));
    }

    if (method === 'GET' && path === '/strategy/list') {
      return route.fulfill(json([
        {
          id: 1,
          name: '测试策略',
          description: '用于 E2E 的示例策略',
          script_content: 'def initialize(context):\n    pass\n\ndef handle_data(context, data):\n    pass\n',
          interval_seconds: 60,
          enabled: true,
          is_running: false,
          created_at: now,
          updated_at: now,
        },
      ]));
    }

    if (method === 'GET' && path === '/ai/capabilities') {
      return route.fulfill(json({
        provider: 'qwen',
        model: null,
        configured: false,
        generation_status: 'not_configured',
        reason: 'QWEN_API_KEY 未配置',
        strategy_auto_develop_mode: 'deterministic_template',
        strategy_auto_develop_uses_ai: false,
        checked_at: now,
      }));
    }

    if (method === 'GET' && /^\/strategy\/\d+\/versions\/latest$/.test(path)) {
      return route.fulfill(json({
        id: '11111111-1111-1111-1111-111111111111',
        legacy_strategy_id: 1,
        name: '测试策略',
        version: 1,
        description: '用于 E2E 的示例策略',
        script_content: 'def initialize(context):\n    pass\n\ndef handle_data(context, data):\n    pass\n',
        content_hash: '0123456789abcdef',
        strategy_api_version: 'stockpro.v1',
        validation_status: 'valid',
        validation_report: { valid: true, api_version: 'stockpro.v1', issues: [], dependencies: [] },
      }));
    }

    if (method === 'POST' && path === '/strategy/save') {
      return route.fulfill(json({
        success: true,
        id: 2,
        strategy_version: {
          id: '22222222-2222-2222-2222-222222222222',
          name: '生命周期策略',
          version: 1,
          description: '',
          script_content: '',
          content_hash: 'abcdef0123456789',
          strategy_api_version: 'stockpro.v1',
          validation_status: 'valid',
          validation_report: { valid: true, api_version: 'stockpro.v1', issues: [], dependencies: ['history'] },
        },
        validation: { valid: true, api_version: 'stockpro.v1', issues: [], dependencies: ['history'] },
      }));
    }

    if (method === 'POST' && /^\/strategy\/versions\/[^/]+\/quick-run$/.test(path)) {
      return route.fulfill(json({
        run_id: '33333333-3333-3333-3333-333333333333',
        status: 'success',
        event_count: 20,
        intent_count: 12,
        record_count: 20,
        intent_hash: 'intent-hash',
        record_hash: 'record-hash',
      }));
    }

    if (method === 'GET' && path === '/factor-snapshots') {
      return route.fulfill(json({ items: [{ id: 3, dataset_snapshot_id: 9, universe_snapshot_id: 1, status: 'sealed' }] }));
    }

    if (method === 'GET' && path === '/backtest/results') {
      return route.fulfill(json({ items: [], total: 0 }));
    }

    if (method === 'GET' && path === '/backtest/configuration') {
      return route.fulfill(json({
        strategy_versions: [{ id: '22222222-2222-2222-2222-222222222222', name: 'MA5 趋势策略', version: 1, description: 'fixture', script_content: 'def initialize(context):\n    pass\n\ndef handle_data(context, data):\n    order_target_percent(context.universe[0], 0.5)\n', content_hash: 'strategy-content-hash' }],
        dataset_snapshots: [{ id: 10, name: 'backtest-ready-2023-2025', start_date: '2023-01-03', end_date: '2025-01-02', row_count: 9700, symbol_count: 20, manifest_hash: 'dataset-manifest', datasets: ['daily_bars', 'price_limits', 'benchmark_bars'] }],
        universe_snapshots: [{ id: 1, code: 'all_a', rule_version: 'v1', trade_date: '2025-01-02', member_count: 5336, manifest_hash: 'universe-manifest' }],
        factor_snapshots: [{ id: 3, name: 'daily-alpha', trade_date: '2025-01-02', dataset_snapshot_id: 10, universe_snapshot_id: 1, manifest_hash: 'factor-manifest' }],
        pool_snapshots: [{ id: 11, pool_id: 'pool-1', pool_name: '动量 Top20', pool_type: 'factor', trade_date: '2025-01-02', dataset_snapshot_id: 10, universe_snapshot_id: 1, factor_snapshot_id: 3, knowledge_cutoff_at: now, manifest_hash: 'pool-manifest', member_count: 20, status: 'sealed' }],
        cost_models: [{ id: '44444444-4444-4444-4444-444444444444', code: 'cn_stock_default', name: 'A股默认成本', version: 1, content_hash: 'cost-hash' }],
        protocols: [{ id: '55555555-5555-5555-5555-555555555555', name: '样本外研究协议', hypothesis: '趋势溢价', status: 'sealed' }],
      }));
    }

    const mockBacktestRun = {
      id: '66666666-6666-6666-6666-666666666666', name: 'MA5 完整回测', status: 'success', run_mode: 'full', progress: 100,
      promotion_status: 'paper_eligible', strategy_version_id: '22222222-2222-2222-2222-222222222222', strategy_name: 'MA5 趋势策略', strategy_version: 1,
      script_content: 'def initialize(context):\n    pass\n', strategy_content_hash: 'strategy-content-hash', dataset_snapshot_id: 10,
      factor_snapshot_id: 3, pool_snapshot_id: 11, universe_snapshot_id: 1, research_protocol_id: '55555555-5555-5555-5555-555555555555', protocol_name: '样本外研究协议',
      cost_model_id: '44444444-4444-4444-4444-444444444444', cost_model_name: 'A股默认成本', benchmark_code: '000300.SH',
      start_date: '2023-01-03', end_date: '2025-01-02', initial_cash: 1000000, parameters: {}, universe: { symbols: ['SH_600519'] },
      metrics: { strategy_return: 0.12, annualized_return: 0.06, benchmark_return: 0.04, excess_return: 0.08, maximum_drawdown: 0.09, sharpe: 1.23 },
      input_hash: 'input-hash-abcdef', result_manifest: { manifest_hash: 'result-manifest-abcdef' }, created_at: '2025-01-02T18:00:00+08:00',
      data_purpose: 'acceptance',
    };
    const mockMetrics = Object.entries(mockBacktestRun.metrics).map(([metric_code, metric_value]) => ({ metric_code, metric_value, unit: metric_code === 'sharpe' ? 'number' : 'ratio', calculation_version: 'backtest-metrics.v1', input_frequency: '1d', null_reason: null }));
    const mockBacktestJob = {
      job_id: '77777777-7777-7777-7777-777777777777',
      request_payload: {},
      run_mode: 'quick',
      status: 'success',
      progress: 100,
      phase: 'completed',
      message: '回测完成，结果证据已封存',
      error_message: null,
      backtest_run_id: mockBacktestRun.id,
      owner_role: 'admin',
      owner_session_id: 'mock-session',
      owner_guest_code_id: null,
      parent_job_id: null,
      attempt: 1,
      created_at: now,
      updated_at: now,
      started_at: now,
      finished_at: now,
      cancel_requested_at: null,
    };

    if (method === 'GET' && path === '/backtest/jobs') return route.fulfill(json({ items: [mockBacktestJob], total: 1 }));
    if (method === 'POST' && path === '/backtest/jobs') return route.fulfill(json(mockBacktestJob, 202));
    if (method === 'GET' && path === `/backtest/jobs/${mockBacktestJob.job_id}/logs`) return route.fulfill(json({ items: [{ id: 1, job_id: mockBacktestJob.job_id, level: 'info', phase: 'completed', message: mockBacktestJob.message, payload: { progress: 100 }, created_at: now }] }));
    if (method === 'GET' && path === '/backtest/runs') return route.fulfill(json({ items: [mockBacktestRun], total: 1 }));
    if (method === 'GET' && path === `/backtest/runs/${mockBacktestRun.id}`) return route.fulfill(json({ ...mockBacktestRun, core_metrics: mockMetrics }));
    if (method === 'GET' && path === `/backtest/runs/${mockBacktestRun.id}/metrics`) return route.fulfill(json({ items: mockMetrics }));
    if (method === 'GET' && path === `/backtest/runs/${mockBacktestRun.id}/series`) return route.fulfill(json({ daily: [{ trade_date: '2025-01-01', strategy_nav: 1, benchmark_nav: 1, excess_nav: 1, equity: 1000000, cash: 1000000, market_value: 0, gross_exposure: 0, position_count: 0, drawdown: 0 }, { trade_date: '2025-01-02', strategy_nav: 1.12, benchmark_nav: 1.04, excess_nav: 1.0769, equity: 1120000, cash: 100000, market_value: 1020000, gross_exposure: 0.91, position_count: 1, drawdown: 0 }], custom_records: [], monthly_returns: [{ month: '2025-01', return: 0.12 }] }));
    if (method === 'GET' && new RegExp(`^/backtest/runs/${mockBacktestRun.id}/(positions|orders|trades|logs|attribution)$`).test(path)) return route.fulfill(json({ items: [] }));
    if (method === 'POST' && path === '/backtest/runs') return route.fulfill(json(mockBacktestRun));

    const mockPool = { id: 'pool-1', name: '动量 Top20', pool_type: 'factor', description: 'fixture', status: 'active', data_purpose: 'acceptance', rule_id: 'rule-1', rule_type: 'factor', rule_version: 1, config: { factor_code: 'momentum_20d', top_n: 20 }, rule_hash: 'rule-hash-abcdef', snapshot_count: 1, current_member_count: 2, latest_generation_id: 'generation-1', latest_dataset_snapshot_id: 10, latest_universe_snapshot_id: 1, latest_factor_snapshot_id: 3, latest_market_evidence_snapshot_id: null, latest_trade_date: '2025-01-02', latest_knowledge_cutoff_at: now, latest_input_hash: 'input-hash' };
    const mockMembers = [{ ordinal: 1, symbol: 'SH_600519', score: 1, reason: '20日动量排名 1', evidence: { factor_snapshot_id: 3 }, evidence_hash: 'member-hash-1', valid_from: '2025-01-02', valid_until: '2025-01-07', generator_version: 'stock-pool-generator.v1' }, { ordinal: 2, symbol: 'SZ_000333', score: 0.95, reason: '20日动量排名 2', evidence: { factor_snapshot_id: 3 }, evidence_hash: 'member-hash-2', valid_from: '2025-01-02', valid_until: '2025-01-07', generator_version: 'stock-pool-generator.v1' }];
    const mockPoolSnapshot = { id: 11, pool_id: 'pool-1', pool_name: '动量 Top20', pool_type: 'factor', trade_date: '2025-01-02', dataset_snapshot_id: 10, universe_snapshot_id: 1, factor_snapshot_id: 3, knowledge_cutoff_at: now, manifest_hash: 'pool-manifest-abcdef', member_count: 2, status: 'sealed' };
    if (method === 'GET' && path === '/pools') return route.fulfill(json({ items: [mockPool], total: 1 }));
    if (method === 'POST' && path === '/pools') return route.fulfill(json(mockPool));
    if (method === 'GET' && path === '/pools/pool-1/members') return route.fulfill(json({ items: mockMembers, total: 2 }));
    if (method === 'POST' && path === '/pools/pool-1/generate') return route.fulfill(json({ id: 'generation-1', pool_id: 'pool-1', status: 'success', trade_date: '2025-01-02', input_hash: 'input-hash', member_manifest_hash: 'member-manifest', member_count: 2, members: mockMembers, reused: false }));
    if (method === 'POST' && path === '/pools/pool-1/snapshots') return route.fulfill(json(mockPoolSnapshot));
    if (method === 'GET' && path === '/pool-snapshots') return route.fulfill(json({ items: [mockPoolSnapshot], total: 1 }));
    if (method === 'POST' && path === '/pool-snapshots/11/backtests') return route.fulfill(json({ status: 'draft', experiment: { id: 'experiment-1', pool_snapshot_id: 11 }, pool_snapshot: mockPoolSnapshot }));

    if (method === 'GET' && path === '/paper/accounts') {
      return route.fulfill(json({ accounts: [], total: 0 }));
    }

    const paperInstance = {
      id: '77777777-7777-7777-7777-777777777777', name: 'MA5 / Paper', status: 'running', data_purpose: 'acceptance',
      strategy_version_id: mockBacktestRun.strategy_version_id, dataset_snapshot_id: 10, factor_snapshot_id: 3,
      universe_snapshot_id: 1, pool_snapshot_id: 11, research_protocol_id: mockBacktestRun.research_protocol_id,
      qualifying_backtest_run_id: mockBacktestRun.id, portfolio_id: '88888888-8888-8888-8888-888888888888',
      parameters: {}, capacity_limits: { max_drawdown: 0.2, cash_floor_ratio: 0.05, max_daily_turnover: 1, max_participation_ratio: 0.1, max_single_symbol_weight: 0.25 }, feed_config: { mode: 'recorded_replay', provider: 'sealed_pg_snapshot' },
      cash_balance: 100000, initial_cash: 1000000, equity: 1120000, signal_count: 1, order_count: 1, trade_count: 1,
      signals: [{ id: 'signal-1', paper_instance_id: '77777777-7777-7777-7777-777777777777', signal_time: now, symbol: 'SH_600519', signal_type: 'buy', strength: 1, status: 'ordered', reason: 'MA5' }],
      orders: [{ id: 'order-1', symbol: 'SH_600519', side: 'buy', quantity: 100, price: 1500, status: 'filled', risk_event_id: 'risk-1', created_at: now }],
      trades: [{ id: 'trade-1', symbol: 'SH_600519', side: 'buy', quantity: 100, price: 1500, amount: 150000, commission: 5, traded_at: now, earliest_fill_at: now }],
      positions: [{ id: 'position-1', symbol: 'SH_600519', quantity: 100, available_quantity: 100, avg_cost: 1500, last_price: 1510, market_value: 151000 }],
      cash_ledger: [{ id: 1, amount: -150005, balance_after: 849995 }], equity_snapshots: [{ id: 1, trade_date: '2025-01-02', cash: 100000, market_value: 1020000, equity: 1120000, nav: 1.12, drawdown: 0 }],
      events: [{ id: 1, occurred_at: now, event_type: 'cycle', level: 'info', message: '行情周期处理完成', cycle_id: 'cycle-1' }],
      cycles: [{ id: 'cycle-1', trade_date: '2025-01-02', cycle_key: '2025-01-02:close', status: 'success', signal_count: 1, order_count: 1, trade_count: 1, ledger_difference: 0 }],
    };
    if (method === 'GET' && path === '/paper/instances') return route.fulfill(json({ items: [paperInstance], total: 1 }));
    if (method === 'GET' && path === `/paper/instances/${paperInstance.id}`) return route.fulfill(json(paperInstance));
    if (method === 'GET' && path === '/watch/context') return route.fulfill(json({ alerts: [{ id: 'alert-1', paper_instance_id: paperInstance.id, category: 'signal', severity: 'info', title: '新的 Paper 策略信号', message: 'SH_600519 order_target_percent=1', source_object_type: 'strategy_signal', source_object_id: 'signal-1', evidence: {}, status: 'active', triggered_at: now }], signals: paperInstance.signals, pool_moves: [{ snapshot_id: 11, pool_id: 'pool-1', pool_name: '动量 Top20', trade_date: '2025-01-02', member_count: 20, manifest_hash: 'pool-manifest' }], instances: [paperInstance], data_status: 'fresh', source_label: 'PostgreSQL audit records', source_updated_at: now, response_generated_at: now }));
    if (method === 'GET' && path === '/monitor/health') return route.fulfill(json({ status: 'healthy', services: [{ id: 1, service_code: 'paper_runtime', status: 'healthy', message: '周期处理成功', observed_at: now }], data: { dataset: { id: 10, status: 'sealed' }, market: { id: 3, status: 'published' } }, strategy_instances: [{ status: 'running', count: 1 }], risk_alerts: [], notifications: [{ status: 'delivered', count: 1 }], observed_at: now }));
    const reviewContext = { review: { id: 'review-1', trade_date: '2025-01-02', status: 'sealed', author_name: 'admin', summary: '全链路复盘', next_day_plan: '继续观察', source_manifest_hash: 'review-manifest' }, trade_date: '2025-01-02', status: 'sealed', source_manifest_hash: 'review-manifest', counts: { market: 1, pool: 1, strategy: 1, risk: 1, order: 1, trade: 1, performance: 1 }, metrics: [{ metric_code: 'limit_up_count', metric_value: 58, source_object_type: 'market_evidence_snapshot', source_object_id: '3', calculation_version: 'v1' }, { metric_code: 'limit_down_count', metric_value: 2, source_object_type: 'market_evidence_snapshot', source_object_id: '3', calculation_version: 'v1' }, { metric_code: 'highest_board', metric_value: 6, source_object_type: 'market_evidence_snapshot', source_object_id: '3', calculation_version: 'v1' }], items: [{ item_key: 'market', occurred_at: '2025-01-02T17:30:00+08:00', category: 'market', title: '市场证据 · post_close', summary: 'all_a · published', source_object_type: 'market_evidence_snapshot', source_object_id: '3', source_route: '/market', resolution_status: 'resolved', evidence: {}, evidence_hash: 'market-hash' }, { item_key: 'pool', occurred_at: '2025-01-02T17:31:00+08:00', category: 'pool', title: '股票池快照 · 动量 Top20', summary: '20 个固定成员', source_object_type: 'stock_pool_snapshot', source_object_id: '11', source_route: '/pools?tab=snapshots', resolution_status: 'resolved', evidence: {}, evidence_hash: 'pool-hash' }, { item_key: 'signal', occurred_at: '2025-01-02T15:00:00+08:00', category: 'strategy', title: '策略信号 · SH_600519 buy', summary: 'MA5', source_object_type: 'strategy_signal', source_object_id: 'signal-1', source_route: `/paper?tab=signals&instance=${paperInstance.id}`, resolution_status: 'resolved', evidence: {}, evidence_hash: 'signal-hash' }, { item_key: 'trade', occurred_at: '2025-01-02T09:30:00+08:00', category: 'trade', title: '模拟成交 · SH_600519 buy', summary: '100 股', source_object_type: 'trade', source_object_id: 'trade-1', source_route: `/paper?tab=orders&instance=${paperInstance.id}`, resolution_status: 'resolved', evidence: {}, evidence_hash: 'trade-hash' }] };
    if (method === 'GET' && path === '/review/dates') return route.fulfill(json({ items: ['2025-01-02'], total: 1 }));
    if (method === 'GET' && path === '/review/2025-01-02') return route.fulfill(json(reviewContext));
    if (method === 'POST' && path === '/review/2025-01-02/assemble') return route.fulfill(json(reviewContext));

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
  await expect(page.locator('[data-financial-operator-ui="true"]')).toBeVisible();
  await expect(page.locator('[data-operator-surface="auth"]')).toBeVisible();
});

test('single api shell keeps overview, research, strategy and admin navigation together', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/');

  await expect(page.getByText('StockPro AI').first()).toBeVisible();
  await expect(page.getByText('数据中台')).toHaveCount(0);
  await expect(page.getByText('研究工坊').first()).toBeVisible();
  await expect(page.getByText('策略工厂').first()).toBeVisible();

  await expect(page.getByRole('link', { name: /总览看板|Overview/ }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /市场研究|Market Research/ }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /股票池|Stock Pools/ }).first()).toBeVisible();
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

test('sidebar exposes exactly twelve ordered first-level workspaces', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/');

  const links = page.getByRole('complementary').locator('nav a');
  await expect(links).toHaveCount(12);
  await expect(links).toHaveText([
    /总览看板/,
    /市场研究/,
    /股票池/,
    /因子研究/,
    /策略开发/,
    /回测中心/,
    /AI 研发/,
    /模拟\/实盘交易/,
    /观察台/,
    /运行风控/,
    /复盘中心/,
    /管理后台/,
  ]);
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
  await expect(page.getByText('行情快照新鲜')).toBeVisible();
  await expect(page.getByText('量化交易中枢')).toHaveCount(0);
  const marketIndexSection = page.getByRole('heading', { name: '市场指数' }).locator('xpath=ancestor::section[1]');
  await expect(marketIndexSection).toBeVisible();
  const marketIndexXs = await Promise.all(
    topbarLabels.map(async (label) => (await marketIndexSection.getByText(label).boundingBox())?.x ?? 0),
  );
  expect(marketIndexXs).toEqual([...marketIndexXs].sort((left, right) => left - right));
});

test('top market ticker stays mounted and does not refetch on page tab changes', async ({ page }) => {
  let overviewRequestCount = 0;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/market/overview') overviewRequestCount += 1;
  });
  await loginAsAdmin(page);
  await page.goto('/strategy');

  const topbar = page.getByTestId('stockpro-ai-topbar');
  await expect(topbar.getByText('行情快照新鲜')).toBeVisible();
  await topbar.evaluate((element) => {
    element.setAttribute('data-lifecycle-probe', 'persistent');
  });
  const initialRequestCount = overviewRequestCount;

  await page.getByRole('link', { name: /回测中心/ }).click();
  await expect(page.getByRole('heading', { name: '回测实例控制台' })).toBeVisible();
  await expect(topbar).toHaveAttribute('data-lifecycle-probe', 'persistent');

  await page.getByRole('link', { name: /模拟\/实盘交易/ }).click();
  await expect(page.getByRole('heading', { name: '模拟交易控制台' })).toBeVisible();
  await expect(topbar).toHaveAttribute('data-lifecycle-probe', 'persistent');
  expect(overviewRequestCount).toBe(initialRequestCount);
});

test('all routed pages share the financial operator contract', async ({ page }) => {
  await loginAsAdmin(page);
  const routes = [
    '/',
    '/market',
    '/pools',
    '/factors',
    '/strategy',
    '/backtest',
    '/ai-lab',
    '/paper',
    '/watch',
    '/monitor',
    '/review',
    '/data',
    '/data/processing',
  ];

  for (const route of routes) {
    await page.goto(route);
    await expect(page.locator('[data-financial-operator-ui="true"]')).toBeVisible();
    await expect(page.getByTestId('financial-operator-shell')).toBeVisible();
    await expect(page.locator('[data-operator-surface="page"]')).toBeVisible();
    const bodyOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(bodyOverflow, `${route} should not overflow the document`).toBeLessThanOrEqual(1);
  }

});

test('financial operator shell remains usable on a mobile viewport', async ({ page }) => {
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/monitor');

  await expect(page.locator('[data-financial-operator-ui="true"]')).toBeVisible();
  await expect(page.getByRole('navigation', { name: '主工作流' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '监控中心' })).toBeVisible();
  const bodyOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(bodyOverflow).toBeLessThanOrEqual(1);
});

test('data-trust pages keep their state evidence usable at 390px', async ({ page }) => {
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const pages = [
    { path: '/', evidence: '未提供可比快照' },
    { path: '/paper', evidence: '回放心跳陈旧' },
    { path: '/review', evidence: '今日盘面复盘' },
    { path: '/data', evidence: '缓存同步质量诊断' },
  ];

  for (const item of pages) {
    await page.goto(item.path);
    await expect(page.getByText(item.evidence, { exact: true }).first()).toBeVisible();
    const bodyOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(bodyOverflow, `${item.path} should not overflow the mobile document`).toBeLessThanOrEqual(1);
  }
});

test('backtest center is separated from daily market review center', async ({ page }) => {
  await loginAsAdmin(page);

  await page.goto('/backtest');
  await expect(page.getByTestId('stockpro-ai-topbar').getByRole('heading', { name: '回测中心' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '回测实例控制台' })).toBeVisible();
  await expect(page.getByRole('button', { name: '创建回测实例' })).toBeVisible();
  await expect(page.getByTestId('backtest-job-console')).toContainText('任务队列');
  await expect(page.getByRole('button', { name: '结果证据' })).toBeVisible();
  await page.getByRole('button', { name: '任务日志' }).click();
  await expect(page.getByTestId('backtest-job-console')).toContainText('回测完成，结果证据已封存');
  await expect(page.getByText('StockPro Strategy API v1')).toHaveCount(0);

  await page.goto('/review');
  await expect(page.getByTestId('stockpro-ai-topbar').getByRole('heading', { name: '复盘中心' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '今日盘面复盘' })).toBeVisible();
  await expect(page.getByText('涨停数')).toBeVisible();
  await expect(page.getByRole('heading', { name: '板块轮动' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '连板梯队' })).toBeVisible();
  await page.getByRole('button', { name: '日志', exact: true }).click();
  await expect(page.getByRole('heading', { name: '复盘结论' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '交易日时间线' })).toBeVisible();
});

test('backtest result exposes six core cards and eight evidence tabs', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/backtest/66666666-6666-6666-6666-666666666666');

  await expect(page.getByRole('heading', { name: 'MA5 完整回测' })).toBeVisible();
  for (const label of ['策略收益', '年化收益', '基准收益', '超额收益', '最大回撤', '夏普比率']) {
    await expect(page.getByText(label, { exact: true })).toBeVisible();
  }
  for (const tab of ['总览', '收益分析', '持仓', '交易', '订单', '日志', '代码与参数', '归因']) {
    await expect(page.getByRole('tab', { name: tab })).toBeVisible();
  }
  await page.getByRole('tab', { name: '代码与参数' }).click();
  await expect(page.getByText('策略代码 · v1')).toBeVisible();
});

test('market research exposes exactly six evidence workspaces and legacy redirects', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/research/overview');
  await expect(page).toHaveURL(/\/market\?tab=structure$/);
  await expect(page.getByRole('heading', { name: '市场研究工作台' })).toBeVisible();
  await expect(page.getByTestId('market-headline-rise_count')).toContainText('3,200');
  await expect(page.getByTestId('market-headline-rise_count')).not.toContainText('stocks');
  await expect(page.getByTestId('market-headline-rise_count').locator('.bp-metric-card')).toHaveClass(/border-red-500/);
  await expect(page.getByTestId('market-headline-fall_count').locator('.bp-metric-card')).toHaveClass(/border-emerald-500/);
  await expect(page.getByTestId('market-headline-seal_rate')).toContainText('86.15%');
  for (const label of ['市场结构', '板块轮动', '情绪 / 涨停', '事件', '交易日历', '个股研究']) {
    await expect(page.getByRole('button', { name: label })).toBeVisible();
  }
  await expect(page.getByText('市场数据快照')).toBeVisible();
  await page.getByRole('button', { name: '情绪 / 涨停' }).click();
  await expect(page.getByText('连板天梯')).toBeVisible();
  await expect(page.getByText('5+板')).toBeVisible();
  await expect(page.getByText(/不发布：缺少/)).toBeVisible();

  const datedLeaderRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.endsWith('/market/hot-concept/leaders') && url.searchParams.get('date') === '2025-01-02';
  });
  await page.getByRole('button', { name: '个股研究' }).click();
  await datedLeaderRequest;
  await expect(page.getByText('研究截止 2025-01-02 · K线至 2025-01-02')).toBeVisible();
  await expect(page.getByText('共 2 根K线')).toBeVisible();
  await expect(page.getByText('2026-06-03', { exact: true })).toHaveCount(0);

  await page.goto('/sentiment');
  await expect(page).toHaveURL(/\/market\?tab=sentiment$/);
  await page.goto('/news');
  await expect(page).toHaveURL(/\/market\?tab=events$/);
  await page.goto('/calendar');
  await expect(page).toHaveURL(/\/market\?tab=calendar$/);
  await page.goto('/ai');
  await expect(page).toHaveURL(/\/market\?tab=stock&panel=ai$/);
});

test('stock-pool snapshot carries evidence into a backtest draft without copied symbols', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/pools?tab=factor');
  await expect(page.getByRole('heading', { name: '股票池研究工作台' })).toBeVisible();
  for (const label of ['我的股票池', '条件选股', '因子股票池', '板块股票池', '事件股票池', '快照仓库']) {
    await expect(page.getByRole('button', { name: label })).toBeVisible();
  }
  const evidencePanel = page.getByRole('heading', { name: '当前成员证据' }).locator('xpath=ancestor::section[1]');
  await expect(evidencePanel.getByText('Factor #3')).toBeVisible();
  await expect(evidencePanel.getByText(/Market #/)).toHaveCount(0);
  await expect(page.getByText('20日动量排名 1')).toBeVisible();
  await expect(page.getByText('600519.SH', { exact: true })).toBeVisible();
  await page.getByTestId('generate-pool').click();
  await expect(page.getByText(/生成 2 只/)).toBeVisible();
  await page.getByTestId('seal-pool').click();
  await expect(page.getByText(/快照 #11 已封存/)).toBeVisible();
  await page.getByTestId('pool-tab-snapshots').click();
  await expect(page.getByTestId('pool-snapshot-table')).toBeVisible();
  await page.getByTestId('pool-backtest-11').click();
  await expect(page).toHaveURL(/\/backtest\?poolSnapshotId=11&experimentId=experiment-1$/);
  await expect(page.locator('label').filter({ has: page.getByText('股票池快照', { exact: true }) }).locator('select')).toHaveValue('11');
  await expect(page.locator('input[value="股票池快照 #11"]')).toBeVisible();
});

test('stock-pool catalogue survives optional market-evidence failure', async ({ page }) => {
  await page.route('**/api/market/research-context**', (route) => route.fulfill(json({ detail: 'market evidence unavailable' }, 400)));
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/pools');

  await expect(page.getByRole('heading', { name: '版本化股票池' })).toBeVisible();
  await expect(page.getByRole('button', { name: /动量 Top20/ })).toBeVisible();
  await expect(page.getByText('部分数据降级')).toBeVisible();
  await expect(page.getByText(/市场证据暂不可用/)).toBeVisible();
  await expect(page.getByText('600519.SH', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
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
  await expect(page.getByText('单位未记录').first()).toBeVisible();
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

test('dashboard marks stale market caches and never presents them as current signals', async ({ page }) => {
  const staleAt = '2025-01-02T15:00:00+08:00';
  await page.route('**/api/market/hot-concepts**', (route) => route.fulfill(json([
    { rank: 1, name: '陈旧概念', change_percent: 6.1, net_inflow: 200000000, updated_at: staleAt },
  ])));
  await page.route('**/api/market/ths-hot**', (route) => route.fulfill(json([
    { rank: 1, code: '600000', name: '陈旧强势股', change_percent: 9.9, updated_at: staleAt },
  ])));
  await page.route('**/api/market/short-line-indices**', (route) => route.fulfill(json([
    { code: 'ZT', name: '涨停家数', price: 42, change_percent: 0, change_amount: 0, updated_at: staleAt },
  ])));
  await loginAsAdmin(page);
  await page.goto('/');

  await expect(page.getByText('热榜缓存已陈旧')).toBeVisible();
  await expect(page.getByText('陈旧强势股')).toHaveCount(0);
  await expect(page.getByText('当前接口未提供历史可比值')).toBeVisible();
  await expect(page.getByText(/陈旧缓存/).first()).toBeVisible();
});

test('dashboard falls back to sealed short-line evidence without calling it realtime', async ({ page }) => {
  const sealed = {
    updated_at: '2026-07-16T14:15:08+00:00',
    trade_date: '2025-01-02',
    snapshot_id: 7,
    data_state: 'sealed_snapshot',
    source_label: 'tushare_limit_list_derived',
    change_percent: null,
    change_amount: null,
    comparison_state: 'unavailable',
  };
  await page.route('**/api/market/short-line-indices**', (route) => route.fulfill(json([
    { ...sealed, code: 'limit_up_count', name: '涨停数', price: 58, unit: 'stocks', definition: '涨停池去重证券数' },
    { ...sealed, code: 'limit_down_count', name: '跌停数', price: 13, unit: 'stocks', definition: '跌停池去重证券数' },
    { ...sealed, code: 'broken_board_count', name: '炸板数', price: 35, unit: 'stocks', definition: '盘中触板但收盘未封板证券数' },
    { ...sealed, code: 'highest_board', name: '最高板', price: 6, unit: 'boards', definition: '涨停池最大连续涨停天数' },
  ])));
  await loginAsAdmin(page);
  await page.goto('/');

  await expect(page.getByText('历史快照 · 2025-01-02')).toBeVisible();
  await expect(page.getByText('历史收盘证据 · 2025-01-02')).toBeVisible();
  await expect(page.getByText('涨停池去重证券数')).toBeVisible();
  await expect(page.getByText('6').filter({ hasText: '板' })).toBeVisible();
  await expect(page.getByText('异动监控')).toHaveCount(0);
});

test('primary pages expose usable A-share research workflow anchors', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await loginAsAdmin(page);
  await page.setViewportSize({ width: 1440, height: 960 });

  const pages = [
    { path: '/', title: '实时大盘', anchors: ['市场指数', '短线指标', '热门板块'] },
    { path: '/market', title: '市场概览', anchors: ['市场研究工作台', '市场数据快照', '涨停数'] },
    { path: '/pools', title: '股票池研究', anchors: ['股票池研究工作台', '版本化股票池', '当前成员与入选证据'] },
    { path: '/factors', title: '因子研究', anchors: ['因子研究工作台', '因子库', '20日动量'] },
    { path: '/strategy', title: '策略开发', anchors: ['策略中心', 'A股策略约束', '100股整数手'] },
    { path: '/backtest', title: '回测中心', anchors: ['回测实例控制台', '创建回测实例', '回测实例'] },
    { path: '/ai-lab', title: 'AI 研发', anchors: ['AI 研发实验室', 'AI 生成不可用', '策略助手', '受控边界'] },
    { path: '/review', title: '复盘中心', anchors: ['今日盘面复盘', '板块轮动', '连板梯队'] },
    { path: '/paper', title: '模拟交易', anchors: ['策略实例、风险控制、订单成交与账户权益。', '实盘前置约束', 'T+1 / 100股'] },
    { path: '/watch', title: '观察台', anchors: ['观察台', '集中观察策略信号', '最新策略信号'] },
    { path: '/monitor', title: '运行风控', anchors: ['监控中心', '运行风控检查', '涨跌停风险'] },
    { path: '/data', title: '管理后台', anchors: ['数据管理中心', '同步覆盖矩阵', 'A股数据维护面板'] },
    { path: '/data/processing', title: '管理后台', anchors: ['数据资产', '生产任务', '质量治理'] },
  ];
  const forbiddenCopy = [
    'PG 策略定义 / 不可变版本',
    'Strategy API v1',
    'Provider-free Read',
    '列表读取不访问行情 provider',
    'PG-only',
    '数据库触发器禁止修改',
    '显式写操作',
    'Recorded Replay',
  ];

  for (const item of pages) {
    await page.goto(item.path);
    await expect(page.getByTestId('stockpro-ai-topbar').getByRole('heading', { name: item.title })).toBeVisible();
    for (const anchor of item.anchors) {
      await expect(page.getByText(anchor).first(), `${item.path} should show ${anchor}`).toBeVisible();
    }
    for (const copy of forbiddenCopy) {
      await expect(page.getByText(copy, { exact: false }), `${item.path} should not expose ${copy}`).toHaveCount(0);
    }
  }

  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('paper watch and monitor keep separate operator ownership', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/paper');
  for (const label of ['实例', '信号', '订单', '持仓', '账户', '事件']) await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
  await page.goto('/watch');
  for (const label of ['策略信号', '股票池变动', '图表联动', '告警']) await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
  await page.goto('/monitor');
  for (const label of ['总览', '策略健康', '数据健康', '风险', '通知']) await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
});

test('strategy backtest and paper expose the A-share operator workflow without implementation notes', async ({ page }) => {
  await loginAsAdmin(page);

  await page.goto('/strategy');
  await expect(page.getByText('PG 策略定义 / 不可变版本')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '策略中心' })).toBeVisible();

  await page.goto('/backtest');
  await expect(page.getByText('PG 封存研究输入 / Provider-free Read')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '回测实例控制台', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /完整回测/ })).toBeVisible();
  await expect(page.getByLabel('回测排序')).toBeVisible();

  await page.getByRole('button', { name: '创建回测实例' }).click();
  await expect(page.getByRole('dialog', { name: '创建回测实例' })).toBeVisible();
  await expect(page.getByText('选择不可变策略版本')).toBeVisible();
  await page.getByRole('button', { name: /MA5 趋势策略/ }).click();
  await page.getByRole('button', { name: '下一步' }).click();
  await expect(page.getByText('设置区间与研究输入')).toBeVisible();
  await page.getByRole('button', { name: '下一步' }).click();
  await expect(page.getByText('实验配置确认')).toBeVisible();
  await expect(page.getByText('参数矩阵', { exact: true })).toBeVisible();

  await page.goto('/paper');
  await expect(page.getByRole('heading', { name: '模拟交易控制台' })).toBeVisible();
  await expect(page.getByText('当前模式：模拟交易')).toBeVisible();
  await page.getByRole('button', { name: '成交', exact: true }).click();
  await expect(page.getByText('SH_600519')).toBeVisible();
  await page.getByRole('button', { name: '账户', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Paper 权益曲线' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '运行证据与风控' })).toBeVisible();
  await expect(page.getByText('历史数据快照', { exact: true }).first()).toBeVisible();
});

test('strategy lifecycle uses one capabilities-first rail and does not imply live trading', async ({ page }) => {
  await loginAsAdmin(page);

  for (const path of ['/strategy', '/backtest', '/paper', '/watch', '/monitor', '/review']) {
    await page.goto(path);
    const rail = page.getByTestId('workflow-rail');
    await expect(rail).toBeVisible();
    await expect(rail.getByText('仅模拟盘')).toBeVisible();
    await expect(rail.getByText('实盘未接入')).toBeVisible();
    for (const label of ['策略', '回测', '模拟', '观察', '监控', '复盘']) {
      await expect(rail.getByRole('link', { name: label, exact: true })).toBeVisible();
    }
  }

  await expect(page.getByRole('link', { name: '模拟交易', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '模拟/实盘交易', exact: true })).toHaveCount(0);
});

test('paper running state is downgraded when the recorded replay heartbeat is missing', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/paper');

  await expect(page.getByText('回放心跳陈旧')).toBeVisible();
  await expect(page.getByText('心跳 --')).toBeVisible();
});

test('watch separates load failure from a legitimate empty signal set', async ({ page }) => {
  await page.route('**/api/watch/context', (route) => route.fulfill(json({ detail: 'watch unavailable' }, 503)));
  await loginAsAdmin(page);
  await page.goto('/watch');

  await expect(page.getByText('模拟交易 / 告警 / 股票池')).toBeVisible();
  await expect(page.getByText('加载失败', { exact: true })).toBeVisible();
  await expect(page.getByText('数据加载失败')).toBeVisible();
});

test('monitor keeps counters unavailable when its health snapshot fails', async ({ page }) => {
  await page.route('**/api/monitor/health', (route) => route.fulfill(json({ detail: 'monitor unavailable' }, 503)));
  await loginAsAdmin(page);
  await page.goto('/monitor');

  await expect(page.getByText('服务健康与审计记录')).toBeVisible();
  await expect(page.getByText('加载失败', { exact: true })).toBeVisible();
  for (const label of ['策略实例', '活动风险告警', '通知投递']) {
    await expect(page.getByText(label).locator('..').getByText('--')).toBeVisible();
  }
});

test('ai lab exposes research state and a real load error', async ({ page }) => {
  await page.route('**/api/strategy/list', (route) => route.fulfill(json({ detail: 'strategy unavailable' }, 503)));
  await loginAsAdmin(page);
  await page.goto('/ai-lab');

  await expect(page.getByText('策略版本 / 回测记录')).toBeVisible();
  await expect(page.getByText('加载失败', { exact: true })).toBeVisible();
});

test('daily review exposes five evidence workspaces and a sealed audit timeline', async ({ page }) => {
  const assembleRequests: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/api/review/2025-01-02/assemble')) assembleRequests.push(request.url());
  });
  await loginAsAdmin(page);
  await page.goto('/review?date=2025-01-02&tab=logs');

  await expect(page.getByTestId('daily-review-workbench')).toBeVisible();
  for (const label of ['市场复盘', '股票池复盘', '策略复盘', '交易复盘', '日志']) {
    await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
  }
  await expect(page.getByRole('heading', { name: '交易日时间线' })).toBeVisible();
  await expect(page.getByText('复盘已封存，不可修改')).toBeVisible();
  await expect(page.getByText('review-manifest')).toHaveCount(0);
  await expect(page.getByText('查看关联记录 →').first()).toBeVisible();
  expect(assembleRequests).toHaveLength(0);
  await page.getByRole('button', { name: '重建时间线' }).click();
  await expect.poll(() => assembleRequests.length).toBe(1);
});

test('daily review keeps metrics unavailable when evidence assembly fails', async ({ page }) => {
  await page.route('**/api/review/2025-01-02', (route) => route.fulfill(json({ detail: 'fixture failure' }, 503)));
  await loginAsAdmin(page);
  await page.goto('/review?date=2025-01-02');

  await expect(page.getByText('加载失败', { exact: true })).toBeVisible();
  for (const label of ['涨停数', '跌停数', '最高连板', '股票池快照', '策略信号', '风险 / 成交']) {
    await expect(page.getByTestId(`review-metric-${label}`).getByText('--')).toBeVisible();
  }
  await expect(page.getByRole('button', { name: '保存草稿' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '封存复盘' })).toHaveCount(0);
});

test('data center separates cache coverage from sealed research readiness', async ({ page }) => {
  await page.route('**/api/data/status', (route) => route.fulfill(json({
    status: 'ready',
    database: 'postgresql',
    tables: [{ name: 'kline_history', rows: 999999 }],
    kline_coverage: [{ symbol: '600000.SH', name: '浦发银行', timeframe: '1d', rows: 100, first_date: '2024-01-02', last_date: '2025-01-02' }],
    sync_jobs: [{ id: 1, job_name: 'daily-cache', status: 'completed', total_items: 1, completed_items: 1, failed_items: 0, created_at: '2025-01-02T18:00:00+08:00' }],
  })));
  await page.route('**/api/data/datasets', (route) => route.fulfill(json({ items: [{ code: 'daily_bars', name: '日线', primary_source: 'tushare', fallback_source: 'akshare', actual_source: 'tushare', response_hash: 'daily-hash', schema_version: 'v1', enabled: true, end_date: '2025-01-02', row_count: 999999, symbol_count: 1, partition_status: 'published', blocking_issues: 0 }] })));
  await page.route('**/api/data/snapshots**', (route) => route.fulfill(json({ items: [{ id: 9, name: 'snapshot-2025-01-02', status: 'sealed', knowledge_cutoff_at: '2025-01-02T15:00:00+08:00', created_at: '2025-01-02T18:00:00+08:00', partition_count: 1 }] })));
  await page.route('**/api/data/schedules/daily', (route) => route.fulfill(json({
    code: 'daily_reference_publication', configured: true, cron: '30 17 * * 1-5', timezone: 'Asia/Shanghai', enabled: true,
    catchupDays: 5, maxRetries: 3, dailyBarsWatermark: '2025-01-02', nextRunAt: '2025-01-03T17:30:00+08:00',
    configuredNextRunAt: '2025-01-03T17:30:00+08:00', runtimeEnabled: false, runnerOnline: false, jobRegistered: false,
    effectiveNextRunAt: null, runtimeStatus: 'runner_offline',
    lastRun: { id: 40, tradeDate: '2025-01-02', status: 'sealed', snapshotId: 9, attemptCount: 1, finishedAt: '2025-01-02T18:00:00+08:00', result: { publication: { actual_source: 'tushare', response_hash: 'daily-hash', snapshot: { id: 9 } }, factorSchedule: { status: 'sealed', factor_snapshot: { id: 3 } }, marketEvidence: { status: 'restricted' } } },
  })));
  await loginAsAdmin(page);
  await page.goto('/data');

  await expect(page.getByText('999,999', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('日线全表统计')).toBeVisible();
  await expect(page.getByText('研究快照历史 · #9')).toBeVisible();
  await expect(page.getByText(/数据快照 9 · 实际来源 tushare/)).toBeVisible();
  await expect(page.getByText(/因子 sealed · 因子快照 3 · 市场证据 restricted/)).toBeVisible();
  await expect(page.getByText('响应哈希 daily-hash')).toHaveCount(0);
  await expect(page.getByText('可回测', { exact: true })).toHaveCount(0);
  await expect(page.getByText(/接口返回样本，不代表全量标的/)).toBeVisible();
  await expect(page.getByText('配置已启用 · 运行器未启动')).toBeVisible();
  await expect(page.getByText(/配置时间不会自动执行/)).toBeVisible();
});

test('factor research exposes six PG-backed workspaces and explicit pending evidence', async ({ page }) => {
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/factors');

  await expect(page.getByText('因子研究工作台')).toBeVisible();
  for (const label of ['因子库', '计算运行', '单因子分析', '多因子分析', '相关性与暴露', '因子值']) {
    await expect(page.getByRole('button', { name: label })).toBeVisible();
  }
  await expect(page.getByTestId('factor-research-summary')).toBeVisible();
  await expect(page.getByText('DS #9', { exact: true })).toBeVisible();
  await expect(page.getByText('Universe #1', { exact: true })).toBeVisible();
  await expect(page.getByText(/历史样本/)).toBeVisible();
  await expect(page.getByText('未来收益窗口尚未成熟，不用 0 填充')).toBeVisible();
  await expect(page.getByText('待成熟').first()).toBeVisible();

  await page.getByText('20日动量').first().click();
  await expect(page).toHaveURL(/\/factors\/61$/);
  await expect(page.getByText('研究协议：探索性 · 未绑定协议')).toBeVisible();
  await expect(page.getByText('未来收益评估待成熟')).toBeVisible();

  await page.getByRole('button', { name: '因子值' }).click();
  await expect(page.getByText('600000.SH')).toBeVisible();
  await expect(page.getByText('点时因子值')).toBeVisible();
});

test('factor research keeps core library usable when optional correlation data fails', async ({ page }) => {
  await page.route('**/api/factor-correlations**', (route) => route.fulfill({
    status: 400,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'correlation fixture unavailable' }),
  }));
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/factors');

  await expect(page.getByText('20日动量').first()).toBeVisible();
  await expect(page.getByText('部分数据降级')).toBeVisible();
  await expect(page.getByText(/相关矩阵暂不可用/)).toBeVisible();
  await expect(page.getByTestId('factor-research-summary')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
});

test('strategy editor saves and quick-runs lifecycle Python without a framework class', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/strategy');

  await page.getByRole('button', { name: '新建策略' }).click();
  await expect(page.getByRole('heading', { name: 'Python 生命周期策略' })).toBeVisible();
  await expect(page.getByText(/编写初始化与交易逻辑/)).toBeVisible();
  await page.getByLabel('策略名称').fill('生命周期策略');
  await expect(page.getByLabel('策略代码')).toHaveValue(/def initialize\(context\)/);
  await page.getByRole('button', { name: '保存并快速运行' }).click();

  await expect(page.getByText('策略校验通过')).toBeVisible();
  await expect(page.getByText(/20 个交易日 · 12 个委托意图 · 20 条指标/)).toBeVisible();
  await expect(page.getByText(/快速运行完成：12 条委托意图/)).toBeVisible();
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
