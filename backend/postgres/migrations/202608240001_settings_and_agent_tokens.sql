-- Settings KV + MCP agent tokens for the operations settings surface.
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mcp_agent_tokens (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    token_prefix TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    scopes JSONB NOT NULL DEFAULT '["read"]'::jsonb,
    tool_groups JSONB NOT NULL DEFAULT '[]'::jsonb,
    rate_limit_per_min INTEGER NOT NULL DEFAULT 60,
    expires_at TIMESTAMPTZ,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_mcp_agent_tokens_active
    ON mcp_agent_tokens (revoked_at) WHERE revoked_at IS NULL;
