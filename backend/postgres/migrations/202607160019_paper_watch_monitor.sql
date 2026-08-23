-- Sprint 06: pinned Paper runtime, append-only audit events, alerts and health.

ALTER TABLE risk_rules ADD COLUMN IF NOT EXISTS rule_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE risk_rules ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE TABLE IF NOT EXISTS paper_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    strategy_version_id UUID NOT NULL REFERENCES strategy_versions(id) ON DELETE RESTRICT,
    dataset_snapshot_id BIGINT NOT NULL REFERENCES dataset_snapshots(id) ON DELETE RESTRICT,
    factor_snapshot_id BIGINT NOT NULL REFERENCES factor_snapshots(id) ON DELETE RESTRICT,
    universe_snapshot_id BIGINT NOT NULL REFERENCES universe_snapshots(id) ON DELETE RESTRICT,
    pool_snapshot_id BIGINT NOT NULL REFERENCES stock_pool_snapshots(id) ON DELETE RESTRICT,
    research_protocol_id UUID NOT NULL REFERENCES research_protocols(id) ON DELETE RESTRICT,
    qualifying_backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    portfolio_id UUID NOT NULL UNIQUE REFERENCES portfolios(id) ON DELETE RESTRICT,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    capacity_limits JSONB NOT NULL DEFAULT '{}'::jsonb,
    feed_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','starting','running','paused','stopping','stopped','failed')),
    runtime_version TEXT NOT NULL,
    last_processed_trade_date DATE,
    last_cycle_key TEXT,
    heartbeat_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_runtime_cycles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_instance_id UUID NOT NULL REFERENCES paper_instances(id) ON DELETE RESTRICT,
    cycle_key TEXT NOT NULL,
    trade_date DATE NOT NULL,
    data_available_at TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','blocked','failed')),
    signal_count INTEGER NOT NULL DEFAULT 0,
    order_count INTEGER NOT NULL DEFAULT 0,
    trade_count INTEGER NOT NULL DEFAULT 0,
    ledger_difference NUMERIC(20,4),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    UNIQUE(paper_instance_id, cycle_key)
);

CREATE TABLE IF NOT EXISTS paper_instance_events (
    id BIGSERIAL PRIMARY KEY,
    paper_instance_id UUID NOT NULL REFERENCES paper_instances(id) ON DELETE RESTRICT,
    cycle_id UUID REFERENCES paper_runtime_cycles(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('info','warning','error','critical')),
    message TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_equity_snapshots (
    id BIGSERIAL PRIMARY KEY,
    paper_instance_id UUID NOT NULL REFERENCES paper_instances(id) ON DELETE RESTRICT,
    cycle_id UUID NOT NULL REFERENCES paper_runtime_cycles(id) ON DELETE RESTRICT,
    trade_date DATE NOT NULL,
    cash NUMERIC(20,4) NOT NULL,
    market_value NUMERIC(20,4) NOT NULL,
    equity NUMERIC(20,4) NOT NULL,
    gross_exposure NUMERIC(20,8) NOT NULL,
    nav NUMERIC(20,8) NOT NULL,
    drawdown NUMERIC(20,8) NOT NULL,
    ledger_difference NUMERIC(20,4) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(paper_instance_id, trade_date)
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL,
    rule_version INTEGER NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('signal','pool','data','risk','system')),
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(code,rule_version)
);

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_rule_id UUID REFERENCES alert_rules(id) ON DELETE RESTRICT,
    paper_instance_id UUID REFERENCES paper_instances(id) ON DELETE RESTRICT,
    category TEXT NOT NULL CHECK (category IN ('signal','pool','data','risk','system')),
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    source_object_type TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    dedupe_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','acknowledged','resolved')),
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT,
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS service_health_snapshots (
    id BIGSERIAL PRIMARY KEY,
    service_code TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('healthy','warning','critical','unavailable')),
    latency_ms DOUBLE PRECISION,
    last_success_at TIMESTAMPTZ,
    error_code TEXT,
    message TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id BIGSERIAL PRIMARY KEY,
    alert_id UUID NOT NULL REFERENCES alerts(id) ON DELETE RESTRICT,
    channel TEXT NOT NULL CHECK (channel IN ('in_app','log')),
    status TEXT NOT NULL CHECK (status IN ('pending','delivered','failed','acknowledged')),
    attempt INTEGER NOT NULL DEFAULT 1,
    error_message TEXT,
    delivered_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(alert_id,channel,attempt)
);

