DROP TRIGGER IF EXISTS trg_factor_values_immutable ON factor_daily_values;

ALTER TABLE factor_daily_values
    ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ;

UPDATE factor_daily_values
SET available_at = (trade_date::timestamp + TIME '17:30') AT TIME ZONE 'Asia/Shanghai'
WHERE available_at IS NULL;

ALTER TABLE factor_daily_values ALTER COLUMN available_at SET NOT NULL;

CREATE TRIGGER trg_factor_values_immutable
    BEFORE UPDATE OR DELETE ON factor_daily_values
    FOR EACH ROW EXECUTE FUNCTION prevent_published_factor_mutation();

CREATE TABLE IF NOT EXISTS backtest_cost_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    commission_rate NUMERIC(12,8) NOT NULL,
    minimum_commission NUMERIC(18,4) NOT NULL,
    stamp_duty_rate NUMERIC(12,8) NOT NULL,
    transfer_fee_rate NUMERIC(12,8) NOT NULL,
    slippage_rate NUMERIC(12,8) NOT NULL,
    max_participation_rate NUMERIC(12,8) NOT NULL DEFAULT 0.10,
    price_impact_rate NUMERIC(12,8) NOT NULL DEFAULT 0,
    calculation_version TEXT NOT NULL DEFAULT 'ashare-cost.v1',
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(code, version),
    UNIQUE(content_hash)
);

INSERT INTO backtest_cost_models
    (code, version, name, commission_rate, minimum_commission, stamp_duty_rate,
     transfer_fee_rate, slippage_rate, max_participation_rate, price_impact_rate, content_hash)
VALUES
    ('cn_stock_default', 1, 'A股日频默认成本 v1', 0.0003, 5, 0.0005,
     0.00001, 0.0002, 0.10, 0,
     encode(digest('cn_stock_default|1|0.0003|5|0.0005|0.00001|0.0002|0.10|0', 'sha256'), 'hex'))
ON CONFLICT (code, version) DO NOTHING;

CREATE TABLE IF NOT EXISTS research_protocols (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    universe_description TEXT NOT NULL DEFAULT '',
    benchmark_code TEXT NOT NULL DEFAULT '000300.SH',
    train_start DATE NOT NULL,
    train_end DATE NOT NULL,
    validation_start DATE,
    validation_end DATE,
    out_of_sample_start DATE NOT NULL,
    out_of_sample_end DATE NOT NULL,
    embargo_days INTEGER NOT NULL DEFAULT 0 CHECK (embargo_days >= 0),
    capacity_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
    promotion_thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
    rejected_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
    selection_rationale TEXT,
    content_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sealed', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sealed_at TIMESTAMPTZ,
    CHECK (train_start <= train_end),
    CHECK (out_of_sample_start <= out_of_sample_end)
);

CREATE TABLE IF NOT EXISTS backtest_experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    strategy_version_id UUID NOT NULL REFERENCES strategy_versions(id) ON DELETE RESTRICT,
    dataset_snapshot_id BIGINT NOT NULL REFERENCES dataset_snapshots(id) ON DELETE RESTRICT,
    factor_snapshot_id BIGINT REFERENCES factor_snapshots(id) ON DELETE RESTRICT,
    universe_snapshot_id BIGINT NOT NULL REFERENCES universe_snapshots(id) ON DELETE RESTRICT,
    research_protocol_id UUID REFERENCES research_protocols(id) ON DELETE RESTRICT,
    cost_model_id UUID NOT NULL REFERENCES backtest_cost_models(id) ON DELETE RESTRICT,
    benchmark_code TEXT NOT NULL,
    base_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'running', 'completed', 'failed', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

