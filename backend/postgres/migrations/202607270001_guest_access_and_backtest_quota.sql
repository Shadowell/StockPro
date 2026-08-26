CREATE TABLE IF NOT EXISTS guest_access_codes (
    id BIGSERIAL PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    note TEXT NOT NULL DEFAULT '',
    expires_at TIMESTAMPTZ NOT NULL,
    max_backtests_per_day INTEGER NOT NULL DEFAULT 10 CHECK (max_backtests_per_day >= 0),
    max_concurrent_backtests INTEGER NOT NULL DEFAULT 1 CHECK (max_concurrent_backtests >= 1),
    max_backtest_days INTEGER NOT NULL DEFAULT 365 CHECK (max_backtest_days >= 1),
    created_by TEXT NOT NULL DEFAULT 'admin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_guest_access_codes_active
    ON guest_access_codes (expires_at DESC)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS guest_backtest_usage (
    id BIGSERIAL PRIMARY KEY,
    guest_code_id BIGINT NOT NULL REFERENCES guest_access_codes(id),
    session_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    run_id TEXT,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_guest_backtest_usage_quota
    ON guest_backtest_usage (guest_code_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_guest_backtest_usage_running
    ON guest_backtest_usage (guest_code_id, status)
    WHERE status = 'running';

CREATE TABLE IF NOT EXISTS auth_audit_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    role TEXT NOT NULL,
    subject_id TEXT,
    guest_code_id BIGINT REFERENCES guest_access_codes(id),
    success BOOLEAN NOT NULL,
    reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_audit_events_created_at
    ON auth_audit_events (created_at DESC);
