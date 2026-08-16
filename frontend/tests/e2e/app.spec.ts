import { BrowserContext, expect, Page, test } from '@playwright/test';

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

async function mockApi(context: BrowserContext) {
  await context.route('**/*', async (route) => {
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

    if (method === 'GET' && path === '/auth/me') {
      return route.fulfill(json({
        role: 'admin',
        username: 'admin',
        permissions: ['read', 'write', 'admin'],
      }));
    }

    if (method === 'GET' && path === '/auth/guest-codes') {
      return route.fulfill(json({ items: [] }));
    }

    if (method === 'GET' && path === '/auth/mcp-agent-tokens') {
      return route.fulfill(json({
        items: [{
          id: 7,
          name: 'Research Agent',
          token_hint: 'sp_mcp_abcd…7890',
          scopes: ['R', 'W'],
          created_by: 'admin',
          created_at: now,
          last_used_at: now,
          revoked_at: null,
        }],
      }));
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

    if (method === 'GET' && path === '/market/sector-fund-flow') {
      return route.fulfill(json({
        limit: 30,
        unit: '亿',
        inflows: [
          { rank: 1, name: '低空经济', change_percent: 6.1, net_inflow_yi: 2.0, inflow_yi: 3.0, outflow_yi: 1.0 },
        ],
        outflows: [
          { rank: 2, name: '机器人', change_percent: 1.7, net_inflow_yi: -0.5, inflow_yi: 0.5, outflow_yi: 1.0 },
        ],
        rankings: [
          { rank: 1, name: '低空经济', change_percent: 6.1, net_inflow_yi: 2.0 },
          { rank: 2, name: '机器人', change_percent: 1.7, net_inflow_yi: -0.5 },
        ],
        updated_at: now,
        data_status: 'fresh',
        source_label: 'PostgreSQL hot_concepts_realtime',
        methodology: '按板块主力净流入排序；连线按流入侧权重分摊。',
      }));
    }

    if (method === 'GET' && path === '/market/limit-board') {
      return route.fulfill(json({
        trade_date: '2025-01-02',
        snapshot_id: 1,
        captured_at: now,
        data_status: 'fresh',
        source_label: 'market_evidence limit_pool_members',
        counts: { up: 2, down: 1 },
        up: [
          { symbol: '000017.SZ', code: '000017', name: '深中华A', pool_kind: 'up', price: 3.45, change_percent: 10.02, limit_times: 2, industry: '商业百货' },
          { symbol: '600000.SH', code: '600000', name: '浦发银行', pool_kind: 'up', price: 10.2, change_percent: 9.99, limit_times: 1, industry: '银行' },
        ],
        down: [
          { symbol: '000001.SZ', code: '000001', name: '平安银行', pool_kind: 'down', price: 8.1, change_percent: -10.01, limit_times: 1, industry: '银行' },
        ],
        methodology: '优先读取封存市场证据 limit_pool_members。',
      }));
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
        protocols: [{ id: '55555555-5555-5555-5555-555555555555', name: '样本外研究协议', hypothesis: '趋势溢价', status: 'sealed', benchmark_code: '000300.SH', train_start: '2023-01-03', train_end: '2023-12-29', validation_start: '2024-01-08', validation_end: '2024-06-28', out_of_sample_start: '2024-07-08', out_of_sample_end: '2025-01-02', embargo_days: 7, capacity_rules: { max_participation_ratio: 0.1, max_single_symbol_weight: 0.25 }, promotion_thresholds: { min_return: 0, min_sharpe: 0.5, max_drawdown: 0.2 } }],
      }));
    }

    const mockBacktestRun = {
      id: '66666666-6666-6666-6666-666666666666', name: 'MA5 完整回测', status: 'success', run_mode: 'full', progress: 100,
      promotion_status: 'paper_eligible', strategy_version_id: '22222222-2222-2222-2222-222222222222', strategy_name: 'MA5 趋势策略', strategy_version: 1,
      script_content: 'def initialize(context):\n    pass\n', strategy_content_hash: 'strategy-content-hash', dataset_snapshot_id: 10,
      factor_snapshot_id: 3, pool_snapshot_id: 11, universe_snapshot_id: 1, research_protocol_id: '55555555-5555-5555-5555-555555555555', protocol_name: '样本外研究协议',
      cost_model_id: '44444444-4444-4444-4444-444444444444', cost_model_name: 'A股默认成本', benchmark_code: '000300.SH',
      start_date: '2023-01-03', end_date: '2025-01-02', initial_cash: 1000000, parameters: {}, universe: { symbols: ['SH_600519'] },
      metrics: { strategy_return: 0.12, annualized_return: 0.06, benchmark_return: 0.04, excess_return: 0.08, maximum_drawdown: 0.09, sharpe: 1.23, total_cost: 128.5, peak_single_symbol_weight: 0.2, capacity_warnings: 0, data_quality_warnings: 0 },
      input_hash: 'input-hash-abcdef', result_manifest: { manifest_hash: 'result-manifest-abcdef' }, created_at: '2025-01-02T18:00:00+08:00',
      data_purpose: 'user',
      protocol: { id: '55555555-5555-5555-5555-555555555555', name: '样本外研究协议', status: 'sealed', benchmark_code: '000300.SH', train_start: '2023-01-03', train_end: '2023-12-29', validation_start: '2024-01-08', validation_end: '2024-06-28', out_of_sample_start: '2024-07-08', out_of_sample_end: '2025-01-02', embargo_days: 7, capacity_rules: { max_participation_ratio: 0.1, max_single_symbol_weight: 0.25 }, promotion_thresholds: { min_return: 0, min_sharpe: 0.5, max_drawdown: 0.2 } },
      protocol_evaluations: [{ sample_label: 'train', status: 'passed', start_date: '2023-01-03', end_date: '2023-12-29', metrics: { strategy_return: 0.08, sharpe: 1.1, maximum_drawdown: 0.08 } }, { sample_label: 'validation', status: 'passed', start_date: '2024-01-08', end_date: '2024-06-28', metrics: { strategy_return: 0.03, sharpe: 0.9, maximum_drawdown: 0.07 } }, { sample_label: 'out_of_sample', status: 'passed', start_date: '2024-07-08', end_date: '2025-01-02', metrics: { strategy_return: 0.04, sharpe: 0.8, maximum_drawdown: 0.09 } }],
      promotion_checks: ['FULL_SEALED_RUN', 'SEALED_PROTOCOL', 'TRAIN_PASS', 'VALIDATION_PASS', 'OUT_OF_SAMPLE_PASS', 'COST_MODEL_PASS', 'CAPACITY_RULES_DEFINED', 'CAPACITY_PASS', 'PROMOTION_THRESHOLDS_DEFINED', 'BENCHMARK_PASS', 'DATA_QUALITY_PASS'].map((check_code) => ({ check_code, status: 'passed', evidence: {} })),
      promotion_gate_complete: true,
      capacity_evidence: { peak_capacity_ratio: 0.05 },
    };
    const mockQuickBacktestRun = {
      ...mockBacktestRun,
      id: '99999999-9999-9999-9999-999999999999',
      name: 'MA5 快速预检',
      run_mode: 'quick',
      promotion_status: 'not_eligible_quick',
      protocol_evaluations: [],
      promotion_checks: [],
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
    if (method === 'GET' && path === '/backtest/runs') return route.fulfill(json({ items: [mockBacktestRun, mockQuickBacktestRun], total: 2 }));
    if (method === 'GET' && path === `/backtest/runs/${mockBacktestRun.id}`) return route.fulfill(json({ ...mockBacktestRun, core_metrics: mockMetrics }));
    if (method === 'GET' && path === `/backtest/runs/${mockQuickBacktestRun.id}`) return route.fulfill(json({ ...mockQuickBacktestRun, core_metrics: mockMetrics }));
    if (method === 'GET' && path === `/backtest/runs/${mockBacktestRun.id}/metrics`) return route.fulfill(json({ items: mockMetrics }));
    if (method === 'GET' && path === `/backtest/runs/${mockQuickBacktestRun.id}/metrics`) return route.fulfill(json({ items: mockMetrics }));
    if (method === 'GET' && path === `/backtest/runs/${mockBacktestRun.id}/series`) return route.fulfill(json({ daily: [{ trade_date: '2025-01-01', strategy_nav: 1, benchmark_nav: 1, excess_nav: 1, equity: 1000000, cash: 1000000, market_value: 0, gross_exposure: 0, position_count: 0, drawdown: 0 }, { trade_date: '2025-01-02', strategy_nav: 1.12, benchmark_nav: 1.04, excess_nav: 1.0769, equity: 1120000, cash: 100000, market_value: 1020000, gross_exposure: 0.91, position_count: 1, drawdown: 0 }], custom_records: [], monthly_returns: [{ month: '2025-01', return: 0.12 }, { month: '2025-02', return: -0.04 }, { month: '2025-03', return: 0 }] }));
    if (method === 'GET' && path === `/backtest/runs/${mockQuickBacktestRun.id}/series`) return route.fulfill(json({ daily: [{ trade_date: '2025-01-02', strategy_nav: 1, benchmark_nav: 1, excess_nav: 1, equity: 1000000, cash: 1000000, market_value: 0, gross_exposure: 0, position_count: 0, drawdown: 0 }], custom_records: [], monthly_returns: [] }));
    if (method === 'GET' && new RegExp(`^/backtest/runs/${mockBacktestRun.id}/(positions|orders|trades|logs|attribution)$`).test(path)) return route.fulfill(json({ items: [] }));
    if (method === 'GET' && new RegExp(`^/backtest/runs/${mockQuickBacktestRun.id}/(positions|orders|trades|logs|attribution)$`).test(path)) return route.fulfill(json({ items: [] }));
    if (method === 'POST' && path === '/backtest/runs') return route.fulfill(json(mockBacktestRun));

    const mockPool = { id: 'pool-1', name: '动量 Top20', pool_type: 'factor', description: 'fixture', status: 'active', data_purpose: 'user', rule_id: 'rule-1', rule_type: 'factor', rule_version: 1, config: { factor_code: 'momentum_20d', top_n: 20 }, rule_hash: 'rule-hash-abcdef', snapshot_count: 1, current_member_count: 2, latest_generation_id: 'generation-1', latest_dataset_snapshot_id: 10, latest_universe_snapshot_id: 1, latest_factor_snapshot_id: 3, latest_market_evidence_snapshot_id: null, latest_trade_date: '2025-01-02', latest_knowledge_cutoff_at: now, latest_input_hash: 'input-hash' };
    const mockMembers = [{ ordinal: 1, symbol: 'SH_600519', score: 1, reason: '20日动量排名 1', evidence: { factor_snapshot_id: 3 }, evidence_hash: 'member-hash-1', valid_from: '2025-01-02', valid_until: '2025-01-07', generator_version: 'stock-pool-generator.v1' }, { ordinal: 2, symbol: 'SZ_000333', score: 0.95, reason: '20日动量排名 2', evidence: { factor_snapshot_id: 3 }, evidence_hash: 'member-hash-2', valid_from: '2025-01-02', valid_until: '2025-01-07', generator_version: 'stock-pool-generator.v1' }];
    const mockPoolSnapshot = { id: 11, pool_id: 'pool-1', pool_name: '动量 Top20', pool_type: 'factor', data_purpose: 'user', trade_date: '2025-01-02', valid_until: '2025-01-07', dataset_snapshot_id: 10, universe_snapshot_id: 1, factor_snapshot_id: 3, knowledge_cutoff_at: now, manifest_hash: 'pool-manifest-abcdef', member_count: 2, status: 'sealed' };
    const mockAuditPoolSnapshot = { ...mockPoolSnapshot, id: 99, pool_id: 'pool-audit', pool_name: '验收探针池', data_purpose: 'acceptance', manifest_hash: 'audit-pool-manifest' };
    if (method === 'GET' && path === '/pools') return route.fulfill(json({ items: [mockPool], total: 1 }));
    if (method === 'POST' && path === '/pools') return route.fulfill(json(mockPool));
    if (method === 'GET' && path === '/pools/pool-1/members') return route.fulfill(json({ items: mockMembers, total: 2 }));
    if (method === 'POST' && path === '/pools/pool-1/generate') return route.fulfill(json({ id: 'generation-1', pool_id: 'pool-1', status: 'success', trade_date: '2025-01-02', input_hash: 'input-hash', member_manifest_hash: 'member-manifest', member_count: 2, members: mockMembers, reused: false }));
    if (method === 'POST' && path === '/pools/pool-1/snapshots') return route.fulfill(json(mockPoolSnapshot));
    if (method === 'GET' && path === '/pool-snapshots') return route.fulfill(json({ items: [mockPoolSnapshot, mockAuditPoolSnapshot], total: 2 }));
    if (method === 'POST' && path === '/pool-snapshots/11/backtests') return route.fulfill(json({ status: 'draft', experiment: { id: 'experiment-1', pool_snapshot_id: 11 }, pool_snapshot: mockPoolSnapshot }));

    if (method === 'GET' && path === '/paper/accounts') {
      return route.fulfill(json({ accounts: [], total: 0 }));
    }

    const paperInstance = {
      id: '77777777-7777-7777-7777-777777777777', name: 'MA5 / Paper', status: 'running', data_purpose: 'user',
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
    if (method === 'GET' && path === '/watch/context') return route.fulfill(json({
      alerts: [{ id: 'alert-1', paper_instance_id: paperInstance.id, category: 'signal', severity: 'info', title: '新的 Paper 策略信号', message: 'SH_600519 order_target_percent=1', source_object_type: 'strategy_signal', source_object_id: 'signal-1', evidence: {}, status: 'active', triggered_at: now }],
      signals: paperInstance.signals,
      orders: paperInstance.orders.map((item) => ({ ...item, paper_instance_id: paperInstance.id, instance_name: paperInstance.name, filled_quantity: item.quantity, order_type: 'limit' })),
      trades: paperInstance.trades.map((item) => ({ ...item, paper_instance_id: paperInstance.id, instance_name: paperInstance.name })),
      positions: paperInstance.positions.map((item) => ({ ...item, paper_instance_id: paperInstance.id, instance_name: paperInstance.name, updated_at: now })),
      risk_events: [{ id: 'risk-1', paper_instance_id: paperInstance.id, instance_name: paperInstance.name, rule_name: 'A股整数手', rule_version: 1, decision: 'accepted', message: '风险检查通过', created_at: now }],
      runtime_events: paperInstance.events,
      coverage: { instances: 1, signals: 1, orders: 1, trades: 1, positions: 1, risk_events: 1, runtime_events: 1 },
      pool_moves: [{ snapshot_id: 11, pool_id: 'pool-1', pool_name: '动量 Top20', trade_date: '2025-01-02', member_count: 20, manifest_hash: 'pool-manifest' }],
      instances: [paperInstance], data_status: 'fresh', source_label: 'PostgreSQL Paper audit evidence', source_updated_at: now, response_generated_at: now,
    }));
    if (method === 'GET' && path === '/monitor/health') return route.fulfill(json({
      status: 'healthy',
      services: [{ id: 1, service_code: 'paper_runtime', status: 'healthy', freshness: 'fresh', message: '周期处理成功', observed_at: now }],
      data: { dataset: { id: 10, status: 'sealed' }, market: { id: 3, status: 'published' } },
      strategy_instances: [{ status: 'running', count: 1 }],
      strategy_health: [{ id: paperInstance.id, name: paperInstance.name, status: 'running', health_state: 'fresh', data_purpose: 'user', heartbeat_at: now, last_processed_trade_date: '2025-01-02', latest_cycle_status: 'success', latest_cycle_finished_at: now, latest_equity: 1120000, latest_drawdown: 0, latest_cycle_ledger_difference: 0, order_count: 1, trade_count: 1, risk_event_count: 1, rejected_count: 0 }],
      risk_alerts: [],
      active_alerts: [],
      notifications: [{ status: 'delivered', count: 1 }],
      source_label: 'PostgreSQL runtime and health evidence', source_updated_at: now, response_generated_at: now,
    }));
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

test.beforeEach(async ({ context }) => {
  await mockApi(context);
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

  await expect(page.getByRole('complementary').getByRole('img', { name: /StockPro 智能投研/ })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '主菜单' })).toBeVisible();
  await expect(page.getByRole('link', { name: '首页', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '行情', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '股票池', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '策略', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '数据', exact: true })).toBeVisible();

  await page.goto('/market');
  await expect(page).toHaveURL(/\/market/);

  await page.goto('/strategy');
  await expect(page).toHaveURL(/\/strategy/);

  await page.goto('/data');
  await expect(page).toHaveURL(/\/data/);

  await page.goto('/data/processing');
  await expect(page.getByText('Data Hub V1')).toHaveCount(0);
  await expect(page.getByText(/当前以/)).toHaveCount(0);
  await expect(page.getByRole('tab', { name: /数据资产|Data Assets/ })).toBeVisible();
});

test('sidebar exposes exactly thirteen ordered first-level workspaces in groups', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/');

  const sidebar = page.getByRole('complementary');
  for (const group of ['研究', '研发', '验证', '系统']) {
    await expect(sidebar.getByRole('group', { name: group })).toBeVisible();
  }
  const links = sidebar.locator('nav a');
  await expect(links).toHaveCount(13);
  await expect(links).toHaveText([
    /首页/,
    /行情/,
    /股票池/,
    /因子/,
    /策略/,
    /回测/,
    /模拟/,
    /盯盘/,
    /监控/,
    /实盘/,
    /复盘/,
    /数据/,
    /AI研发/,
  ]);
});