ALTER TABLE backtest_runs
    ADD COLUMN IF NOT EXISTS replay_run_id UUID REFERENCES strategy_replay_runs(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS experiment_id UUID REFERENCES backtest_experiments(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS dataset_snapshot_id BIGINT REFERENCES dataset_snapshots(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS pool_snapshot_id BIGINT,
    ADD COLUMN IF NOT EXISTS factor_snapshot_id BIGINT REFERENCES factor_snapshots(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS universe_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS universe_snapshot_id BIGINT REFERENCES universe_snapshots(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS corporate_action_snapshot_id BIGINT REFERENCES dataset_snapshots(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS knowledge_cutoff_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS research_protocol_id UUID REFERENCES research_protocols(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS cost_model_id UUID REFERENCES backtest_cost_models(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS benchmark_code TEXT,
    ADD COLUMN IF NOT EXISTS strategy_api_version TEXT,
    ADD COLUMN IF NOT EXISTS input_hash TEXT,
    ADD COLUMN IF NOT EXISTS run_mode TEXT NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS progress NUMERIC(5,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS promotion_status TEXT NOT NULL DEFAULT 'not_evaluated',
    ADD COLUMN IF NOT EXISTS initial_cash NUMERIC(20,4),
    ADD COLUMN IF NOT EXISTS frequency TEXT NOT NULL DEFAULT '1d',
    ADD COLUMN IF NOT EXISTS calculation_version TEXT NOT NULL DEFAULT 'backtest.v1',
    ADD COLUMN IF NOT EXISTS result_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS sealed_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'backtest_runs_run_mode_check') THEN
        ALTER TABLE backtest_runs ADD CONSTRAINT backtest_runs_run_mode_check
            CHECK (run_mode IN ('legacy', 'quick', 'full'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_backtest_runs_input_full
    ON backtest_runs(input_hash) WHERE run_mode = 'full' AND status = 'success';
CREATE INDEX IF NOT EXISTS idx_backtest_runs_experiment ON backtest_runs(experiment_id, created_at);

CREATE TABLE IF NOT EXISTS backtest_matrix_cells (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES backtest_experiments(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL,
    parameters JSONB NOT NULL,
    parameter_hash TEXT NOT NULL,
    backtest_run_id UUID REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'success', 'failed', 'cancelled')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    UNIQUE(experiment_id, parameter_hash)
);

CREATE TABLE IF NOT EXISTS backtest_metrics (
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    metric_code TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    unit TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    input_frequency TEXT NOT NULL,
    null_reason TEXT,
    metric_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(backtest_run_id, metric_code)
);

CREATE TABLE IF NOT EXISTS backtest_daily_equity (
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    trade_date DATE NOT NULL,
    strategy_nav DOUBLE PRECISION NOT NULL,
    strategy_return DOUBLE PRECISION,
    benchmark_nav DOUBLE PRECISION,
    benchmark_return DOUBLE PRECISION,
    excess_nav DOUBLE PRECISION,
    excess_return DOUBLE PRECISION,
    equity NUMERIC(20,4) NOT NULL,
    cash NUMERIC(20,4) NOT NULL,
    market_value NUMERIC(20,4) NOT NULL,
    gross_exposure DOUBLE PRECISION NOT NULL,
    net_exposure DOUBLE PRECISION NOT NULL,
    position_count INTEGER NOT NULL,
    drawdown DOUBLE PRECISION NOT NULL,
    excess_drawdown DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(backtest_run_id, trade_date)
);

CREATE TABLE IF NOT EXISTS backtest_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    replay_intent_id BIGINT REFERENCES strategy_replay_intents(id) ON DELETE RESTRICT,
    event_ordinal INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    intent_type TEXT NOT NULL,
    side TEXT CHECK (side IN ('buy', 'sell')),
    requested_value DOUBLE PRECISION,
    requested_quantity INTEGER,
    filled_quantity INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('created', 'accepted', 'rejected', 'filled', 'cancelled', 'expired')),
    signal_at TIMESTAMPTZ NOT NULL,
    data_available_at TIMESTAMPTZ NOT NULL,
    submitted_at TIMESTAMPTZ,
    earliest_fill_at TIMESTAMPTZ NOT NULL,
    filled_at TIMESTAMPTZ,
    execution_price NUMERIC(18,4),
    execution_price_source TEXT,
    rejection_code TEXT,
    rejection_reason TEXT,
    capacity_ratio DOUBLE PRECISION,
    intent_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_orders_run_time ON backtest_orders(backtest_run_id, signal_at, event_ordinal);

ALTER TABLE backtest_trades
    ADD COLUMN IF NOT EXISTS backtest_order_id UUID REFERENCES backtest_orders(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS signal_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS data_available_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS earliest_fill_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS tax NUMERIC(18,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS transfer_fee NUMERIC(18,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS slippage_cost NUMERIC(18,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS realized_pnl NUMERIC(20,4),
    ADD COLUMN IF NOT EXISTS holding_days INTEGER,
    ADD COLUMN IF NOT EXISTS execution_price_source TEXT;

CREATE TABLE IF NOT EXISTS backtest_daily_positions (
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    trade_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    available_quantity INTEGER NOT NULL,
    avg_cost NUMERIC(18,6) NOT NULL,
    close_price NUMERIC(18,4) NOT NULL,
    market_value NUMERIC(20,4) NOT NULL,
    weight DOUBLE PRECISION NOT NULL,
    unrealized_pnl NUMERIC(20,4) NOT NULL,
    industry_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(backtest_run_id, trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS backtest_logs (
    id BIGSERIAL PRIMARY KEY,
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    simulated_at TIMESTAMPTZ,
    level TEXT NOT NULL,
    source TEXT NOT NULL,
    message TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS backtest_custom_records (
    id BIGSERIAL PRIMARY KEY,
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    event_ordinal INTEGER NOT NULL,
    simulated_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(backtest_run_id, event_ordinal, payload_hash)
);

CREATE TABLE IF NOT EXISTS backtest_attribution (
    id BIGSERIAL PRIMARY KEY,
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    attribution_type TEXT NOT NULL CHECK (attribution_type IN ('symbol', 'industry', 'benchmark', 'cost')),
    attribution_key TEXT NOT NULL,
    contribution DOUBLE PRECISION,
    amount NUMERIC(20,4),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(backtest_run_id, attribution_type, attribution_key)
);

CREATE TABLE IF NOT EXISTS backtest_protocol_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    research_protocol_id UUID NOT NULL REFERENCES research_protocols(id) ON DELETE RESTRICT,
    sample_label TEXT NOT NULL CHECK (sample_label IN ('train', 'validation', 'out_of_sample')),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    metrics JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('passed', 'rejected', 'not_applicable')),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(backtest_run_id, sample_label)
);

CREATE TABLE IF NOT EXISTS backtest_promotion_checks (
    id BIGSERIAL PRIMARY KEY,
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    check_code TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('passed', 'failed', 'pending')),
    reason TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(backtest_run_id, check_code)
);

CREATE OR REPLACE FUNCTION prevent_sealed_backtest_mutation()
RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'success' AND (
        OLD.strategy_version_id IS DISTINCT FROM NEW.strategy_version_id OR
        OLD.dataset_snapshot_id IS DISTINCT FROM NEW.dataset_snapshot_id OR
        OLD.factor_snapshot_id IS DISTINCT FROM NEW.factor_snapshot_id OR
        OLD.universe_snapshot_id IS DISTINCT FROM NEW.universe_snapshot_id OR
        OLD.parameters IS DISTINCT FROM NEW.parameters OR
        OLD.start_date IS DISTINCT FROM NEW.start_date OR
        OLD.end_date IS DISTINCT FROM NEW.end_date OR
        OLD.cost_model_id IS DISTINCT FROM NEW.cost_model_id OR
        OLD.benchmark_code IS DISTINCT FROM NEW.benchmark_code OR
        OLD.input_hash IS DISTINCT FROM NEW.input_hash OR
        OLD.result_manifest IS DISTINCT FROM NEW.result_manifest
    ) THEN
        RAISE EXCEPTION 'sealed backtest inputs and result manifest are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_backtest_run_immutable ON backtest_runs;
CREATE TRIGGER trg_backtest_run_immutable
BEFORE UPDATE ON backtest_runs
FOR EACH ROW EXECUTE FUNCTION prevent_sealed_backtest_mutation();
