INSERT INTO dataset_definitions (
    code,
    name,
    primary_source,
    fallback_source,
    schema_version,
    quality_policy,
    enabled
)
VALUES
    ('security_master', '证券主数据与历史状态', 'tushare', 'akshare', 'ashare.dataset.v1', '{"required_fields":["symbol","name","exchange","list_status"],"available_at":"collection_finished","seal_required":true}'::jsonb, TRUE),
    ('trade_calendar', 'A股交易日历', 'tushare', NULL, 'ashare.dataset.v1', '{"required_fields":["trade_date","is_open"],"available_at":"collection_finished","seal_required":true}'::jsonb, TRUE),
    ('daily_bars', '未复权日线行情', 'tushare', 'akshare', 'ashare.dataset.v1', '{"required_fields":["trade_date","symbol","open","high","low","close","volume","turnover"],"available_at":"after_market_close_collection","seal_required":true}'::jsonb, TRUE),
    ('adj_factor', '复权因子', 'tushare', NULL, 'ashare.dataset.v1', '{"required_fields":["trade_date","symbol","adj_factor"],"available_at":"after_market_close_collection","seal_required":true}'::jsonb, TRUE),
    ('daily_basic', '每日估值与换手', 'tushare', 'akshare', 'ashare.dataset.v1', '{"required_fields":["trade_date","symbol"],"null_policy":"preserve_null_fundamental_values","available_at":"source_published","seal_required":true}'::jsonb, TRUE),
    ('suspensions', '停复牌', 'tushare', NULL, 'ashare.dataset.v1', '{"required_fields":["trade_date","symbol"],"empty_partition_policy":"valid_empty_day","available_at":"collection_finished","seal_required":true}'::jsonb, TRUE),
    ('price_limits', '涨跌停价格', 'tushare', 'akshare', 'ashare.dataset.v1', '{"required_fields":["trade_date","symbol","has_price_limit"],"sentinel_policy":"ipo_or_no_limit_must_be_explicit","available_at":"before_execution_replay","seal_required":true}'::jsonb, TRUE),
    ('corporate_actions', '公司行动', 'tushare', NULL, 'ashare.dataset.v1', '{"required_fields":["symbol","action_type","ex_date","announcement_available_at"],"available_at":"announcement_available_at","seal_required":true}'::jsonb, TRUE),
    ('benchmark_bars', '基准指数日线', 'tushare', NULL, 'ashare.dataset.v1', '{"required_fields":["trade_date","symbol","close"],"available_at":"after_market_close_collection","seal_required":true}'::jsonb, TRUE)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    primary_source = EXCLUDED.primary_source,
    fallback_source = EXCLUDED.fallback_source,
    schema_version = EXCLUDED.schema_version,
    quality_policy = EXCLUDED.quality_policy,
    enabled = EXCLUDED.enabled,
    updated_at = NOW();

INSERT INTO source_entitlements (
    dataset_code,
    source,
    permission_state,
    cache_policy,
    export_policy,
    contract_version,
    checked_at
)
VALUES
    ('security_master', 'tushare', 'requires_configuration', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('security_master', 'akshare', 'fallback_available_when_enabled', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('trade_calendar', 'tushare', 'requires_configuration', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('daily_bars', 'tushare', 'requires_configuration', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('daily_bars', 'akshare', 'fallback_available_when_enabled', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('adj_factor', 'tushare', 'requires_configuration', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('daily_basic', 'tushare', 'requires_configuration', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('daily_basic', 'akshare', 'fallback_available_when_enabled', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('suspensions', 'tushare', 'requires_configuration', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('price_limits', 'tushare', 'requires_configuration', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('price_limits', 'akshare', 'fallback_available_when_enabled', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('corporate_actions', 'tushare', 'requires_configuration', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW()),
    ('benchmark_bars', 'tushare', 'requires_configuration', 'local_pg_research_only', 'disabled', 'ashare.dataset.v1', NOW())
ON CONFLICT (dataset_code, source) DO UPDATE SET
    permission_state = EXCLUDED.permission_state,
    cache_policy = EXCLUDED.cache_policy,
    export_policy = EXCLUDED.export_policy,
    contract_version = EXCLUDED.contract_version,
    checked_at = NOW();

INSERT INTO dataset_sync_schedules (
    code,
    cron,
    timezone,
    enabled,
    catchup_days,
    max_retries
)
VALUES
    ('ashare_eod_research_v1', '30 17 * * 1-5', 'Asia/Shanghai', FALSE, 5, 3)
ON CONFLICT (code) DO UPDATE SET
    cron = EXCLUDED.cron,
    timezone = EXCLUDED.timezone,
    enabled = FALSE,
    catchup_days = EXCLUDED.catchup_days,
    max_retries = EXCLUDED.max_retries,
    updated_at = NOW();