test('desktop shell matches the BitPro single-column operator navigation', async ({ page }) => {
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto('/');

  const sidebar = page.getByRole('complementary');
  const sidebarBox = await sidebar.boundingBox();
  expect(sidebarBox?.width ?? 999).toBeLessThanOrEqual(65);
  await expect(sidebar.getByRole('link', { name: '首页', exact: true })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: '实盘', exact: true })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: '数据', exact: true })).toBeVisible();
  const firstBox = await sidebar.getByRole('link', { name: '首页', exact: true }).boundingBox();
  const lastBox = await sidebar.getByRole('link', { name: '数据', exact: true }).boundingBox();
  expect(lastBox?.y ?? 0).toBeGreaterThan(firstBox?.y ?? 0);
  await expect(page.getByTestId('stockpro-ai-topbar')).toHaveCount(0);
  const marketIndexSection = page.getByRole('heading', { name: '市场指数' }).locator('xpath=ancestor::section[1]');
  await expect(marketIndexSection).toBeVisible();
  const topbarLabels = ['上证指数', '深证成指', '创业板指', '科创50'];
  const marketIndexXs = await Promise.all(
    topbarLabels.map(async (label) => (await marketIndexSection.getByText(label).boundingBox())?.x ?? 0),
  );
  expect(marketIndexXs).toEqual([...marketIndexXs].sort((left, right) => left - right));
});

