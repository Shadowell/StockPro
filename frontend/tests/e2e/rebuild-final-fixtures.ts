import type { Page, Route } from '@playwright/test'

export async function installFinalFixtures(page: Page, role: 'admin' | 'guest' = 'admin') {
  await page.route('**/api/v2/**', async (route: Route) => {
    const path = new URL(route.request().url()).pathname
    let data: any = { items: [], total: 0 }

    if (path === '/api/v2/auth/me') data = { auth_enabled: false, authenticated: true, role, permissions: role === 'admin' ? ['admin'] : ['read', 'backtest'] }
    else if (path === '/api/v2/system/health') data = { status: 'healthy', project: 'StockPro', database: 'postgresql', private_exchange: false }
    else if (path === '/api/v2/market/tickers') data = []
    else if (path === '/api/v2/market/native-sentiment') data = { core: [], pipeline: { security_master: { rows: 0, from: '', to: '' }, daily_bars: { rows: 0, from: '', to: '' } } }
    else if (path === '/api/v2/market/symbols') data = { symbols: [] }
    else if (path === '/api/v2/market/klines' || path === '/api/v2/market/trades') data = []
    else if (path === '/api/v2/market/indicators') data = { source: 'backend_derived_from_ohlcv', data_source: 'market_klines', timestamps: [], series: {} }
    else if (path === '/api/v2/market/orderbook') data = { bids: [], asks: [], source: 'unavailable' }
    else if (path === '/api/v2/market/ticker') data = { symbol: '', last: 0, change_percent: 0 }
    else if (path === '/api/v2/strategies') data = { items: [], total: 0, page: 1, per_page: 60, pages: 1, status_counts: { all: 0 }, asset_counts: { all: 0 }, type_counts: { all: 0 }, timeframe_counts: { all: 0 }, capital_counts: { all: 0 } }
    else if (path === '/api/v2/backtest/configuration') data = { items: [] }
    else if (path === '/api/v2/backtest/results' || path === '/api/v2/backtest/jobs') data = []
    else if (path === '/api/v2/live/instances') data = { items: [] }
    else if (path === '/api/v2/live/candidates') data = []
    else if (path === '/api/v2/live/dashboard') data = { system: { state: 'idle', exchange: 'CN', symbol: '', symbols: [], timeframe: '1d', strategy: '', strategy_id: null, dry_run: true, mode: 'paper' }, equity: {}, performance: {}, risk: {}, positions: [], account: {}, recent_events: [], feishu: { enabled: false } }
    else if (path === '/api/v2/live/accounts' || path.startsWith('/api/v2/live/')) data = []
    else if (path === '/api/v2/monitor/summary') data = { overall_status: 'unavailable', services: [], data: {}, strategy_health: [], active_alerts: [], notifications: [], source_label: 'PostgreSQL', source_updated_at: null }
    else if (path === '/api/v2/monitor/active_strategies' || path === '/api/v2/monitor/alerts') data = []
    else if (path === '/api/v2/monitor/long-short-ratio') data = { ratio: null, source: 'unavailable' }
    else if (path === '/api/v2/monitor/open-interest') data = { open_interest: null, source: 'unavailable' }
    else if (path === '/api/v2/review/summary') data = { overview: { review_window: '24h', bucket: '1h', updated_at: null, strategy_count: 0, sample_strategy_count: 0, overall_return_pct: 0, median_return_pct: 0, max_drawdown_pct: 0, observe_count: 0, review_count: 0, sample_health_pct: 0 }, groups: [], leaderboard: { observe: [], review: [] }, heatmap: [], tags: [], next_actions: [] }
    else if (path === '/api/v2/data/status') data = { storage: 'postgresql', provider_state: 'restricted', datasets: 0, published_partitions: 0, published_rows: 0, sealed_snapshots: 0, sync_jobs: 0, quality_issues: 0, staged_imports: 0, provider_calls_performed: 0 }
    else if (path.startsWith('/api/v2/data/')) data = { items: [], total: 0, provider_calls_performed: 0 }
    else if (path === '/api/v2/factorlab/summary') data = { status: 'ready', phase: 'a_share_catalog', statistics: { definition_count: 0, instance_count: 0, latest_value_count: 0, materialized_partition_count: 0, research_task_count: 0, trial_count: 0 }, definitions: [], instances: [], latest_values: [], data_plane: { format: 'PostgreSQL', layout: 'partitioned', manifest: 'sealed' }, capabilities: { api_mode: 'a_share_catalog', materialization_store_ready: true, research_metrics_available: false, strategy_runtime_connected: false, paper_live_connected: false } }
    else if (path === '/api/v2/factorlab/research/tasks') data = []
    else if (path.startsWith('/api/v2/factorlab/')) data = []
    else if (path === '/api/v2/settings/llm-model') data = { provider_key: '', provider_name: 'Not configured', model: '', default_model: '', models: [], free_tier_models: [], model_fallback_enabled: false, base_url: '', enable_thinking: false, request_timeout: 180, api_key_configured: false, api_key_source: null, providers: [], provider_capabilities: [] }
    else if (path === '/api/v2/agent/tasks' || path === '/api/v2/agent/strategy-optimizer/runs' || path === '/api/v2/agent/autonomous-trader/instances') data = []
    else if (path.startsWith('/api/v2/agent/')) data = { items: [], total: 0, status: 'unavailable' }
    else if (path.startsWith('/api/v2/arc/')) data = { configured: false, items: [], tasks: [], status: 'unavailable' }
    else if (path.startsWith('/api/v2/signals') || path.startsWith('/api/v2/signal-') || path.startsWith('/api/v2/watch/')) data = { items: [], total: 0 }
    else if (path === '/api/v2/arbitrage/summary') data = { status: 'unavailable', configured_exchanges: [], opportunities: [], spread_matrix: [], funding_rankings: [], portfolio_positions: [], leg_status: [], net_exposure: { total_usdt: 0, by_symbol: [] }, pnl: { estimated_usdt: 0, actual_usdt: 0, funding_usdt: 0, spread_usdt: 0, fee_usdt: 0 }, empty_reason: '当前没有经过验证的 ETF、LOF 或可转债申赎/折溢价数据。数据接通前保持诚实空态，不生成虚假套利机会。' }
    else if (path === '/api/v2/onchain/summary') data = { status: 'partial', as_of: null, source: { provider: 'PostgreSQL A-share datasets', auth_required: false, endpoints: {} }, source_status: { capital_flow: 'catalogued', shareholders: 'catalogued', fundamentals: 'catalogued' }, kpis: {}, chains: [], protocols: [], fees: [], stablecoins: [], stablecoin_chains: [], yield_pools: [], warnings: [], empty_reason: '当前 PostgreSQL 已登记股东、资金流和基本面数据域，但尚未形成可验证的冻结快照。明细适配完成前保持诚实空态，不用模拟数据填充。' }
    else if (path === '/api/v2/orderflow/stream-status') data = { enabled: false, connected: false, subscribed_count: 0, total_ingested: 0, total_filtered: 0, buffer_size: 0, reconnects: 0, last_msg_at: null, last_flush_at: null, last_error: 'A-share tick Provider not configured', min_notional_usdt: 0, inst_ids: [] }
    else if (path.startsWith('/api/v2/orderflow/')) data = []
    else if (path === '/api/v2/sync/status') data = { is_running: false, current_job: null, summary: { total_records: 0, exchanges: ['CN'], symbols_count: 0, pairs: 0 }, details: [] }
    else if (path === '/api/v2/sync/table-stats') data = []
    else if (path === '/api/v2/sync/config') data = { enabled: false, schedules: [] }
    else if (path.startsWith('/api/v2/research-workbench/')) data = { items: [], total: 0, status: 'unavailable' }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
  })
}
