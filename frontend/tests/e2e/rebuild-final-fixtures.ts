import type { Page, Route } from '@playwright/test'

export async function installFinalFixtures(page: Page, role: 'admin' | 'guest' = 'admin') {
  await page.route('**/api/v2/**', async (route: Route) => {
    const path = new URL(route.request().url()).pathname
    let data: any = { items: [], total: 0 }

    if (path === '/api/v2/auth/me') data = { auth_enabled: false, authenticated: true, role, permissions: role === 'admin' ? ['admin'] : ['read', 'backtest'] }
    else if (path === '/api/v2/system/health') data = { status: 'healthy', project: 'StockPro', database: 'postgresql', private_exchange: false }
    else if (path === '/api/v2/market/overview') data = {
      status: 'empty',
      data_status: 'empty',
      definition_version: 'ashare-market-overview.v1',
      trade_date: null,
      data_mode: '盘后快照',
      provider: 'PostgreSQL',
      source_snapshot_id: null,
      available_at: null,
      knowledge_cutoff_at: null,
      last_success_at: null,
      missing_inputs: ['测试夹具未提供 A 股行情事实'],
      evidence: { status: 'empty', data_mode: '盘后快照', provider: 'PostgreSQL', source_snapshot_id: null, missing_inputs: ['测试夹具未提供 A 股行情事实'] },
      indices: { status: 'empty', items: [], required_count: 4, available_count: 0, denominator: '真实指数点位与当日涨跌', missing_inputs: ['测试夹具未提供真实指数'] },
      breadth: { status: 'empty', universe_count: 0, eligible_count: 0, excluded_count: 0, excluded_reasons: {}, gainers: 0, losers: 0, flat: 0, advance_ratio_pct: null, strong_count: 0, weak_count: 0, mean_change_pct: null, median_change_pct: null, strong_move_threshold_pct: 3, denominator: '有效价格与当日涨跌均存在的 A 股', missing_inputs: ['测试夹具未提供 A 股行情事实'] },
      distribution: { status: 'empty', buckets: [], total_count: null, boundary_definition: '左闭右开', denominator: '同市场宽度 eligible_count', missing_inputs: ['测试夹具未提供 A 股行情事实'] },
      trend: { status: 'blocked', required_history_days: 60, available_history_days: 0, total_symbols: 0, covered_symbols: 0, denominator: '至少 60 个确认交易日且收盘价有效的 A 股', above_ma5: { count: null, percentage: null }, above_ma20: { count: null, percentage: null }, above_ma60: { count: null, percentage: null }, new_high_60d: { count: null, percentage: null }, new_low_60d: { count: null, percentage: null }, new_high_low_ratio: null, missing_inputs: ['没有可用的历史日线'] },
      activity: { status: 'empty', total_amount_cny: null, average_amount_cny: null, amount_unit: 'CNY', amount_denominator: '有有效成交额的 eligible 股票', average_turnover_rate_pct: null, turnover_unit: '%', turnover_denominator: '有有效换手率的 eligible 股票', high_turnover_count: null, high_turnover_threshold_pct: 8, average_volume_ratio: null, volume_ratio_unit: '倍', volume_ratio_denominator: '20日平均成交量', volume_expansion_count: null, volume_ratio_threshold: 1.5, amount: { total_cny: null, average_cny: null, unit: 'CNY', denominator: '有有效成交额的 eligible 股票' }, turnover: { average_rate_pct: null, high_count: null, unit: '%', threshold_pct: 8 }, volume_ratio: { average: null, expansion_count: null, unit: '倍', threshold: 1.5, denominator: '20日平均成交量' }, missing_inputs: ['成交额缺失', '换手率缺失', '量比缺失'] },
      amount: { status: 'empty', total_cny: null, average_cny: null, unit: 'CNY', denominator: '有有效成交额的 eligible 股票' },
      rankings: { status: 'empty', limit: 10, top_gainers: [], top_losers: [], turnover_leaders: [], active_leaders: [], missing_inputs: ['没有可用于排行的有效价格与涨跌数据'] },
      top_gainers: [],
      top_losers: [],
      turnover_leaders: [],
      active_leaders: [],
    }
    else if (path === '/api/v2/market/tickers') data = []
    else if (path === '/api/v2/market/native-sentiment') data = { core: [], pipeline: { security_master: { rows: 0, from: '', to: '' }, daily_bars: { rows: 0, from: '', to: '' } } }
    else if (path === '/api/v2/market/symbols') data = {
      symbols: ['600519.SH', '000001.SZ'],
      instruments: [
        { symbol: '600519.SH', name: '贵州茅台', display_name: '贵州茅台 600519.SH', asset_class: 'stock', exchange: 'SSE' },
        { symbol: '000001.SZ', name: '平安银行', display_name: '平安银行 000001.SZ', asset_class: 'stock', exchange: 'SZSE' },
      ],
    }
    else if (path === '/api/v2/market/klines' || path === '/api/v2/market/trades') data = []
    else if (path === '/api/v2/market/indicators') data = { source: 'backend_derived_from_ohlcv', data_source: 'market_klines', timestamps: [], series: {} }
    else if (path === '/api/v2/market/orderbook') data = { bids: [], asks: [], source: 'unavailable' }
    else if (path === '/api/v2/market/ticker') data = { symbol: '', last: 0, change_percent: 0 }
    else if (path === '/api/v2/market/phase') data = { trade_date: '2026-08-27', phase: '主升', status: 'ok', confidence: 0.82, reasons: ['上涨占比 72.0%'], missing_inputs: [], definition_version: 'ashare-market-phase.v1' }
    else if (path === '/api/v2/market/sector-rps') data = [{ trade_date: '2026-08-27', classification_system: 'industry', sector_code: 'I001', sector_name: '半导体', rps_percentile: 96, rank: 1, rank_change: 2, leader_symbol: '688001.SH', status: 'ok', missing_inputs: [] }]
    else if (path === '/api/v2/market/movers') data = [{ symbol: '600519.SH', name: '贵州茅台', board: '主板', st: false, trade_date: '2026-08-27', windows: { '3d': { value: 0.16, value_pct: 16, threshold: 0.2, threshold_pct: 20, closeness: 0.8, direction: 'up', status: 'edge' }, '10d': { value: 0.35, value_pct: 35, threshold: 1, threshold_pct: 100, closeness: 0.35, direction: 'up', status: 'watch' }, '30d': { value: 0.8, value_pct: 80, threshold: 2, threshold_pct: 200, closeness: 0.4, direction: 'up', status: 'watch' } }, abnormal_status: 'edge', eligible: true, tags: ['接近前高'], status: 'ok', data_status: 'ok', missing_inputs: [] }]
    else if (path === '/api/v2/strategies') data = { items: [], total: 0, page: 1, per_page: 60, pages: 1, status_counts: { all: 0 }, asset_counts: { all: 0 }, type_counts: { all: 0 }, timeframe_counts: { all: 0 }, capital_counts: { all: 0 } }
    else if (path === '/api/v2/backtest/configuration') data = { items: [] }
    else if (path === '/api/v2/backtest/results' || path === '/api/v2/backtest/jobs') data = []
    else if (path === '/api/v2/live/instances') data = { items: [] }
    else if (path === '/api/v2/live/candidates') data = []
    else if (path === '/api/v2/live/dashboard') data = { system: { state: 'idle', exchange: 'CN', symbol: '', symbols: [], timeframe: '1d', strategy: '', strategy_id: null, dry_run: true, mode: 'paper' }, equity: {}, performance: {}, risk: {}, positions: [], account: {}, recent_events: [], feishu: { enabled: false } }
    else if (path === '/api/v2/live/accounts' || path.startsWith('/api/v2/live/')) data = []
    else if (path === '/api/v2/monitor/summary') data = { overall_status: 'unavailable', services: [], data: {}, strategy_health: [], active_alerts: [], notifications: [], source_label: 'PostgreSQL', source_updated_at: null }
    else if (path === '/api/v2/monitor/events') data = { events: [{ event_id: 'evt-1', source: 'abnormal', severity: 'warning', symbol: '600519.SH', name: '贵州茅台', message: '3日异动边缘', rule_id: 'ashare-abnormal-3d', source_object_type: 'market_alert_event', source_object_id: 'evt-1', triggered_at: '2026-08-27T09:30:00+08:00', orders_created: 0, paper_mutated: false }], data_status: 'ok', unavailable_reason: null, orders_created: 0, paper_mutated: false, limit: 10 }
    else if (path === '/api/v2/monitor/active_strategies' || path === '/api/v2/monitor/alerts') data = []
    else if (path === '/api/v2/monitor/long-short-ratio') data = { ratio: null, source: 'unavailable' }
    else if (path === '/api/v2/monitor/open-interest') data = { open_interest: null, source: 'unavailable' }
    else if (path === '/api/v2/sync/config') data = {
      default_symbols: ['000001.SZ', '600519.SH'],
      instruments: [
        { symbol: '000001.SZ', name: '平安银行', display_name: '平安银行 000001.SZ', asset_class: 'stock', exchange: 'SZSE' },
        { symbol: '600519.SH', name: '贵州茅台', display_name: '贵州茅台 600519.SH', asset_class: 'stock', exchange: 'SSE' },
      ],
      symbols_count: 2,
      default_timeframes: ['1d'],
      default_history_days: 500,
    }
    else if (path === '/api/v2/sync/status') data = { is_running: false, current_job: null, summary: { total_records: 0, exchanges: ['CN'], symbols_count: 2, pairs: 0 }, details: [] }
    else if (path === '/api/v2/sync/table-stats') data = { tables: [], total_records: 0, total_pairs: 0, market_stats: { swap: { total_records: 0, total_pairs: 0, total_symbols: 0 }, spot: { total_records: 0, total_pairs: 0, total_symbols: 2 } } }
    else if (path === '/api/v2/sync/schedule') data = { enabled: true, interval_minutes: 1440, history_days: 500, symbols: [], timeframes: ['1d'], next_run_at: '2026-08-27T18:10:00+08:00' }
    else if (path === '/api/v2/sync/jobs') data = { jobs: [] }
    else if (path === '/api/v2/review/summary') data = { overview: { review_window: '24h', bucket: '1h', updated_at: null, strategy_count: 0, sample_strategy_count: 0, overall_return_pct: 0, median_return_pct: 0, max_drawdown_pct: 0, observe_count: 0, review_count: 0, sample_health_pct: 0 }, groups: [], leaderboard: { observe: [], review: [] }, heatmap: [], tags: [], next_actions: [] }
    else if (path === '/api/v2/data/status') data = { storage: 'postgresql', provider_state: 'restricted', datasets: 0, published_partitions: 0, published_rows: 0, sealed_snapshots: 0, sync_jobs: 0, quality_issues: 0, staged_imports: 0, provider_calls_performed: 0 }
    else if (path.startsWith('/api/v2/data/')) data = { items: [], total: 0, provider_calls_performed: 0 }
    else if (path === '/api/v2/factorlab/summary') data = { status: 'ready', phase: 'a_share_catalog', statistics: { definition_count: 0, instance_count: 0, latest_value_count: 0, materialized_partition_count: 0, research_task_count: 0, trial_count: 0 }, definitions: [], instances: [], latest_values: [], data_plane: { format: 'PostgreSQL', layout: 'partitioned', manifest: 'sealed' }, capabilities: { api_mode: 'a_share_catalog', materialization_store_ready: true, research_metrics_available: false, strategy_runtime_connected: false, paper_live_connected: false } }
    else if (path === '/api/v2/factorlab/research/tasks') data = []
    else if (path.startsWith('/api/v2/factorlab/')) data = []
    else if (path === '/api/v2/settings/llm-model') data = {
      provider_key: 'dashscope', provider_name: 'DashScope', model: 'qwen3.6-plus', default_model: 'qwen3.6-plus', models: ['qwen3.6-plus'], free_tier_models: [], model_fallback_enabled: false,
      base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', enable_thinking: false, request_timeout: 180, api_key_configured: false, api_key_source: null,
      providers: [{ provider_key: 'dashscope', name: 'DashScope', api_key_env: 'DASHSCOPE_API_KEY', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', default_model: 'qwen3.6-plus', models: ['qwen3.6-plus'], api_key_configured: false, builtin: true, active: true, enabled: true, transport_type: 'openai_chat', credential_mode: 'env', credential_source: null }],
      provider_capabilities: [{ provider_key: 'dashscope', display_name: 'DashScope', transport_type: 'openai_chat', models: ['qwen3.6-plus'], reasoning_efforts: [], speed_modes: [], supports_tools: true, supports_structured_output: true, supports_resume: false, configured: false, healthy: false, status_detail: '未配置服务端 API Key', credential_mode: 'env', credential_source: null, default_model: 'qwen3.6-plus', enabled: true, active: true }],
      model_management_enabled: true, provider_management_enabled: false, connection_test_enabled: false,
    }
    else if (path === '/api/v2/settings/mcp-agent-tokens') data = { items: [], policy: { plaintext_returned_once: true, static_token_env: 'STOCKPRO_MCP_API_TOKEN', auth_header_default: 'X-StockPro-MCP-Token', legacy_token_env: 'BITPRO_MCP_API_TOKEN', legacy_auth_header: 'X-BitPro-MCP-Token' }, status: { configured: false, env_token_configured: false, active_token_count: 0 } }
    else if (path === '/api/v2/settings/mcp-token') data = { configured: false, source: 'none', masked_token: null, auth_header: 'X-StockPro-MCP-Token', token_env: 'STOCKPRO_MCP_API_TOKEN', legacy_auth_header: 'X-BitPro-MCP-Token', legacy_token_env: 'BITPRO_MCP_API_TOKEN', remote_enabled: false, remote_path: '/api/v2/mcp', require_token: true }
    else if (path === '/api/v2/settings/feishu-webhook') data = { webhook_configured: false, masked_webhook_url: null, source: 'none' }
    else if (path === '/api/v2/settings/llm-providers/dashscope/capabilities') data = { provider_key: 'dashscope', display_name: 'DashScope', transport_type: 'openai_chat', models: ['qwen3.6-plus'], reasoning_efforts: [], speed_modes: [], supports_tools: true, supports_structured_output: true, supports_resume: false, configured: false, healthy: false, status_detail: '未配置服务端 API Key', credential_mode: 'env', credential_source: null, default_model: 'qwen3.6-plus', enabled: true, active: true }
    else if (path === '/api/v2/agent/tasks' || path === '/api/v2/agent/strategy-optimizer/runs' || path === '/api/v2/agent/autonomous-trader/instances') data = []
    else if (path.startsWith('/api/v2/agent/')) data = { items: [], total: 0, status: 'unavailable' }
    else if (path.startsWith('/api/v2/arc/')) data = { configured: false, items: [], tasks: [], status: 'unavailable' }
    else if (path.startsWith('/api/v2/signals') || path.startsWith('/api/v2/signal-') || path.startsWith('/api/v2/watch/')) data = { items: [], total: 0 }
    else if (path === '/api/v2/arbitrage/summary') data = { status: 'unavailable', configured_exchanges: [], opportunities: [], spread_matrix: [], funding_rankings: [], portfolio_positions: [], leg_status: [], net_exposure: { total_usdt: 0, by_symbol: [] }, pnl: { estimated_usdt: 0, actual_usdt: 0, funding_usdt: 0, spread_usdt: 0, fee_usdt: 0 }, empty_reason: '当前没有经过验证的 ETF、LOF 或可转债申赎/折溢价数据。数据接通前保持诚实空态，不生成虚假套利机会。' }
    else if (path === '/api/v2/onchain/summary') data = { status: 'partial', as_of: null, source: { provider: 'PostgreSQL A-share datasets', auth_required: false, endpoints: {} }, source_status: { capital_flow: 'catalogued', shareholders: 'catalogued', fundamentals: 'catalogued' }, kpis: {}, chains: [], protocols: [], fees: [], stablecoins: [], stablecoin_chains: [], yield_pools: [], warnings: [], empty_reason: '当前 PostgreSQL 已登记股东、资金流和基本面数据域，但尚未形成可验证的冻结快照。明细适配完成前保持诚实空态，不用模拟数据填充。' }
    else if (path === '/api/v2/orderflow/stream-status') data = { enabled: false, connected: false, subscribed_count: 0, total_ingested: 0, total_filtered: 0, buffer_size: 0, reconnects: 0, last_msg_at: null, last_flush_at: null, last_error: 'A-share tick Provider not configured', min_notional_usdt: 0, inst_ids: [] }
    else if (path.startsWith('/api/v2/orderflow/')) data = []
    else if (path.startsWith('/api/v2/research-workbench/')) data = { items: [], total: 0, status: 'unavailable' }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
  })
}