test('BitPro-style navigation stays mounted across first-level page changes', async ({ page }) => {
  let overviewRequestCount = 0;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/market/overview') overviewRequestCount += 1;
  });
  await loginAsAdmin(page);
  await page.goto('/strategy');

  const navigation = page.getByRole('navigation', { name: '主菜单' });
  await navigation.evaluate((element) => {
    element.setAttribute('data-lifecycle-probe', 'persistent');
  });
  const initialRequestCount = overviewRequestCount;

  await page.getByRole('link', { name: '回测', exact: true }).click();
  await expect(page.getByRole('heading', { name: '回测', exact: true })).toBeVisible();
  await expect(navigation).toHaveAttribute('data-lifecycle-probe', 'persistent');

  await page.getByRole('link', { name: '模拟', exact: true }).click();
  await expect(page.getByRole('heading', { name: '模拟盘' })).toBeVisible();
  await expect(navigation).toHaveAttribute('data-lifecycle-probe', 'persistent');
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
    '/live',
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
  await expect(page.getByRole('navigation', { name: '主菜单' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '监控中心' })).toBeVisible();
  const bodyOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(bodyOverflow).toBeLessThanOrEqual(1);
});

test('mobile navigation scrolls every current workspace link into view', async ({ page }) => {
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const workspaces = [
    ['/', '首页'],
    ['/market', '行情'],
    ['/pools', '股票池'],
    ['/factors', '因子'],
    ['/strategy', '策略'],
    ['/backtest', '回测'],
    ['/paper', '模拟'],
    ['/watch', '盯盘'],
    ['/monitor', '监控'],
    ['/live', '实盘'],
    ['/review', '复盘'],
    ['/data', '数据'],
    ['/ai-lab', 'AI研发'],
  ] as const;

  for (const [path, label] of workspaces) {
    await page.goto(path);
    const activeLink = page.getByRole('navigation', { name: '主菜单' }).getByRole('link', { name: label });
    await expect(activeLink).toHaveAttribute('aria-current', 'page');
    await expect.poll(async () => activeLink.evaluate((link) => {
      const viewport = link.closest('[data-mobile-nav-viewport]');
      if (!viewport) return false;
      const linkRect = link.getBoundingClientRect();
      const viewportRect = viewport.getBoundingClientRect();
      return linkRect.left >= viewportRect.left - 1 && linkRect.right <= viewportRect.right + 1;
    })).toBeTruthy();
  }
});

test('administrator can inspect the MCP agent access boundary', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/data');
  await page.getByRole('button', { name: '设置' }).click();

  await expect(page.getByRole('region', { name: 'Agent Token 管理' })).toContainText('stockpro-mcp-v1');
  await expect(page.getByRole('region', { name: 'Agent Token 管理' })).toContainText('Research Agent');
  await expect(page.getByRole('region', { name: 'Agent Token 管理' })).toContainText('R/W');
  await expect(page.getByLabel('授予 W：允许带幂等键的异步回测写操作')).toBeVisible();
});

test('data-trust pages keep their state evidence usable at 390px', async ({ page }) => {
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const pages = [
    { path: '/', evidence: '快照可用' },
    { path: '/paper', evidence: '模拟盘' },
    { path: '/review', evidence: '复盘' },
    { path: '/data', evidence: '缓存同步质量诊断' },
  ];

  for (const item of pages) {
    await page.goto(item.path);
    const evidence = item.path === '/review'
      ? page.getByRole('heading', { name: '复盘', exact: true })
      : page.getByText(item.evidence, { exact: true }).first();
    await expect(evidence).toBeVisible();
    const bodyOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(bodyOverflow, `${item.path} should not overflow the mobile document`).toBeLessThanOrEqual(1);
  }
});

test('backtest center is separated from daily market review center', async ({ page }) => {
  await loginAsAdmin(page);

  await page.goto('/backtest');
  await expect(page.getByRole('heading', { name: '回测', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '创建回测实例' })).toBeVisible();
  await expect(page.getByTestId('backtest-job-console')).toContainText('任务队列');
  await expect(page.getByRole('button', { name: '结果证据' })).toBeVisible();
  await page.getByRole('button', { name: '任务日志' }).click();
  await expect(page.getByTestId('backtest-job-console')).toContainText('回测完成，结果证据已封存');
  await expect(page.getByText('StockPro Strategy API v1')).toHaveCount(0);

  await page.goto('/review');
  await expect(page.getByRole('heading', { name: '复盘', exact: true })).toBeVisible();
  await expect(page.getByText('涨停家数').first()).toBeVisible();
  await expect(page.getByRole('heading', { name: '板块资金', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '连板天梯' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '复盘结论' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '交易日时间线' })).toBeVisible();
});

test('backtest result exposes a verdict strip, performance detail and six evidence tabs', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/backtest/66666666-6666-6666-6666-666666666666');

  await expect(page.getByRole('heading', { name: 'MA5 趋势策略' })).toBeVisible();
  await expect(page.getByText('MA5 完整回测').first()).toBeVisible();
  const verdictStrip = page.getByTestId('backtest-verdict-strip');
  await expect(verdictStrip).toBeVisible();
  for (const label of ['净收益', '超额收益', '最大回撤', '夏普']) {
    await expect(verdictStrip.getByText(label, { exact: true })).toBeVisible();
  }
  const performanceDetail = page.getByRole('heading', { name: '绩效明细' }).locator('xpath=ancestor::section[1]');
  for (const label of ['年化收益', '基准收益', '夏普比率']) {
    await expect(performanceDetail.getByText(label, { exact: true })).toBeVisible();
  }
  for (const tab of ['持仓', '交易', '订单', '日志', '归因', '代码与参数']) {
    await expect(page.getByRole('tab', { name: tab, exact: true })).toBeVisible();
  }
  await page.getByRole('tab', { name: '代码与参数' }).click();
  await expect(page.getByText('策略代码 · v1')).toBeVisible();
  await page.getByRole('tab', { name: '订单' }).click();
  await expect(page.getByText('暂无记录', { exact: true })).toBeVisible();
});