ALTER TABLE strategy_signals ADD COLUMN IF NOT EXISTS paper_instance_id UUID REFERENCES paper_instances(id) ON DELETE RESTRICT;
ALTER TABLE strategy_signals ADD COLUMN IF NOT EXISTS signal_key TEXT;
ALTER TABLE strategy_signals ADD COLUMN IF NOT EXISTS data_available_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS paper_instance_id UUID REFERENCES paper_instances(id) ON DELETE RESTRICT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS risk_event_id UUID REFERENCES risk_events(id) ON DELETE SET NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS signal_time TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS data_available_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS earliest_fill_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS paper_instance_id UUID REFERENCES paper_instances(id) ON DELETE RESTRICT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS signal_time TIMESTAMPTZ;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS data_available_at TIMESTAMPTZ;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS earliest_fill_at TIMESTAMPTZ;
ALTER TABLE cash_ledger ADD COLUMN IF NOT EXISTS paper_instance_id UUID REFERENCES paper_instances(id) ON DELETE RESTRICT;
ALTER TABLE risk_events ADD COLUMN IF NOT EXISTS paper_instance_id UUID REFERENCES paper_instances(id) ON DELETE RESTRICT;
ALTER TABLE risk_events ADD COLUMN IF NOT EXISTS rule_version INTEGER;
ALTER TABLE risk_events ADD COLUMN IF NOT EXISTS decision TEXT CHECK (decision IN ('accepted','rejected','warned'));
ALTER TABLE risk_events ADD COLUMN IF NOT EXISTS input_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_signal_key ON strategy_signals(paper_instance_id,signal_key) WHERE paper_instance_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_paper_instances_status ON paper_instances(status,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_events_instance ON paper_instance_events(paper_instance_id,occurred_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(status,severity,triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_health_service_observed ON service_health_snapshots(service_code,observed_at DESC);

INSERT INTO risk_rules(name,rule_type,enabled,severity,config,rule_version,content_hash)
VALUES
 ('Paper Cash Floor v1','cash_floor',TRUE,'block','{"minimum_ratio":0.05}'::jsonb,1,'paper-risk-cash-floor-v1'),
 ('Paper Single Symbol v1','single_symbol_weight',TRUE,'block','{"maximum_ratio":1.0}'::jsonb,1,'paper-risk-single-symbol-v1'),
 ('Paper Participation v1','participation',TRUE,'block','{"maximum_ratio":0.1}'::jsonb,1,'paper-risk-participation-v1'),
 ('Paper Drawdown v1','drawdown',TRUE,'block','{"maximum_ratio":0.2}'::jsonb,1,'paper-risk-drawdown-v1'),
 ('Paper Daily Turnover v1','daily_turnover',TRUE,'block','{"maximum_ratio":2.0}'::jsonb,1,'paper-risk-turnover-v1')
ON CONFLICT(name) DO UPDATE SET rule_version=EXCLUDED.rule_version,content_hash=EXCLUDED.content_hash;

INSERT INTO alert_rules(code,rule_version,category,severity,config,content_hash)
VALUES
 ('stale_feed',1,'data','critical','{}'::jsonb,'alert-stale-feed-v1'),
 ('risk_rejection',1,'risk','warning','{}'::jsonb,'alert-risk-rejection-v1'),
 ('strategy_signal',1,'signal','info','{}'::jsonb,'alert-strategy-signal-v1'),
 ('pool_move',1,'pool','info','{}'::jsonb,'alert-pool-move-v1'),
 ('service_health',1,'system','warning','{}'::jsonb,'alert-service-health-v1')
ON CONFLICT(code,rule_version) DO NOTHING;
