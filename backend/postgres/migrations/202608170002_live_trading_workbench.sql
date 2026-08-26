-- A 股实盘工作台审计：预检与晋级请求全部留痕，真实委托需券商通道显式配置。

CREATE TABLE IF NOT EXISTS live_trading_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL CHECK (event_type IN ('preflight', 'enable_request')),
    candidate_kind TEXT NOT NULL CHECK (candidate_kind IN ('backtest_run', 'paper_instance')),
    candidate_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('passed', 'failed', 'deployed', 'rejected', 'blocked', 'pending_broker_binding')),
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_live_trading_events_created ON live_trading_events(created_at DESC);
