import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "catalog.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    evidence_level TEXT NOT NULL DEFAULT 'limited',
    sort_order INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_type TEXT NOT NULL,
    name TEXT NOT NULL,
    specialty TEXT,
    city TEXT NOT NULL,
    district TEXT,
    address TEXT,
    phone TEXT,
    whatsapp TEXT,
    website TEXT,
    instagram TEXT,
    age_from INTEGER,
    age_to INTEGER,
    price_from INTEGER,
    price_to INTEGER,
    pricing TEXT NOT NULL DEFAULT 'paid',
    has_state_funding INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    logo_path TEXT NOT NULL DEFAULT '',
    is_test INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_methods (
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    method_id INTEGER NOT NULL REFERENCES methods(id) ON DELETE CASCADE,
    PRIMARY KEY (provider_id, method_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    author_name TEXT NOT NULL,
    rating INTEGER NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    author_ip TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reviews_provider ON reviews(provider_id, status);
CREATE INDEX IF NOT EXISTS idx_reviews_ip ON reviews(provider_id, author_ip, created_at);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Встроенный LOWER() в SQLite понижает регистр только у латиницы,
    # поэтому поиск по названиям использует питоновский str.lower.
    conn.create_function(
        "lower_ru", 1, lambda value: value.lower() if value else value, deterministic=True
    )
    return conn


@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    from .reference import (
        DEFAULT_METHODS,
        PROVIDER_TYPE_MIGRATION,
        SPECIALTY_MIGRATION,
    )

    with db_session() as conn:
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(providers)")}
        if "logo_path" not in columns:
            conn.execute(
                "ALTER TABLE providers ADD COLUMN logo_path TEXT NOT NULL DEFAULT ''"
            )

        # Справочники мест занятий и специальностей обновились — приводим
        # уже сохранённые записи к новым значениям.
        for old_code, new_code in PROVIDER_TYPE_MIGRATION.items():
            conn.execute(
                "UPDATE providers SET provider_type = ? WHERE provider_type = ?",
                (new_code, old_code),
            )
        for old_name, new_name in SPECIALTY_MIGRATION.items():
            conn.execute(
                "UPDATE providers SET specialty = ? WHERE specialty = ?",
                (new_name, old_name),
            )

        # Методы, добавленные в справочник после создания базы. Названия
        # уже существующих методов не трогаем: их могли изменить в админке.
        known = {row["code"] for row in conn.execute("SELECT code FROM methods")}
        if known:
            next_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS n FROM methods"
            ).fetchone()["n"]
            for code, name, level, description in DEFAULT_METHODS:
                if code in known:
                    continue
                next_order += 1
                conn.execute(
                    "INSERT INTO methods (code, name, description, evidence_level,"
                    " sort_order) VALUES (?, ?, ?, ?, ?)",
                    (code, name, description, level, next_order),
                )