test('full backtest exposes protocol segments and immutable Paper promotion gates', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/backtest/66666666-6666-6666-6666-666666666666');

  const gatePanel = page.getByRole('heading', { name: '晋级检查' }).locator('xpath=ancestor::section[1]');
  await expect(gatePanel).toBeVisible();
  for (const label of ['完整回测已封存', '研究协议已封存', '训练区间通过', '验证区间通过', '样本外区间通过', '成本模型证据完整', '容量规则已定义', '容量实测通过', '晋级阈值已定义', '基准证据完整', '数据质量通过']) {
    await expect(gatePanel.getByText(label, { exact: true })).toBeVisible();
  }
  await expect(gatePanel.getByText('门禁全部通过')).toBeVisible();
  await expect(gatePanel.getByText(/训练 2023-01-03~2023-12-29/)).toBeVisible();
  await expect(gatePanel.getByText(/样本外 2024-07-08~2025-01-02/)).toBeVisible();
  await expect(page.getByText('晋级 Paper', { exact: true })).toBeVisible();
});

test('quick backtest is visibly isolated from Paper promotion', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/backtest/99999999-9999-9999-9999-999999999999');

  await expect(page.getByText('快速预检不可晋级', { exact: true })).toBeVisible();
  await expect(page.getByText('快速预检不产生晋级证据')).toBeVisible();
  await expect(page.getByText('不会进入模拟盘候选')).toBeVisible();
  await expect(page.getByText('晋级 Paper', { exact: true })).toHaveCount(0);
  await expect(page.getByText('门禁全部通过')).toHaveCount(0);
});

test('configured market colors apply to gains, losses and neutral values', async ({ page }) => {
  await loginAsAdmin(page);
  await page.addInitScript(() => {
    if (!window.localStorage.getItem('stockpro_settings')) {
      window.localStorage.setItem('stockpro_settings', JSON.stringify({ colorScheme: 'redUpGreenDown' }));
    }
  });
  await page.goto('/backtest/66666666-6666-6666-6666-666666666666');

  const monthlyReturns = page.getByText('月度收益', { exact: true }).locator('xpath=..');
  const gain = monthlyReturns.getByText('12.00%', { exact: true });
  const loss = monthlyReturns.getByText('-4.00%', { exact: true });
  const neutral = monthlyReturns.getByText('0.00%', { exact: true });
  await expect(gain).toHaveCSS('color', 'rgb(255, 23, 68)');
  await expect(loss).toHaveCSS('color', 'rgb(0, 200, 83)');
  await expect(neutral).toHaveCSS('color', 'rgb(185, 195, 207)');

  await page.evaluate(() => {
    window.localStorage.setItem('stockpro_settings', JSON.stringify({ colorScheme: 'greenUpRedDown' }));
  });
  await page.reload();
  await expect(monthlyReturns.getByText('12.00%', { exact: true })).toHaveCSS('color', 'rgb(0, 200, 83)');
  await expect(monthlyReturns.getByText('-4.00%', { exact: true })).toHaveCSS('color', 'rgb(255, 23, 68)');
  await expect(monthlyReturns.getByText('0.00%', { exact: true })).toHaveCSS('color', 'rgb(185, 195, 207)');
});

test('market research exposes exactly six evidence workspaces and legacy redirects', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/research/overview');
  await expect(page).toHaveURL(/\/market\?tab=structure$/);
  await expect(page.getByRole('heading', { name: '行情' })).toBeVisible();
  await expect(page.getByTestId('market-headline-rise_count')).toContainText('3,200');
  await expect(page.getByTestId('market-headline-rise_count')).not.toContainText('stocks');
  await expect(page.getByTestId('market-headline-rise_count').locator('.bp-metric-card')).toHaveClass(/border-up/);
  await expect(page.getByTestId('market-headline-fall_count').locator('.bp-metric-card')).toHaveClass(/border-down/);
  await expect(page.getByTestId('market-headline-seal_rate')).toContainText('86.15%');
  for (const label of ['市场结构', '板块轮动', '情绪 / 涨停', '事件', '交易日历', '个股研究']) {
    await expect(page.getByRole('tab', { name: label })).toBeVisible();
  }
  await expect(page.getByText('市场数据快照')).toBeVisible();
  await page.getByRole('tab', { name: '情绪 / 涨停' }).click();
  await expect(page.getByText('连板天梯')).toBeVisible();
  await expect(page.getByText('5+板')).toBeVisible();
  await expect(page.getByText('暂不可用', { exact: true })).toBeVisible();

  const datedLeaderRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.endsWith('/market/hot-concept/leaders') && url.searchParams.get('date') === '2025-01-02';
  });
  await page.getByRole('tab', { name: '个股研究' }).click();
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
  await page.goto('/pools');
  await expect(page.getByRole('heading', { name: '股票池工作台', exact: true })).toBeVisible();
  for (const tab of ['mine', 'screener', 'snapshots']) {
    await expect(page.getByTestId(`pool-tab-${tab}`)).toBeVisible();
  }
  const evidencePanel = page.getByRole('heading', { name: '输入绑定与证据状态' }).locator('xpath=ancestor::section[1]');
  await expect(evidencePanel.getByText('因子快照已绑定')).toBeVisible();
  await expect(evidencePanel.getByText('Factor #3', { exact: true })).toBeHidden();
  await expect(evidencePanel.getByText(/Market #/)).toHaveCount(0);
  await expect(page.getByText('20日动量排名 1').first()).toBeVisible();
  await expect(page.getByText('600519.SH', { exact: true })).toBeVisible();
  await page.getByTestId('generate-pool').click();
  await expect(page.getByText(/已完成筛选，入选 2 只标的/)).toBeVisible();
  await page.getByTestId('seal-pool').click();
  await expect(page.getByText(/股票池快照已成功封存/)).toBeVisible();
  await page.getByTestId('pool-tab-snapshots').click();
  await expect(page.getByTestId('pool-snapshot-table')).toBeVisible();
  await expect(page.getByText('验收探针池', { exact: true })).toHaveCount(0);
  await expect(page.getByTestId('pool-snapshot-availability-11')).toContainText('历史快照');
  await expect(page.getByTestId('pool-snapshot-availability-11')).toContainText('成员有效期至 2025-01-07');
  await expect(page.getByTestId('pool-backtest-11')).toContainText('创建历史回测草稿');
  await page.getByTestId('pool-backtest-11').click();
  await expect(page).toHaveURL(/\/backtest\?poolSnapshotId=11&experimentId=experiment-1$/);
  await page.getByRole('button', { name: '创建回测实例' }).click();
  await page.getByRole('button', { name: '下一步' }).click();
  await expect(page.locator('label').filter({ has: page.getByText('股票池快照', { exact: true }) }).locator('select')).toHaveValue('11');
  await expect(page.getByRole('textbox', { name: '股票代码 由股票池快照提供' })).toHaveValue('动量 Top20 · 20只');
});

test('stock-pool catalogue survives optional market-evidence failure', async ({ page }) => {
  await page.route('**/api/market/research-context**', (route) => route.fulfill(json({ detail: 'market evidence unavailable' }, 400)));
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/pools');

  await expect(page.getByRole('heading', { name: '股票池规则目录' })).toBeVisible();
  await expect(page.getByRole('button', { name: /动量 Top20/ })).toBeVisible();
  await expect(page.getByText('部分数据降级')).toBeVisible();
  await expect(page.getByText(/市场证据暂不可用/)).toBeVisible();
  await expect(page.getByText('600519.SH', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
});

test('dashboard shows the realtime market cockpit by default', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/');

  await expect(page.getByRole('heading', { name: '市场大盘' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '市场指数' })).toBeVisible();
  await expect(page.getByText('上证指数').last()).toBeVisible();
  await expect(page.getByText('强势股', { exact: true })).toBeVisible();
  await expect(page.getByText('市场情绪', { exact: true }).last()).toBeVisible();
  await expect(page.getByText('成交额', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '涨停生态', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '涨跌停个股列表', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '板块资金流向', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '热门板块 TOP30', exact: true })).toBeVisible();
  await expect(page.getByText('查看全部')).toBeVisible();
});

