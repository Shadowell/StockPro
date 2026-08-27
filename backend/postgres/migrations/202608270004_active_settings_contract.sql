-- Complete the active PostgreSQL settings/token contract introduced by the
-- direct A-share port. Earlier installations already have token_hint/scopes.
ALTER TABLE mcp_agent_tokens ADD COLUMN IF NOT EXISTS token_prefix TEXT;
UPDATE mcp_agent_tokens SET token_prefix=token_hint WHERE token_prefix IS NULL;
ALTER TABLE mcp_agent_tokens ALTER COLUMN token_prefix SET NOT NULL;

ALTER TABLE mcp_agent_tokens ADD COLUMN IF NOT EXISTS tool_groups JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE mcp_agent_tokens ADD COLUMN IF NOT EXISTS rate_limit_per_min INTEGER NOT NULL DEFAULT 120;
ALTER TABLE mcp_agent_tokens ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

ALTER TABLE mcp_agent_tokens DROP CONSTRAINT IF EXISTS mcp_agent_tokens_scopes_check;
ALTER TABLE mcp_agent_tokens ADD CONSTRAINT mcp_agent_tokens_scopes_check
    CHECK (scopes <@ ARRAY['R','W','L','T']::TEXT[]);
