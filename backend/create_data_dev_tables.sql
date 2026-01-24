-- 创建数据开发任务表
CREATE TABLE IF NOT EXISTS data_dev_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    sql_content TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    enabled BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 创建数据开发任务执行日志表
CREATE TABLE IF NOT EXISTS data_dev_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    execution_start DATETIME DEFAULT CURRENT_TIMESTAMP,
    execution_end DATETIME,
    status TEXT CHECK(status IN ('success', 'failed', 'running')),
    error_message TEXT,
    affected_rows INTEGER,
    FOREIGN KEY (task_id) REFERENCES data_dev_tasks(id)
);

-- 创建M5/M10/M20/M30移动平均线计算结果表
CREATE TABLE IF NOT EXISTS stock_ma_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    date DATE NOT NULL,
    ma5 REAL,
    ma10 REAL,
    ma20 REAL,
    ma30 REAL,
    price REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code, date)
);

-- 为股票代码和日期创建索引以提高查询性能
CREATE INDEX IF NOT EXISTS idx_stock_ma_indicators_code_date ON stock_ma_indicators(code, date);
CREATE INDEX IF NOT EXISTS idx_stock_ma_indicators_date ON stock_ma_indicators(date);