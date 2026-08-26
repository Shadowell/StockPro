CREATE TABLE IF NOT EXISTS market_phase_results (
    trade_date DATE PRIMARY KEY,
    phase TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok','partial','unknown','failed')),
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_inputs JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_snapshot_id BIGINT REFERENCES market_evidence_snapshots(id) ON DELETE RESTRICT,
    input_trade_date DATE NOT NULL,
    definition_version TEXT NOT NULL DEFAULT 'ashare-market-phase.v1',
    available_at TIMESTAMPTZ NOT NULL,
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS sector_rps_results (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    classification_system TEXT NOT NULL CHECK (classification_system IN ('industry','concept')),
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    strength_score DOUBLE PRECISION,
    rps_percentile DOUBLE PRECISION,
    rank INTEGER,
    rank_change INTEGER,
    strong_days INTEGER NOT NULL DEFAULT 0,
    member_coverage DOUBLE PRECISION,
    member_count INTEGER NOT NULL DEFAULT 0,
    leader_symbol TEXT,
    leader_contribution_pct DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','partial','unknown','failed')),
    missing_inputs JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_snapshot_id BIGINT REFERENCES market_evidence_snapshots(id) ON DELETE RESTRICT,
    definition_version TEXT NOT NULL DEFAULT 'ashare-sector-rps.v1',
    available_at TIMESTAMPTZ NOT NULL,
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(trade_date, classification_system, sector_code, definition_version)
);

CREATE TABLE IF NOT EXISTS sector_rps_member_contributions (
    rps_result_id BIGINT NOT NULL REFERENCES sector_rps_results(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    symbol_name TEXT,
    return_20d DOUBLE PRECISION,
    amount_share DOUBLE PRECISION,
    limit_up_count INTEGER,
    contribution_score DOUBLE PRECISION,
    data_status TEXT NOT NULL DEFAULT 'ok',
    missing_inputs JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY(rps_result_id, symbol)
);

CREATE TABLE IF NOT EXISTS symbol_abnormal_metrics (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    return_3d DOUBLE PRECISION,
    return_10d DOUBLE PRECISION,
    return_30d DOUBLE PRECISION,
    benchmark_code TEXT DEFAULT '000300.SH',
    benchmark_deviation_3d DOUBLE PRECISION,
    benchmark_deviation_10d DOUBLE PRECISION,
    benchmark_deviation_30d DOUBLE PRECISION,
    sector_code TEXT,
    sector_deviation_3d DOUBLE PRECISION,
    sector_deviation_10d DOUBLE PRECISION,
    sector_deviation_30d DOUBLE PRECISION,
    amount_ratio_5d DOUBLE PRECISION,
    volume_zscore_20d DOUBLE PRECISION,
    turnover_zscore_60d DOUBLE PRECISION,
    distance_to_60d_high_pct DOUBLE PRECISION,
    distance_to_60d_low_pct DOUBLE PRECISION,
    distance_to_limit_up_pct DOUBLE PRECISION,
    distance_to_limit_down_pct DOUBLE PRECISION,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','partial','unknown','failed')),
    missing_inputs JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_snapshot_id BIGINT REFERENCES market_evidence_snapshots(id) ON DELETE RESTRICT,
    definition_version TEXT NOT NULL DEFAULT 'ashare-abnormality.v1',
    available_at TIMESTAMPTZ NOT NULL,
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(symbol, trade_date, definition_version),
    CHECK (symbol ~ '^[0-9]{6}\.(SH|SZ|BJ)$')
);

CREATE TABLE IF NOT EXISTS fundamental_factor_facts (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    factor_code TEXT NOT NULL,
    report_period DATE NOT NULL,
    ann_date DATE,
    announcement_available_at TIMESTAMPTZ NOT NULL,
    source_fetch_run_id BIGINT REFERENCES source_fetch_runs(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL DEFAULT 1,
    value DOUBLE PRECISION,
    quality_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
    definition_version TEXT NOT NULL DEFAULT 'ashare-fundamental-pit.v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(symbol, factor_code, report_period, announcement_available_at, revision),
    CHECK (symbol ~ '^[0-9]{6}\.(SH|SZ|BJ)$')
);

ALTER TABLE factor_daily_values
    ADD COLUMN IF NOT EXISTS source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_sector_rps_date_rank
    ON sector_rps_results(trade_date DESC, classification_system, rank);
CREATE INDEX IF NOT EXISTS idx_symbol_abnormal_date_return
    ON symbol_abnormal_metrics(trade_date DESC, (ABS(COALESCE(return_3d, 0))) DESC);
CREATE INDEX IF NOT EXISTS idx_fundamental_factor_pit
    ON fundamental_factor_facts(symbol, factor_code, announcement_available_at DESC, revision DESC);

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
    ('market_phase', 'A股六阶段市场情绪', 'postgresql_market_evidence', NULL, 'ashare-market-phase.v1', '{"available_at":"post_close","requires":["breadth","turnover","limit_up","sector_diffusion"],"read_requires_computed_result":true}'::jsonb, TRUE),
    ('sector_rps', '行业/概念 RPS 轮动', 'postgresql_market_evidence', NULL, 'ashare-sector-rps.v1', '{"classification_systems":["industry","concept"],"requires_member_coverage":0.8,"read_requires_computed_result":true}'::jsonb, TRUE),
    ('symbol_abnormality', '个股异动与关键价位', 'postgresql_daily_bars', NULL, 'ashare-abnormality.v1', '{"lookbacks":[3,10,30,60],"available_at":"post_close","read_requires_computed_result":true}'::jsonb, TRUE),
    ('fundamental_factor_facts', '公告时点约束财务因子事实', 'tushare', NULL, 'ashare-fundamental-pit.v1', '{"available_at":"announcement_available_at","revision_policy":"latest_known_at_simulated_at","no_ann_date_no_backfill":true}'::jsonb, TRUE)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    primary_source = EXCLUDED.primary_source,
    fallback_source = EXCLUDED.fallback_source,
    schema_version = EXCLUDED.schema_version,
    quality_policy = EXCLUDED.quality_policy,
    enabled = EXCLUDED.enabled,
    updated_at = NOW();

INSERT INTO factor_definitions (
    factor_code,
    factor_name,
    category,
    subcategory,
    description,
    formula,
    data_source,
    update_frequency,
    unit,
    direction,
    research_status,
    enabled
)
VALUES
    ('momentum.max_return_20d', '20日最大单日收益', 'momentum', 'short_line', '最近20个交易日中最大单日收益，窗口不足返回 null。', 'max(daily_return,20)', 'daily_bars', 'daily', 'percent', 1, 'exploratory', TRUE),
    ('momentum.return_skew_20d', '20日收益偏度', 'momentum', 'short_line', '最近20个交易日收益分布偏度，窗口不足返回 null。', 'skew(daily_return,20)', 'daily_bars', 'daily', 'ratio', 1, 'exploratory', TRUE),
    ('momentum.up_days_20d', '20日上涨天数占比', 'momentum', 'short_line', '最近20个交易日上涨天数占比，使用已确认日线。', 'count(return>0,20)/20', 'daily_bars', 'daily', 'ratio', 1, 'exploratory', TRUE),
    ('liquidity.turnover_z_60d', '换手率60日Z-Score', 'liquidity', 'short_line', '当前换手率相对60日窗口的标准差倍数，缺 daily_basic/换手返回 null。', 'zscore(turnover_rate,60)', 'daily_basic', 'daily', 'standard_deviation', 1, 'exploratory', TRUE),
    ('event.limit_up_count_20d', '20日涨停次数', 'event', 'limit_price', '最近20个交易日涨停次数，缺涨跌停数据返回 null。', 'count(limit_up,20)', 'price_limits', 'daily', 'count', 1, 'exploratory', TRUE),
    ('event.limit_up_count_60d', '60日涨停次数', 'event', 'limit_price', '最近60个交易日涨停次数，缺涨跌停数据返回 null。', 'count(limit_up,60)', 'price_limits', 'daily', 'count', 1, 'exploratory', TRUE),
    ('liquidity.amihud_20d', 'Amihud 20日非流动性', 'liquidity', 'capacity', '20日平均 |收益率| / 成交额；零成交额返回 null。', 'avg(abs(return)/amount,20)', 'daily_bars', 'daily', 'ratio', -1, 'exploratory', TRUE),
    ('volume.amount_ratio_5d', '5日成交额相对20日均值', 'volume', 'short_line', '近5日成交额均值除以20日成交额均值，窗口不足返回 null。', 'avg(amount,5)/avg(amount,20)', 'daily_bars', 'daily', 'ratio', 1, 'exploratory', TRUE),
    ('price.gap_return', '跳空收益', 'price', 'short_line', '今日开盘价相对昨日收盘价收益，避免使用未来数据。', 'open/prev_close-1', 'daily_bars', 'daily', 'percent', 1, 'exploratory', TRUE),
    ('price.intraday_return', '日内收益', 'price', 'short_line', '今日收盘价相对今日开盘价收益。', 'close/open-1', 'daily_bars', 'daily', 'percent', 1, 'exploratory', TRUE),
    ('fundamental.roe_ttm_pit', '公告时点ROE TTM', 'fundamental', 'profitability', '只使用 announcement_available_at <= simulated_at 的最新已知 ROE 版本。', 'net_profit_ttm/avg_equity', 'fundamental_factor_facts', 'quarterly', 'percent', 1, 'exploratory', TRUE),
    ('fundamental.roa_ttm_pit', '公告时点ROA TTM', 'fundamental', 'profitability', '只使用 announcement_available_at <= simulated_at 的最新已知 ROA 版本。', 'net_profit_ttm/avg_assets', 'fundamental_factor_facts', 'quarterly', 'percent', 1, 'exploratory', TRUE),
    ('fundamental.gross_margin_pit', '公告时点毛利率', 'fundamental', 'profitability', '按公告可用时间约束的毛利率因子。', 'gross_profit/revenue', 'fundamental_factor_facts', 'quarterly', 'percent', 1, 'exploratory', TRUE),
    ('fundamental.net_margin_pit', '公告时点净利率', 'fundamental', 'profitability', '按公告可用时间约束的净利率因子。', 'net_profit/revenue', 'fundamental_factor_facts', 'quarterly', 'percent', 1, 'exploratory', TRUE),
    ('fundamental.revenue_growth_yoy_pit', '公告时点营收同比增长', 'fundamental', 'growth', '只在公告后可见的营收同比增长。', 'revenue_yoy', 'fundamental_factor_facts', 'quarterly', 'percent', 1, 'exploratory', TRUE),
    ('fundamental.net_profit_growth_yoy_pit', '公告时点净利润同比增长', 'fundamental', 'growth', '只在公告后可见的净利润同比增长。', 'net_profit_yoy', 'fundamental_factor_facts', 'quarterly', 'percent', 1, 'exploratory', TRUE),
    ('fundamental.ocf_quality_pit', '公告时点经营现金流质量', 'fundamental', 'quality', '经营现金流净额相对净利润，按公告可用时间约束。', 'net_operate_cash_flow/net_profit', 'fundamental_factor_facts', 'quarterly', 'ratio', 1, 'exploratory', TRUE),
    ('fundamental.debt_asset_ratio_pit', '公告时点资产负债率', 'fundamental', 'leverage', '总负债相对总资产，按公告可用时间约束。', 'total_liab/total_assets', 'fundamental_factor_facts', 'quarterly', 'percent', -1, 'exploratory', TRUE),
    ('fundamental.dividend_yield_pit', '公告时点股息率', 'fundamental', 'shareholder_return', '基于已公告分红事实和可见价格计算，缺公告日不回填。', 'cash_dividend/price', 'fundamental_factor_facts', 'annual', 'percent', 1, 'exploratory', TRUE)
ON CONFLICT (factor_code) DO UPDATE SET
    factor_name = EXCLUDED.factor_name,
    category = EXCLUDED.category,
    subcategory = EXCLUDED.subcategory,
    description = EXCLUDED.description,
    formula = EXCLUDED.formula,
    data_source = EXCLUDED.data_source,
    update_frequency = EXCLUDED.update_frequency,
    unit = EXCLUDED.unit,
    direction = EXCLUDED.direction,
    research_status = EXCLUDED.research_status,
    enabled = EXCLUDED.enabled,
    updated_at = NOW();
