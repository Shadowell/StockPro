-- AI 策略研发任务：多智能体闭环 (Planner/Strategist/Backtester/Evaluator) 的持久化。
-- 任务与每轮迭代全部落库，重启后可恢复未完成任务。

CREATE TABLE IF NOT EXISTS agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'stopped')),
    stage TEXT NOT NULL DEFAULT 'planner',
    stage_label TEXT NOT NULL DEFAULT '',
    user_prompt TEXT NOT NULL DEFAULT '',
    goal JSONB NOT NULL DEFAULT '{}'::jsonb,
    research_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    strategy_spec JSONB,
    max_iterations INTEGER NOT NULL DEFAULT 6,
    current_iteration INTEGER NOT NULL DEFAULT 0,
    best_iteration INTEGER,
    llm_model TEXT NOT NULL DEFAULT '',
    promoted_strategy_version_id UUID REFERENCES strategy_versions(id) ON DELETE SET NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_iterations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,
    iteration INTEGER NOT NULL,
    action TEXT NOT NULL DEFAULT 'new',
    contract JSONB,
    strategy_name TEXT NOT NULL DEFAULT '',
    strategy_version_id UUID REFERENCES strategy_versions(id) ON DELETE SET NULL,
    strategy_code TEXT NOT NULL DEFAULT '',
    reasoning TEXT NOT NULL DEFAULT '',
    sandbox_report JSONB,
    backtest_run_id UUID,
    backtest_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    eval_scores JSONB,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    meets_goal BOOLEAN NOT NULL DEFAULT FALSE,
    analysis TEXT NOT NULL DEFAULT '',
    suggestions JSONB NOT NULL DEFAULT '[]'::jsonb,
    error TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT 'refine',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (task_id, iteration)
);

CREATE INDEX IF NOT EXISTS idx_agent_iterations_task ON agent_iterations(task_id, iteration);
