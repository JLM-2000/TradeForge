-- TradeForge development schema. Production uses PostgreSQL migrations with
-- NUMERIC columns and equivalent append-only protections.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    account_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    origin TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE
);

CREATE TRIGGER IF NOT EXISTS ledger_events_no_update
BEFORE UPDATE ON ledger_events
BEGIN
    SELECT RAISE(ABORT, 'ledger_events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS ledger_events_no_delete
BEFORE DELETE ON ledger_events
BEGIN
    SELECT RAISE(ABORT, 'ledger_events are append-only');
END;

CREATE TABLE IF NOT EXISTS control_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    state TEXT NOT NULL,
    reason TEXT NOT NULL,
    activated_at TEXT,
    cancel_pending_on_pause INTEGER NOT NULL CHECK (cancel_pending_on_pause IN (0, 1))
);

INSERT OR IGNORE INTO control_state(singleton_id, state, reason, activated_at, cancel_pending_on_pause)
VALUES (1, 'RUNNING', '', NULL, 1);

CREATE TABLE IF NOT EXISTS owner_hard_limits (
    version TEXT PRIMARY KEY,
    max_total_capital_eur NUMERIC NOT NULL,
    max_position_eur NUMERIC NOT NULL,
    max_total_exposure_eur NUMERIC NOT NULL,
    max_open_positions INTEGER NOT NULL,
    max_daily_loss_eur NUMERIC NOT NULL,
    max_daily_profit_eur NUMERIC,
    max_weekly_loss_eur NUMERIC NOT NULL,
    max_weekly_profit_eur NUMERIC,
    max_monthly_loss_eur NUMERIC NOT NULL,
    max_monthly_profit_eur NUMERIC,
    max_drawdown_percent NUMERIC NOT NULL,
    max_orders_per_day INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS instruments (
    instrument_id TEXT PRIMARY KEY,
    isin TEXT NOT NULL,
    ticker TEXT NOT NULL,
    venue TEXT NOT NULL,
    currency TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    tradable INTEGER NOT NULL CHECK (tradable IN (0, 1)),
    quantity_increment NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS quotes (
    instrument_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    bid NUMERIC NOT NULL,
    ask NUMERIC NOT NULL,
    source TEXT NOT NULL,
    sequence INTEGER,
    PRIMARY KEY (instrument_id, timestamp)
);

CREATE TABLE IF NOT EXISTS trade_intents (
    intent_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    broker_order_id TEXT,
    intent_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    state TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    broker_order_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    executed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cash_movements (
    movement_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    movement_type TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    origin TEXT NOT NULL,
    broker_reference TEXT
);

CREATE TABLE IF NOT EXISTS tax_lots (
    lot_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    homogeneous_key TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    quantity NUMERIC NOT NULL,
    remaining_quantity NUMERIC NOT NULL,
    acquisition_price_eur NUMERIC NOT NULL,
    acquisition_at TEXT NOT NULL,
    fees_eur NUMERIC NOT NULL,
    source_event_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    previous_value TEXT,
    new_value TEXT,
    reason TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_reports (
    report_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    status TEXT NOT NULL,
    differences_json TEXT NOT NULL,
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS demo_runtime_state (
    state_key TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
