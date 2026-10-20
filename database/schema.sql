-- Schema inicial do SQLite para o Sorge V1

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calendar_event_id TEXT UNIQUE,
    title TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER,
    send_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    sent_at TEXT,
    channel TEXT NOT NULL DEFAULT 'telegram',
    FOREIGN KEY(event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    route TEXT NOT NULL,
    used_llm INTEGER NOT NULL DEFAULT 0,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL,
    intent TEXT,
    telegram_update_id INTEGER
);

CREATE TABLE IF NOT EXISTS processed_updates (
    telegram_update_id INTEGER PRIMARY KEY,
    processed_at TEXT NOT NULL
);

-- Índices para buscas rápidas de lembretes pendentes e estatísticas
CREATE INDEX IF NOT EXISTS idx_reminders_status_send ON reminders(status, send_at);
CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_events(created_at);