test('dashboard shows limit-up and limit-down stock board with expandable charts', async ({ page }) => {
  await page.route('**/api/charts/daily/**', (route) => route.fulfill(json([
    { date: '2025-01-01', open: 9.7, high: 10.1, low: 9.6, close: 9.9, volume: 900000 },
    { date: '2025-01-02', open: 9.9, high: 10.3, low: 9.8, close: 10.1, volume: 1000000 },
  ])));
  await page.route('**/api/charts/intraday/**', (route) => route.fulfill(json({
    data: [
      { time: '2025-01-02 09:31:00', price: 10.0, volume: 1000, pre_close: 9.9, trade_date: '2025-01-02' },
      { time: '2025-01-02 09:32:00', price: 10.1, volume: 1200 },
    ],
    pre_close: 9.9,
    trade_date: '2025-01-02',
  })));
  await loginAsAdmin(page);
  await page.goto('/');

  const board = page.getByTestId('limit-board');
  await expect(board.getByRole('heading', { name: '涨跌停个股列表' })).toBeVisible();
  await expect(board.getByRole('button', { name: /涨停 2/ })).toBeVisible();
  await expect(board.getByText('深中华A')).toBeVisible();
  await board.getByRole('button', { name: /深中华A/ }).click();
  await expect(board.getByText(/近 30 日 K|读取日 K|无日 K/)).toBeVisible();
  await board.getByRole('button', { name: /跌停 1/ }).click();
  await expect(board.getByText('平安银行')).toBeVisible();
});


test('dashboard shows sector fund-flow top30 list and loads leaders on click', async ({ page }) => {
  await page.route('**/api/market/sector-fund-flow**', (route) => route.fulfill(json({
    limit: 30,
    unit: '亿',
    inflows: [{ rank: 1, name: '存储芯片', change_percent: 3.12, net_inflow_yi: 7 }],
    outflows: [{ rank: 2, name: '中芯国际概念', change_percent: 2.8, net_inflow_yi: -1 }],
    rankings: [
      { rank: 1, name: '存储芯片', change_percent: 3.12, net_inflow_yi: 7 },
      { rank: 2, name: '中芯国际概念', change_percent: 2.8, net_inflow_yi: -1 },
    ],
    updated_at: '2026-07-28T10:00:00+08:00',
    data_status: 'fresh',
    source_label: 'PostgreSQL hot_concepts_realtime',
    methodology: '按板块主力净流入排序；连线按流入侧权重分摊。',
  })));
  await page.route('**/api/market/hot-concept/leaders**', (route) => {
    const url = new URL(route.request().url());
    const name = url.searchParams.get('name') || '';
    if (name === '中芯国际概念') {
      return route.fulfill(json([
        { code: '688981', name: '中芯国际', price: 50.1, change_percent: 4.2, amount: 1.2e9, turnover: 2.1 },
      ]));
    }
    return route.fulfill(json([
      { code: '603986', name: '兆易创新', price: 100.2, change_percent: 5.1, amount: 8e8, turnover: 3.2 },
    ]));
  });
  await loginAsAdmin(page);
  await page.goto('/');

  const panel = page.getByTestId('sector-fund-flow');
  await expect(panel.getByRole('heading', { name: '热门板块 TOP30' })).toBeVisible();
  await expect(panel.getByRole('button', { name: /存储芯片/ })).toBeVisible();
  await expect(panel.getByRole('heading', { name: '存储芯片 · 核心龙头' })).toBeVisible();
  await expect(panel.getByText('兆易创新')).toBeVisible();

  await panel.getByRole('button', { name: /中芯国际概念/ }).click();
  await expect(panel.getByRole('heading', { name: '中芯国际概念 · 核心龙头' })).toBeVisible();
  await expect(panel.getByText('中芯国际 688981.SH')).toBeVisible();
});

