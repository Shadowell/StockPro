CREATE TABLE IF NOT EXISTS app_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    display_name TEXT NOT NULL DEFAULT 'StockPro User',
    role TEXT NOT NULL DEFAULT 'owner' CHECK (role IN ('owner', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS strategy_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legacy_strategy_id INTEGER,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    script_content TEXT NOT NULL,
    parameter_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    data_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    output_contract JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS strategy_parameters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_version_id UUID NOT NULL REFERENCES strategy_versions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    value JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (strategy_version_id, name)
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_version_id UUID REFERENCES strategy_versions(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    universe JSONB NOT NULL DEFAULT '{}'::jsonb,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'success', 'failed', 'cancelled')),
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy ON backtest_runs(strategy_version_id);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created_at ON backtest_runs(created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    trade_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    price NUMERIC(18, 4) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    amount NUMERIC(20, 4) NOT NULL,
    commission NUMERIC(18, 4) NOT NULL DEFAULT 0,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades(backtest_run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_symbol_date ON backtest_trades(symbol, trade_date);

CREATE TABLE IF NOT EXISTS strategy_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_version_id UUID REFERENCES strategy_versions(id) ON DELETE SET NULL,
    legacy_strategy_id INTEGER,
    symbol TEXT NOT NULL,
    name TEXT,
    signal_type TEXT NOT NULL DEFAULT 'candidate' CHECK (signal_type IN ('candidate', 'buy', 'sell', 'watch')),
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'confirmed', 'invalidated', 'ordered', 'closed')),
    signal_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    price NUMERIC(18, 4),
    strength NUMERIC(10, 4),
    reason TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_signals_status_time ON strategy_signals(status, signal_time DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_signals_symbol_time ON strategy_signals(symbol, signal_time DESC);

CREATE TABLE IF NOT EXISTS portfolios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL DEFAULT 'paper' CHECK (mode IN ('paper', 'dry_run', 'live')),
    base_currency TEXT NOT NULL DEFAULT 'CNY',
    initial_cash NUMERIC(20, 4) NOT NULL DEFAULT 1000000,
    cash_balance NUMERIC(20, 4) NOT NULL DEFAULT 1000000,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    name TEXT,
    quantity INTEGER NOT NULL DEFAULT 0,
    available_quantity INTEGER NOT NULL DEFAULT 0,
    avg_cost NUMERIC(18, 4) NOT NULL DEFAULT 0,
    last_price NUMERIC(18, 4),
    market_value NUMERIC(20, 4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (portfolio_id, symbol)
);

CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    signal_id UUID REFERENCES strategy_signals(id) ON DELETE SET NULL,
    broker_order_id TEXT,
    symbol TEXT NOT NULL,
    name TEXT,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type TEXT NOT NULL DEFAULT 'limit' CHECK (order_type IN ('limit', 'market')),
    price NUMERIC(18, 4),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    filled_quantity INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'submitted', 'partial', 'filled', 'cancelled', 'rejected')),
    message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_portfolio_status ON orders(portfolio_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_symbol_created ON orders(symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    broker_trade_id TEXT,
    symbol TEXT NOT NULL,
    name TEXT,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    price NUMERIC(18, 4) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    amount NUMERIC(20, 4) NOT NULL,
    commission NUMERIC(18, 4) NOT NULL DEFAULT 0,
    traded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_portfolio_time ON trades(portfolio_id, traded_at DESC);

CREATE TABLE IF NOT EXISTS cash_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('deposit', 'withdrawal', 'buy', 'sell', 'commission', 'freeze', 'unfreeze', 'adjustment')),
    amount NUMERIC(20, 4) NOT NULL,
    balance_after NUMERIC(20, 4) NOT NULL,
    ref_type TEXT,
    ref_id UUID,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cash_ledger_portfolio_time ON cash_ledger(portfolio_id, created_at DESC);

CREATE TABLE IF NOT EXISTS risk_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    rule_type TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    severity TEXT NOT NULL DEFAULT 'block' CHECK (severity IN ('warn', 'block')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS risk_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID REFERENCES portfolios(id) ON DELETE SET NULL,
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    signal_id UUID REFERENCES strategy_signals(id) ON DELETE SET NULL,
    rule_id UUID REFERENCES risk_rules(id) ON DELETE SET NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warn', 'block')),
    message TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_events_created_at ON risk_events(created_at DESC);

CREATE TABLE IF NOT EXISTS broker_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    adapter_type TEXT NOT NULL CHECK (adapter_type IN ('mock', 'dry_run', 'live')),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_status TEXT,
    last_checked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO portfolios (name, mode, initial_cash, cash_balance)
VALUES ('默认模拟组合', 'paper', 1000000, 1000000)
ON CONFLICT (name) DO NOTHING;

INSERT INTO risk_rules (name, rule_type, severity, config)
VALUES
    ('单票仓位上限', 'max_symbol_weight', 'block', '{"max_weight": 0.2}'::jsonb),
    ('订单数量必须为100股整数倍', 'a_share_lot_size', 'block', '{"lot_size": 100}'::jsonb),
    ('默认禁用实盘下单', 'live_trading_disabled', 'block', '{"allow_live": false}'::jsonb)
ON CONFLICT (name) DO NOTHING;

INSERT INTO broker_connections (name, adapter_type, enabled, config)
VALUES ('Mock Broker', 'mock', true, '{}'::jsonb), ('Dry Run Broker', 'dry_run', false, '{}'::jsonb)
ON CONFLICT (name) DO NOTHING;
