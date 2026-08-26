CREATE TABLE IF NOT EXISTS research_workbench_mandates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    provider_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS research_workbench_jobs (
    id TEXT PRIMARY KEY,
    mandate_id TEXT NOT NULL REFERENCES research_workbench_mandates(id),
    status TEXT NOT NULL DEFAULT 'created',
    request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    cost_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    provider_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    reason TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS research_workbench_candidates (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES research_workbench_jobs(id),
    mandate_id TEXT NOT NULL REFERENCES research_workbench_mandates(id),
    status TEXT NOT NULL DEFAULT 'draft',
    strategy_spec JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS research_workbench_paper_promotions (
    id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'requested',
    request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS research_workbench_paper_observations (
    id TEXT PRIMARY KEY,
    promotion_id TEXT,
    request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