test('dashboard marks stale market caches and never presents them as current signals', async ({ page }) => {
  const staleAt = '2025-01-02T15:00:00+08:00';
  await page.route('**/api/market/sector-fund-flow**', (route) => route.fulfill(json({
    limit: 30,
    unit: '亿',
    inflows: [],
    outflows: [{ rank: 1, name: '陈旧概念', change_percent: 6.1, net_inflow_yi: -2.0, updated_at: staleAt }],
    rankings: [{ rank: 1, name: '陈旧概念', change_percent: 6.1, net_inflow_yi: -2.0, updated_at: staleAt }],
    updated_at: staleAt,
    data_status: 'stale',
    source_label: 'PostgreSQL hot_concepts_realtime',
    methodology: '按板块主力净流入排序；连线按流入侧权重分摊。',
  })));
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
  await expect(page.getByText(/陈旧缓存|缓存陈旧/).first()).toBeVisible();
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
    { path: '/', anchors: ['市场大盘', '市场指数', '涨停生态', '板块资金流向'] },
    { path: '/market', anchors: ['行情', '市场数据快照', '涨停数'] },
    { path: '/pools', anchors: ['股票池工作台', '股票池规则目录', '当前入选成员明细与存根理由'] },
    { path: '/factors', anchors: ['因子研究', '因子库', '20日动量'] },
    { path: '/strategy', anchors: ['策略中心', 'A股策略约束', '100股整数手'] },
    { path: '/backtest', anchors: ['回测', '创建回测实例', '回测实例'] },
    { path: '/ai-lab', anchors: ['AI研发', 'AI自主交易', 'AI自主交易控制台', '硬风控边界'] },
    { path: '/live', anchors: ['实盘工作台', '券商通道', '晋级候选'] },
    { path: '/review', anchors: ['复盘', '板块资金', '连板天梯'] },
    { path: '/paper', anchors: ['模拟盘', '创建 Paper 实例', 'A股模拟策略'] },
    { path: '/watch', anchors: ['盯盘', '观察同一策略版本的信号', '最新策略信号'] },
    { path: '/monitor', anchors: ['监控中心', '运行风控', '涨跌停风险'] },
    { path: '/data', anchors: ['数据管理中心', '当前数据结论', '缓存同步质量诊断'] },
    { path: '/data/processing', anchors: ['数据资产', '生产任务', '质量治理'] },
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
    await expect(page.getByRole('navigation', { name: '主菜单' })).toBeVisible();
    for (const anchor of item.anchors) {
      await expect(page.getByText(anchor).first(), `${item.path} should show ${anchor}`).toBeVisible();
    }
    for (const copy of forbiddenCopy) {
      await expect(page.getByText(copy, { exact: false }), `${item.path} should not expose ${copy}`).toHaveCount(0);
    }
  }

  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('market terminal quarantines a consolidated price when daily and live evidence conflict', async ({ page }) => {
  await page.route('**/api/market/research-context**', (route) => route.fulfill(json({
    publication_state: 'published',
    snapshot: {
      id: 8,
      trade_date: '2026-08-07',
      snapshot_type: 'post_close',
      session_label: '盘后',
      freshness: 'fresh',
      source_map: {},
      status: 'published',
      content_hash: 'market-evidence-20260807',
    },
    sentiment: { metrics: [], market_temperature: null },
    limit_ecosystem: { ladder: [], pools: { up: [], down: [], broken: [] }, promotion_elimination: [] },
    sector_evidence: { items: [] },
    heat_rankings: [],
  })));
  await page.route('**/api/charts/daily/**', (route) => route.fulfill(json([
    {
      date: '2026-08-07',
      open: 2.68,
      high: 2.70,
      low: 2.62,
      close: 2.70,
      volume: 314992,
      source_label: 'tushare',
      updated_at: '2026-08-07T17:30:19+08:00',
    },
  ])));
  await page.route('**/api/market/fundamentals/**', (route) => route.fulfill(json({
    code: '600000',
    data_status: 'empty',
    source_label: 'PostgreSQL fundamentals cache',
    error: 'not_available_in_postgresql',
  })));
  await page.route('**/api/market/order-book/**', (route) => route.fulfill(json({
    symbol: '600000.SH',
    code: '600000',
    name: '浦发银行',
    price: 9.21,
    pre_close: 9.29,
    bid: 9.21,
    ask: 9.22,
    change_percent: -0.86,
    asks: [{ level: 1, price: 9.22, volume: 100 }],
    bids: [{ level: 1, price: 9.21, volume: 200 }],
    volume_unit: '手',
    trade_date: '2026-08-07',
    trade_time: '15:00:00',
    source: 'tushare_sina',
    source_label: 'TuShare 五档快照（新浪源）',
    data_status: 'fresh',
    updated_at: '2026-08-07T15:00:01+08:00',
    error: null,
  })));
  await loginAsAdmin(page);
  await page.goto('/market?tab=stock');

  await expect(page.getByTestId('market-price-evidence-conflict')).toBeVisible();
  await expect(page.getByText('价格证据冲突')).toBeVisible();
  await expect(page.getByText(/日线收盘 2.70/)).toBeVisible();
  await expect(page.getByText(/盘口 9.21/)).toBeVisible();
  await expect(page.getByText(/暂停合并价格与派生涨跌幅/)).toBeVisible();
  await expect(page.getByRole('heading', { name: '价格口径' })).toBeVisible();
  const dailyBasis = page.getByTestId('market-price-basis-daily');
  const bookBasis = page.getByTestId('market-price-basis-book');
  await expect(dailyBasis.getByText('未复权日线（研究基线）')).toBeVisible();
  await expect(bookBasis.getByText('未复权盘口（执行参考）')).toBeVisible();
  await expect(dailyBasis.getByText(/2026-08-07 · tushare/)).toBeVisible();
  await expect(bookBasis.getByText(/2026-08-07 15:00:00 · TuShare 五档快照/)).toBeVisible();
  await expect(page.getByText('¥2.70', { exact: true })).toHaveCount(0);
});

test('paper watch and monitor keep separate operator ownership', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/paper');
  await expect(page.getByRole('heading', { name: '模拟盘', exact: true })).toBeVisible();
  await page.getByTestId('paper-instance-card').first().getByRole('button', { name: '详情' }).click();
  await expect(page.getByTestId('paper-instance-monitor')).toBeVisible();
  for (const label of ['核心选股与交易逻辑', '当前持仓', '成交与事件', '账户曲线', '风控状态']) {
    await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible();
  }
  await page.goto('/watch');
  for (const label of ['策略信号', '订单与成交', '股票池变动', '图表联动', '告警']) await expect(page.getByRole('tab', { name: label, exact: true })).toBeVisible();
  const watchAuditRequest = page.waitForRequest((request) => request.url().includes('/api/watch/context') && request.url().includes('scope=audit'));
  await page.getByRole('button', { name: '审计视图' }).click();
  await watchAuditRequest;
  await expect(page.getByTestId('data-scope-control')).toContainText('不改变原始记录');
  await page.getByRole('tab', { name: '订单与成交', exact: true }).click();
  await expect(page.getByRole('heading', { name: '模拟订单' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '模拟成交' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '当前持仓证据' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '风险决策' })).toBeVisible();
  await page.goto('/monitor');
  for (const label of ['总览', '策略健康', '数据健康', '风险', '通知']) await expect(page.getByRole('tab', { name: label, exact: true })).toBeVisible();
  const monitorAuditRequest = page.waitForRequest((request) => request.url().includes('/api/monitor/health') && request.url().includes('scope=audit'));
  await page.getByRole('button', { name: '审计视图' }).click();
  await monitorAuditRequest;
  await expect(page.getByTestId('data-scope-control')).toContainText('验收与种子证据');
  await page.getByRole('button', { name: '业务视图' }).click();
  await page.getByRole('tab', { name: '策略健康', exact: true }).click();
  await expect(page.getByText('验收数据')).toHaveCount(0);
  await expect(page.getByText('最后心跳')).toBeVisible();
});

test('strategy backtest and paper expose the A-share operator workflow without implementation notes', async ({ page }) => {
  await loginAsAdmin(page);

  await page.goto('/strategy');
  await expect(page.getByText('PG 策略定义 / 不可变版本')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '策略中心' })).toBeVisible();

  await page.goto('/backtest');
  await expect(page.getByText('PG 封存研究输入 / Provider-free Read')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '回测', exact: true })).toBeVisible();
  await expect(page.getByTestId('backtest-history-table')).toBeVisible();
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
  await expect(page.getByRole('heading', { name: '模拟盘', exact: true })).toBeVisible();
  await expect(page.getByTestId('paper-instance-grid')).toBeVisible();
  await page.getByTestId('paper-instance-card').first().getByRole('button', { name: '详情' }).click();
  await expect(page.getByTestId('paper-instance-monitor')).toBeVisible();
  await expect(page.getByText('600519.SH', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('heading', { name: '账户曲线' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '风控状态' })).toBeVisible();
  await expect(page.getByText('研究数据：已绑定封存版本')).toBeVisible();
});

test('strategy catalogue labels the user-strategy count separately from reference records', async ({ page }) => {
  await page.route('**/api/strategy/list*', (route) => route.fulfill(json([
    {
      id: 1,
      name: '用户动量策略',
      description: '用户策略',
      script_content: 'def initialize(context):\n    pass\n\ndef handle_data(context, data):\n    pass\n',
      interval_seconds: 60,
      enabled: true,
      is_running: false,
      data_purpose: 'user',
      created_at: now,
      updated_at: now,
    },
    {
      id: 99,
      name: 'Sprint07 acceptance probe',
      description: '验收证据',
      script_content: 'def initialize(context):\n    pass\n',
      interval_seconds: 60,
      enabled: false,
      is_running: false,
      data_purpose: 'acceptance',
      created_at: now,
      updated_at: now,
    },
  ])));
  await loginAsAdmin(page);
  await page.goto('/strategy');

  await expect(page.getByRole('tab', { name: /我的策略 1/ })).toBeVisible();
  await expect(page.getByRole('tab', { name: /策略广场 4/ })).toBeVisible();
  await expect(page.getByRole('tab', { name: /审计证据 1/ })).toBeVisible();
  await expect(page.getByText('Sprint07 acceptance probe')).toHaveCount(0);
  await page.getByRole('tab', { name: /审计证据 1/ }).click();
  await expect(page.getByTestId('strategy-audit-scope')).toContainText('Sprint07 acceptance probe');
});

test('strategy details have a reloadable deep link and visible return path', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/strategy');

  await page.getByTestId('strategy-card').first().getByRole('button', { name: '详情' }).click();
  await expect(page).toHaveURL(/\/strategy\?strategy=1&view=detail$/);
  await expect(page.getByTestId('strategy-detail-workspace')).toBeVisible();
  await expect(page.getByRole('heading', { name: '测试策略' })).toBeVisible();

  await page.reload();
  await expect(page.getByTestId('strategy-detail-workspace')).toBeVisible();
  await page.getByRole('button', { name: '返回' }).click();
  await expect(page).toHaveURL(/\/strategy$/);
  await expect(page.getByRole('heading', { name: '策略中心' })).toBeVisible();
});

test('strategy lifecycle uses one BitPro-style first-level menu and does not imply live trading', async ({ page }) => {
  await loginAsAdmin(page);

  for (const path of ['/strategy', '/backtest', '/paper', '/watch', '/monitor', '/review']) {
    await page.goto(path);
    const menu = page.getByRole('navigation', { name: '主菜单' });
    await expect(menu).toBeVisible();
    await expect(page.getByTestId('workflow-rail')).toHaveCount(0);
    for (const label of ['策略', '回测', '模拟', '盯盘', '监控', '复盘']) {
      await expect(menu.getByRole('link', { name: label, exact: true })).toBeVisible();
    }
  }

  await expect(page.getByRole('link', { name: '模拟', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '模拟/实盘交易', exact: true })).toHaveCount(0);
});

