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
    enabled INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(surface, reading)
);
