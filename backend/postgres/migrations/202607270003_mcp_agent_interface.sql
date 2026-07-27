CREATE TABLE IF NOT EXISTS mcp_agent_tokens (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,
    token_hint TEXT NOT NULL,
    scopes TEXT[] NOT NULL DEFAULT ARRAY['R']::TEXT[],
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    CHECK (scopes <@ ARRAY['R', 'W']::TEXT[])
);

CREATE TABLE IF NOT EXISTS mcp_agent_audit (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT REFERENCES mcp_agent_tokens(id) ON DELETE RESTRICT,
    tool_name TEXT,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('authorized', 'denied')),
    reason TEXT,
    idempotency_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mcp_agent_audit_token_created
    ON mcp_agent_audit (token_id, created_at DESC);

CREATE TABLE IF NOT EXISTS mcp_idempotency_records (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT NOT NULL REFERENCES mcp_agent_tokens(id) ON DELETE RESTRICT,
    tool_name TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (token_id, tool_name, idempotency_key)
);