test('paper running state is downgraded when the recorded replay heartbeat is missing', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/paper');

  const instanceCard = page.getByTestId('paper-instance-card').first();
  await expect(instanceCard.getByText('心跳陈旧', { exact: true })).toBeVisible();
  await expect(instanceCard.getByText('运行中', { exact: true })).toHaveCount(0);
  // 生命周期仍是 running：暂停等生命周期操作保持可用，但健康口径已降级。
  await expect(instanceCard.getByRole('button', { name: '暂停' })).toBeVisible();
});

test('watch never presents a stale snapshot as one hundred percent realtime', async ({ page }) => {
  await page.route('**/api/watch/context*', (route) => route.fulfill(json({
    alerts: [], signals: [], orders: [], trades: [], positions: [], risk_events: [],
    runtime_events: [], pool_moves: [], instances: [],
    coverage: { instances: 0, signals: 0, orders: 0, trades: 0, alerts: 0 },
    data_status: 'stale',
    source_label: 'PostgreSQL Paper audit evidence',
    source_updated_at: '2026-07-27T15:00:00+08:00',
    response_generated_at: now,
  })));
  await loginAsAdmin(page);
  await page.goto('/watch');

  await expect(page.getByText('旧快照 · 不可视为实时', { exact: true })).toBeVisible();
  await expect(page.getByText(/100% 实时监控中/)).toHaveCount(0);
});

test('watch separates load failure from a legitimate empty signal set', async ({ page }) => {
  await page.route('**/api/watch/context*', (route) => route.fulfill(json({ detail: 'watch unavailable' }, 503)));
  await loginAsAdmin(page);
  await page.goto('/watch');

  await expect(page.getByText('模拟交易 / 告警 / 股票池')).toBeVisible();
  await expect(page.getByText(/Request failed with status code 503/)).toBeVisible();
  await expect(page.getByText('数据加载失败')).toBeVisible();
});

test('monitor keeps counters unavailable when its health snapshot fails', async ({ page }) => {
  await page.route('**/api/monitor/health*', (route) => route.fulfill(json({ detail: 'monitor unavailable' }, 503)));
  await loginAsAdmin(page);
  await page.goto('/monitor');

  await expect(page.getByText('本地运行证据')).toBeVisible();
  await expect(page.getByText(/Request failed with status code 503/)).toBeVisible();
  for (const label of ['策略实例', '活动风险告警', '通知投递']) {
    await expect(page.getByText(label).locator('..').getByText('--')).toBeVisible();
  }
});

test('monitor gives stale service freshness precedence over a historical healthy result', async ({ page }) => {
  await page.route('**/api/monitor/health*', (route) => route.fulfill(json({
    status: 'critical',
    services: [{
      id: 1,
      service_code: 'paper_feed',
      status: 'healthy',
      freshness: 'stale',
      last_success_at: '2026-07-27T15:00:00+08:00',
      error_code: null,
      message: '历史周期成功',
      observed_at: '2026-07-27T15:00:00+08:00',
    }],
    data: {}, strategy_instances: [], strategy_health: [], risk_alerts: [],
    active_alerts: [], notifications: [],
    source_label: 'PostgreSQL runtime and health evidence',
    source_updated_at: '2026-07-27T15:00:00+08:00',
    response_generated_at: now,
  })));
  await loginAsAdmin(page);
  await page.goto('/monitor?tab=data');

  await expect(page.getByText('模拟行情服务', { exact: true })).toBeVisible();
  await expect(page.getByText('数据滞后', { exact: true })).toBeVisible();
  await expect(page.getByText('null', { exact: true })).toBeHidden();
});

test('primary reading surfaces localize internal values and keep raw evidence in diagnostics', async ({ page }) => {
  await loginAsAdmin(page);

  await page.goto('/pools');
  const poolEvidence = page.getByRole('heading', { name: '输入绑定与证据状态' }).locator('xpath=ancestor::section[1]');
  await expect(poolEvidence.getByText('研究数据快照已绑定 · 历史股票范围已绑定')).toBeVisible();
  await expect(poolEvidence.getByText('因子快照已绑定')).toBeVisible();
  const poolDiagnostics = poolEvidence.getByRole('group', { name: '输入绑定诊断原值' });
  await expect(poolDiagnostics.getByText('Dataset #10', { exact: true })).toBeHidden();
  await poolDiagnostics.getByText('查看诊断原值', { exact: true }).click();
  await expect(poolDiagnostics.getByText('Dataset #10', { exact: true })).toBeVisible();
  await expect(poolDiagnostics.getByText('Universe #1', { exact: true })).toBeVisible();

  await page.goto('/review?date=2025-01-02&tab=market');
  await expect(page.getByText('市场证据 · 盘后', { exact: true })).toBeVisible();
  await expect(page.getByText('全A · 已发布', { exact: true })).toBeVisible();
  const reviewDiagnostics = page.getByRole('group', { name: '时间线诊断原值' }).first();
  await expect(reviewDiagnostics.getByText('市场证据 · post_close', { exact: true })).toBeHidden();
  await reviewDiagnostics.getByText('查看诊断原值', { exact: true }).click();
  await expect(reviewDiagnostics.getByText('市场证据 · post_close', { exact: true })).toBeVisible();
  await expect(reviewDiagnostics.getByText('all_a · published', { exact: true })).toBeVisible();

  await page.route('**/api/monitor/health*', (route) => route.fulfill(json({
    status: 'critical',
    services: [{
      id: 1,
      service_code: 'paper_feed',
      status: 'healthy',
      freshness: 'stale',
      last_success_at: now,
      error_code: null,
      message: '历史周期成功',
      observed_at: now,
    }],
    data: {}, strategy_instances: [], strategy_health: [], risk_alerts: [],
    active_alerts: [], notifications: [],
    source_label: 'PostgreSQL runtime and health evidence',
    source_updated_at: now,
    response_generated_at: now,
  })));
  await page.goto('/monitor?tab=data');
  await expect(page.getByText('模拟行情服务', { exact: true })).toBeVisible();
  const serviceDiagnostics = page.getByRole('group', { name: '服务诊断原值' });
  await expect(serviceDiagnostics.getByText('paper_feed', { exact: true })).toBeHidden();
  await serviceDiagnostics.getByText('查看诊断原值', { exact: true }).click();
  await expect(serviceDiagnostics.getByText('paper_feed', { exact: true })).toBeVisible();
  await expect(serviceDiagnostics.getByText('null', { exact: true })).toBeVisible();
});

test('ai lab exposes research state and a real load error', async ({ page }) => {
  await page.route('**/api/strategy/list*', (route) => route.fulfill(json({ detail: 'strategy unavailable' }, 503)));
  await loginAsAdmin(page);
  await page.goto('/ai-lab');

  await expect(page.getByText('策略版本库记录')).toBeVisible();
  await expect(page.getByText(/证据加载失败/)).toBeVisible();
});

test('daily review exposes the market snapshot blocks and a sealed audit timeline', async ({ page }) => {
  const assembleRequests: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/api/review/2025-01-02/assemble')) assembleRequests.push(request.url());
  });
  await loginAsAdmin(page);
  await page.goto('/review?date=2025-01-02');

  await expect(page.getByTestId('daily-review-workbench')).toBeVisible();
  await expect(page.getByRole('heading', { name: '复盘', exact: true })).toBeVisible();
  for (const title of ['指数快照', '市场宽度', '情绪指标', '涨停生态', '人气榜', '板块资金']) {
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  }
  const filters = page.getByRole('group', { name: '复盘证据类别筛选' });
  for (const label of ['全部', '市场', '股票池', '策略', '交易执行']) {
    await expect(filters.getByRole('button', { name: label, exact: false })).toContainText(/\d/);
  }
  await expect(filters.getByRole('button', { name: '全部' })).toContainText('4');
  await expect(page.getByRole('heading', { name: '交易日时间线' })).toBeVisible();
  await expect(page.getByText('复盘已封存，不可修改')).toBeVisible();
  await expect(page.getByText('review-manifest')).toHaveCount(0);
  await expect(page.getByText('查看关联记录 →').first()).toBeVisible();
  expect(assembleRequests).toHaveLength(0);
  await page.getByRole('button', { name: '生成复盘' }).click();
  await expect.poll(() => assembleRequests.length).toBe(1);
});

