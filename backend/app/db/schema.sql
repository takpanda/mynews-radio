CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source TEXT,
    url TEXT UNIQUE,
    text TEXT,
    summary TEXT,
    category TEXT,
    importance_score INTEGER,
    difficulty INTEGER,
    status TEXT NOT NULL DEFAULT 'new',
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_date TEXT NOT NULL,
    seq INTEGER DEFAULT 0,
    script_text TEXT,
    audio_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    type TEXT NOT NULL DEFAULT 'radio',
    source_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS episode_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL,
    article_id INTEGER,
    item_order INTEGER NOT NULL,
    segment_text TEXT,
    audio_generation_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE,
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_episodes_date ON episodes(episode_date);
CREATE INDEX IF NOT EXISTS idx_episodes_date_type ON episodes(episode_date, type);
CREATE INDEX IF NOT EXISTS idx_episode_items_episode_id ON episode_items(episode_id);
CREATE INDEX IF NOT EXISTS idx_episode_items_order ON episode_items(item_order);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_importance_score ON articles(importance_score);

CREATE TABLE IF NOT EXISTS dictionary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    surface TEXT NOT NULL,
    reading TEXT NOT NULL,
    category TEXT DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT '',
    source_misreading_report_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(surface, reading)
);

CREATE TABLE IF NOT EXISTS misreading_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_text TEXT NOT NULL,
    correct_reading TEXT NOT NULL,
    article_id INTEGER,
    audio_generation_id TEXT,
    playback_position REAL,
    notes TEXT DEFAULT '',
    app_version TEXT DEFAULT '',
    approved INTEGER NOT NULL DEFAULT 0,
    approved_at TEXT,
    approved_dictionary_entry_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_misreading_reports_target ON misreading_reports(target_text);
CREATE INDEX IF NOT EXISTS idx_misreading_reports_created_at ON misreading_reports(created_at);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    admin_user_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

-- Server-side quota and idempotency records for owner-triggered generation.
CREATE TABLE IF NOT EXISTS generation_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    episode_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'failed')),
    claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    FOREIGN KEY (owner_user_id) REFERENCES admin_users(id) ON DELETE CASCADE,
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE SET NULL,
    UNIQUE(owner_user_id, operation, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_generation_jobs_owner_status
    ON generation_jobs(owner_user_id, status);
CREATE INDEX IF NOT EXISTS idx_generation_jobs_claimed_at
    ON generation_jobs(claimed_at);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,
    owner_user_id INTEGER,
    executed_at TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('started', 'success', 'failure')),
    episode_id INTEGER,
    FOREIGN KEY (owner_user_id) REFERENCES admin_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_executed_at ON audit_logs(executed_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_operation ON audit_logs(operation);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id_hash TEXT NOT NULL UNIQUE,
    endpoint_hash TEXT NOT NULL UNIQUE,
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_active ON push_subscriptions(is_active);

CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    episode_id INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_type, episode_id),
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_notification_outbox_created_at ON notification_outbox(created_at);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outbox_id INTEGER NOT NULL,
    subscription_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error TEXT,
    sent_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(outbox_id, subscription_id),
    FOREIGN KEY (outbox_id) REFERENCES notification_outbox(id) ON DELETE CASCADE,
    FOREIGN KEY (subscription_id) REFERENCES push_subscriptions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_notification_deliveries_ready
    ON notification_deliveries(status, next_attempt_at);

-- MVP settings are local, single-user state.  Keep one row and store the
-- validated category selections as JSON so the schema can evolve later.
CREATE TABLE IF NOT EXISTS user_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    priority_themes TEXT NOT NULL DEFAULT '[]',
    excluded_themes TEXT NOT NULL DEFAULT '[]',
    duration_preset TEXT NOT NULL DEFAULT 'normal',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
