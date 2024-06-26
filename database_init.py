import sqlite3

# Connect to the SQLite database
conn = sqlite3.connect('trading_algo.db')
c = conn.cursor()

# Create table for tradeable assets
c.execute('''CREATE TABLE IF NOT EXISTS tradeable_assets (
    token_address TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    platform TEXT NOT NULL,
    creation_unixtime INTEGER NOT NULL,
)''')

# Create table for tradeable asset info
c.execute('''CREATE TABLE IF NOT EXISTS tradeable_asset_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unixtime INTEGER NOT NULL,
    token_address TEXT NOT NULL,
    top_10_holders_pct REAL,
    volume REAL,
    volume_change_pct REAL,
    market_cap REAL,
    liquidity REAL,
    volume_pct_market_cap REAL,
    FOREIGN KEY (token_address) REFERENCES tradeable_assets (token_address)
    ON DELETE CASCADE
)''')

# Composite index for tradeable_asset_info
c.execute('''CREATE INDEX IF NOT EXISTS idx_tradeable_asset_info_unixtime_token ON tradeable_asset_info(unixtime, token_address);''')

# Create table for tradeable asset prices
c.execute('''CREATE TABLE IF NOT EXISTS tradeable_asset_prices(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address TEXT NOT NULL,
    unixtime INTEGER NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    interval TEXT,
    FOREIGN KEY (token_address) REFERENCES tradeable_assets (token_address)
    ON DELETE CASCADE
)''')

# Composite index for tradeable_asset_prices
c.execute('''CREATE INDEX IF NOT EXISTS idx_tradeable_asset_prices_unixtime_token ON tradeable_asset_prices(unixtime, token_address);''')

# Create table for tradeable asset indicators
c.execute('''CREATE TABLE IF NOT EXISTS tradeable_asset_indicators(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address TEXT NOT NULL,
    unixtime INTEGER NOT NULL,
    interval TEXT,
    FOREIGN KEY (token_address) REFERENCES tradeable_assets (token_address)
    ON DELETE CASCADE
)''')

# Composite index for tradeable_asset_indicators
c.execute('''CREATE INDEX IF NOT EXISTS idx_tradeable_asset_indicators_unixtime_token ON tradeable_asset_indicators(unixtime, token_address);''')

# Create table for algorithmic trades
c.execute('''CREATE TABLE IF NOT EXISTS algorithmic_trades (
    transactionID TEXT PRIMARY KEY,
    unixtime INTEGER NOT NULL,
    token_address TEXT NOT NULL,
    strategyID TEXT NOT NULL,
    buy_sell TEXT NOT NULL,
    price REAL,
    fees REAL,
    FOREIGN KEY (token_address) REFERENCES tradeable_assets (token_address)
    ON DELETE CASCADE
)''')

# Create table for portfolio composition by strategy
c.execute('''CREATE TABLE IF NOT EXISTS portfolio_composition_by_strategy (
          id INTEGER PRIMARY KEY AUTOINCREMENT
          token_address TEXT NOT NULL
          strategyID TEXT NOT NULL
          token_balance REAL 
          FOREIGN KEY (token_address) REFERENCES tradeable_assets (token_address)
          ON DELETE CASCADE
)
''')

# Create table for portfolio balances
c.execute('''CREATE TABLE IF NOT EXISTS portfolio_balances (
    datetime DATETIME NOT NULL,
    wallet_address TEXT NOT NULL,
    usdc_balance REAL,
    solana_balance REAL,
    solana_balance_usd REAL,
    amt_spl_tokens INTEGER,
    spl_token_balance_usd REAL,
    total_portfolio_balance_usd REAL
)''')

# Commit the changes and close the connection
conn.commit()
conn.close()

print("Database initialized successfully with indexes for optimized reading operations.")