test('daily review keeps metrics unavailable when evidence assembly fails', async ({ page }) => {
  await page.route('**/api/review/2025-01-02', (route) => route.fulfill(json({ detail: 'fixture failure' }, 503)));
  await loginAsAdmin(page);
  await page.goto('/review?date=2025-01-02');

  await expect(page.getByText('加载失败', { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Request failed with status code 503/)).toBeVisible();
  const filters = page.getByRole('group', { name: '复盘证据类别筛选' });
  for (const label of ['全部', '市场', '股票池', '策略', '交易执行']) {
    await expect(filters.getByRole('button', { name: label, exact: false })).toContainText('--');
  }
  await expect(page.getByRole('button', { name: '保存草稿' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '封存复盘' })).toHaveCount(0);
  await expect(page.getByText('复盘证据加载后才可保存或封存')).toBeVisible();
});

test('daily review renders absent category counters as zero instead of undefined', async ({ page }) => {
  await page.route('**/api/review/2025-01-02', (route) => route.fulfill(json({
    review: null,
    trade_date: '2025-01-02',
    status: 'live',
    source_manifest_hash: 'empty-review-manifest',
    counts: { market: 1 },
    metrics: [],
    items: [],
  })));
  await loginAsAdmin(page);
  await page.goto('/review?date=2025-01-02');

  const filters = page.getByRole('group', { name: '复盘证据类别筛选' });
  await expect(filters.getByRole('button', { name: '市场' })).toContainText('1');
  await expect(filters.getByRole('button', { name: '股票池' })).toContainText('0');
  await expect(filters.getByRole('button', { name: '策略' })).toContainText('0');
  await expect(filters.getByRole('button', { name: '交易执行' })).toContainText('0');
  await expect(page.getByText(/undefined/)).toHaveCount(0);
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
  await expect(page.getByText('研究快照历史')).toBeVisible();
  await page.getByRole('tab', { name: '研究数据' }).click();
  await expect(page.getByText(/研究数据 已封存 · 实际来源 tushare/)).toBeVisible();
  await expect(page.getByText(/因子 已封存 · 市场证据 restricted/)).toBeVisible();
  await expect(page.getByText('响应哈希 daily-hash')).toHaveCount(0);
  await expect(page.getByText('可回测', { exact: true })).toHaveCount(0);
  await expect(page.getByText('配置已启用 · 运行器未启动')).toBeVisible();
  await expect(page.getByText(/配置时间不会自动执行/)).toBeVisible();
});

test('data center automatically shows the latest quality report, failed rules and repair entry', async ({ page }) => {
  let qualityRunRequests = 0;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/data-hub/quality/run') qualityRunRequests += 1;
  });
  await page.route('**/api/data-hub/quality/report', (route) => route.fulfill(json({
    status: 'success',
    data: {
      report_key: 'dq_20260810',
      scope: ['stock_history'],
      status: 'red',
      summary: { total_checks: 1, green: 0, yellow: 0, red: 1, status: 'red' },
      checks: [{
        dataset_id: 'stock_history',
        status: 'red',
        title: 'A股日线行情质量',
        detail: '最新日期 2026-07-01，日期最大间隔 12 天',
        metrics: { rows: 1000, freshness_days: 40, max_gap_days: 12 },
        findings: [{
          rule_id: 'freshness',
          status: 'red',
          title: '数据最新性失败',
          detail: '最近数据距今 40.00 天',
          observed_value: 40,
          threshold: '数据延迟 <= 3 天',
          remediation: { kind: 'heal_missing_data', label: '回补最近日线', supported: true },
        }],
      }],
      created_at: '2026-08-10T09:00:00+08:00',
    },
  })));
  await loginAsAdmin(page);
  await page.goto('/data');

  await expect(page.getByRole('heading', { name: '最近一次质量报告' })).toBeVisible();
  await expect(page.getByText('2026-08-10 09:00:00')).toBeVisible();
  await expect(page.getByText('数据最新性失败')).toBeVisible();
  await expect(page.getByText('最近数据距今 40.00 天')).toBeVisible();
  await expect(page.getByRole('button', { name: '回补最近日线' })).toBeVisible();
  expect(qualityRunRequests).toBe(0);
});

test('data center labels a missing quality report honestly without zero-value claims', async ({ page }) => {
  await page.route('**/api/data-hub/quality/report', (route) => route.fulfill(json({ status: 'success', data: null })));
  await loginAsAdmin(page);
  await page.goto('/data');

  await expect(page.getByRole('heading', { name: '最近一次质量报告' })).toBeVisible();
  await expect(page.getByText('尚无质量报告')).toBeVisible();
  await expect(page.getByText('尚未执行过质量检查，当前质量状态不可用。')).toBeVisible();
  await expect(page.getByRole('button', { name: '运行质量检查' })).toBeVisible();
  await expect(page.getByText('通过 0')).toHaveCount(0);
});

test('data center keeps every primary action visible without a hidden horizontal exit', async ({ page }) => {
  await loginAsAdmin(page);
  const actionLabels = [
    '查看数据同步说明',
    '刷新',
    '定时同步',
    '立即运行日终',
    '增量更新',
    '自定义同步',
    '全量下载',
    '一键数据自愈',
  ];

  for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.goto('/data');
    const actionGroup = page.getByRole('button', { name: '一键数据自愈' }).locator('..');
    await expect(actionGroup).toBeVisible();
    expect(await actionGroup.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBeTruthy();
    for (const label of actionLabels) {
      const button = page.getByRole('button', { name: label }).first();
      await expect(button).toBeVisible();
      expect(await button.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return rect.left >= -1 && rect.right <= window.innerWidth + 1;
      }), `${label} must be inside the ${viewport.width}px viewport`).toBeTruthy();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  }
});

test('factor research exposes six PG-backed workspaces and explicit pending evidence', async ({ page }) => {
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/factors');

  await expect(page.getByRole('heading', { name: '因子研究' })).toBeVisible();
  for (const label of ['因子库', '计算运行', '单因子分析', '多因子分析', '相关性与暴露', '因子值']) {
    await expect(page.getByRole('tab', { name: label })).toBeVisible();
  }
  await expect(page.getByTestId('factor-research-summary')).toBeVisible();
  await expect(page.getByText('2025-01-02', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('已发布', { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/研究日 2025-01-02/)).toBeVisible();
  await expect(page.getByText('未来收益窗口未成熟')).toBeVisible();
  await expect(page.getByText('待成熟').first()).toBeVisible();

  await page.getByRole('row', { name: /20日动量 momentum_20d/ }).click();
  await expect(page).toHaveURL(/\/factors\/61$/);
  await expect(page.getByText('研究状态：探索研究')).toBeVisible();
  await expect(page.getByText('未来收益评估待成熟')).toBeVisible();

  await page.getByRole('tab', { name: '因子值' }).click();
  await expect(page.getByText('600000.SH')).toBeVisible();
  await expect(page.getByText('点时因子值')).toBeVisible();
});

test('factor maturity uses independent denominators and explains unavailable research gates', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/factors');

  await expect(page.getByTestId('factor-stage-defined')).toContainText('1');
  await expect(page.getByTestId('factor-stage-computed')).toContainText('1/1');
  await expect(page.getByTestId('factor-stage-evaluated')).toContainText('0/1');
  await expect(page.getByTestId('factor-stage-evaluated')).toContainText('未来收益窗口未成熟');
  await expect(page.getByTestId('factor-stage-eligible')).toContainText('--');
  await expect(page.getByTestId('factor-stage-eligible')).toContainText('没有已评估因子，暂不形成分母');

  await expect(page.getByTestId('factor-check-cross-sectional')).toContainText('1/1');
  await expect(page.getByTestId('factor-check-time-series')).toContainText('--');
  await expect(page.getByTestId('factor-check-time-series')).toContainText('至少需要两个成熟交易日');
  await expect(page.getByTestId('factor-check-out-of-sample')).toContainText('--');
  await expect(page.getByTestId('factor-check-out-of-sample')).toContainText('尚无封存样本外通过证据');
  await expect(page.getByTestId('factor-check-leakage')).toContainText('1/1');
  await expect(page.getByText('0%', { exact: true })).toHaveCount(0);
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
