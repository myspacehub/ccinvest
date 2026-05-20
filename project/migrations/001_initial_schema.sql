-- =====================================================
-- CC Invest 数据库架构
-- 支持 SQLite (开发环境) 和 PostgreSQL (生产环境)
-- =====================================================

-- =====================================================
-- 用户表
-- =====================================================
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    api_key TEXT,
    api_secret TEXT,
    trading_mode TEXT DEFAULT 'paper',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 市场数据表
-- =====================================================
CREATE TABLE IF NOT EXISTS market_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price DECIMAL(18, 8) NOT NULL,
    volume_24h DECIMAL(18, 8),
    change_24h DECIMAL(10, 4),
    high_24h DECIMAL(18, 8),
    low_24h DECIMAL(18, 8),
    timestamp TIMESTAMP NOT NULL,
    source TEXT DEFAULT 'binance',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- K线数据表
-- =====================================================
CREATE TABLE IF NOT EXISTS ohlc_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open_price DECIMAL(18, 8) NOT NULL,
    high_price DECIMAL(18, 8) NOT NULL,
    low_price DECIMAL(18, 8) NOT NULL,
    close_price DECIMAL(18, 8) NOT NULL,
    volume DECIMAL(18, 8) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 链上数据表
-- =====================================================
CREATE TABLE IF NOT EXISTS chain_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    chain TEXT NOT NULL,
    tx_hash TEXT,
    from_address TEXT,
    to_address TEXT,
    value DECIMAL(18, 8),
    gas_used INTEGER,
    event_type TEXT,
    block_number INTEGER,
    timestamp TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 社交情绪表
-- =====================================================
CREATE TABLE IF NOT EXISTS sentiment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    keyword TEXT,
    sentiment_score REAL DEFAULT 0,
    polarity TEXT,
    post_count INTEGER DEFAULT 0,
    engagement_score REAL DEFAULT 0,
    timestamp TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 模拟账户表
-- =====================================================
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    balance DECIMAL(18, 8) NOT NULL,
    initial_balance DECIMAL(18, 8) NOT NULL,
    total_pnl DECIMAL(18, 8) DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    max_drawdown DECIMAL(10, 6) DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- =====================================================
-- 持仓表
-- =====================================================
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity DECIMAL(18, 8) NOT NULL,
    entry_price DECIMAL(18, 8) NOT NULL,
    current_price DECIMAL(18, 8),
    unrealized_pnl DECIMAL(18, 8) DEFAULT 0,
    status TEXT DEFAULT 'open',
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

-- =====================================================
-- 订单表
-- =====================================================
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity DECIMAL(18, 8) NOT NULL,
    price DECIMAL(18, 8),
    filled_quantity DECIMAL(18, 8) DEFAULT 0,
    avg_fill_price DECIMAL(18, 8),
    status TEXT DEFAULT 'pending',
    order_id TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

-- =====================================================
-- 交易记录表
-- =====================================================
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    order_id INTEGER,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity DECIMAL(18, 8) NOT NULL,
    price DECIMAL(18, 8) NOT NULL,
    commission DECIMAL(18, 8) DEFAULT 0,
    pnl DECIMAL(18, 8),
    strategy TEXT,
    signal_type TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

-- =====================================================
-- 策略信号表
-- =====================================================
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    strength REAL DEFAULT 0.5,
    price DECIMAL(18, 8),
    indicators TEXT,
    reasoning TEXT,
    confidence REAL DEFAULT 0.5,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 风控日志表
-- =====================================================
CREATE TABLE IF NOT EXISTS risk_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    severity TEXT DEFAULT 'warning',
    message TEXT,
    details TEXT,
    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 系统审计日志表
-- =====================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    table_name TEXT,
    record_id INTEGER,
    old_value TEXT,
    new_value TEXT,
    ip_address TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- =====================================================
-- 回测结果表
-- =====================================================
CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital DECIMAL(18, 8) NOT NULL,
    final_capital DECIMAL(18, 8) NOT NULL,
    total_return DECIMAL(10, 4),
    sharpe_ratio REAL,
    max_drawdown DECIMAL(10, 4),
    win_rate DECIMAL(10, 4),
    total_trades INTEGER,
    parameters TEXT,
    equity_curve TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- OpenClaw 长期记忆表 (向量嵌入)
-- 注意：pgvector 仅在 PostgreSQL 环境下可用
-- =====================================================
CREATE TABLE IF NOT EXISTS openclaw_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    content TEXT NOT NULL,
    embedding TEXT,
    memory_type TEXT DEFAULT 'conversation',
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 技能版本管理表
-- =====================================================
CREATE TABLE IF NOT EXISTS skill_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    version TEXT NOT NULL,
    content TEXT,
    changelog TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 索引优化
-- =====================================================
CREATE INDEX IF NOT EXISTS idx_market_data_symbol_time 
ON market_data(symbol, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_ohlc_symbol_time 
ON ohlc_data(symbol, timeframe, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_positions_account 
ON positions(account_id, status);

CREATE INDEX IF NOT EXISTS idx_orders_account_status 
ON orders(account_id, status);

CREATE INDEX IF NOT EXISTS idx_trades_account_time 
ON trades(account_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_strategy 
ON signals(symbol, strategy, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_risk_logs_event_time 
ON risk_logs(event_type, triggered_at DESC);

-- =====================================================
-- 注意：SQLite 不支持 CREATE EXTENSION 和 PostgreSQL 触发器
-- 如需使用向量数据库功能，请使用 PostgreSQL + pgvector
-- =====================================================