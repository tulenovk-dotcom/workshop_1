import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# На хостинге база лежит на подключённом диске, локально - рядом с проектом.
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "catalog.db"
DB_PATH = Path(os.environ.get("DB_PATH") or DEFAULT_DB_PATH)


def read_or_create_secret(name: str) -> str:
    """Длинная случайная строка, которая переживает перезапуск процесса.

    Файл лежит рядом с базой: там же, где данные, которые он защищает.
    Если переменная окружения задана, этот файл не нужен - вызывающий код
    смотрит переменную первым.
    """
    path = DB_PATH.parent / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()

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
    author_ip_hash TEXT,
    anonymized_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    applicant_kind TEXT NOT NULL,
    name TEXT NOT NULL,
    provider_type TEXT NOT NULL DEFAULT '',
    specialty TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    method_codes TEXT NOT NULL DEFAULT '[]',
    age_from INTEGER,
    age_to INTEGER,
    price_from INTEGER,
    price_to INTEGER,
    pricing TEXT NOT NULL DEFAULT 'paid',
    link TEXT NOT NULL DEFAULT '',
    contact_person TEXT NOT NULL,
    phone TEXT NOT NULL,
    whatsapp TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    logo_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    admin_note TEXT NOT NULL DEFAULT '',
    provider_id INTEGER REFERENCES providers(id) ON DELETE SET NULL,
    consent_at TEXT NOT NULL,
    author_ip_hash TEXT,
    anonymized_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    consent_text TEXT NOT NULL,
    given_at TEXT NOT NULL,
    ip_hash TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS data_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    admin_note TEXT NOT NULL DEFAULT '',
    author_ip_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Индексы создаются после миграций: на старой базе колонка с хешем адреса
# появляется только там, а индекс по несуществующей колонке не создать.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_reviews_provider ON reviews(provider_id, status);
CREATE INDEX IF NOT EXISTS idx_reviews_ip ON reviews(provider_id, author_ip_hash, created_at);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status, created_at);
CREATE INDEX IF NOT EXISTS idx_applications_ip ON applications(author_ip_hash, created_at);
CREATE INDEX IF NOT EXISTS idx_consents_record ON consents(subject_type, record_id);
CREATE INDEX IF NOT EXISTS idx_data_actions_record ON data_actions(subject_type, record_id);
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status, created_at);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate_ip_columns(conn: sqlite3.Connection) -> None:
    """Открытые адреса в старых базах заменяются хешами - один раз.

    Колонка переименовывается, чтобы по имени было видно, что в ней лежит:
    author_ip хранил сам адрес, author_ip_hash хранит только его отпечаток.
    """
    from .personal_data import hash_ip, looks_like_hash

    for table in ("reviews", "applications"):
        columns = table_columns(conn, table)
        if "author_ip" in columns and "author_ip_hash" not in columns:
            conn.execute(
                f"ALTER TABLE {table} RENAME COLUMN author_ip TO author_ip_hash"
            )
        if "anonymized_at" not in table_columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN anonymized_at TEXT")

        rows = conn.execute(
            f"SELECT id, author_ip_hash FROM {table}"
            " WHERE author_ip_hash IS NOT NULL AND author_ip_hash <> ''"
        ).fetchall()
        for row in rows:
            if looks_like_hash(row["author_ip_hash"]):
                continue
            conn.execute(
                f"UPDATE {table} SET author_ip_hash = ? WHERE id = ?",
                (hash_ip(row["author_ip_hash"]), row["id"]),
            )


def init_db() -> None:
    from .reference import (
        DEFAULT_METHODS,
        PROVIDER_TYPE_MIGRATION,
        SPECIALTY_MIGRATION,
    )

    with db_session() as conn:
        conn.executescript(SCHEMA)
        migrate_ip_columns(conn)
        conn.executescript(INDEXES)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(providers)")}
        if "logo_path" not in columns:
            conn.execute(
                "ALTER TABLE providers ADD COLUMN logo_path TEXT NOT NULL DEFAULT ''"
            )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(applications)")}
        if "logo_path" not in columns:
            conn.execute(
                "ALTER TABLE applications ADD COLUMN logo_path TEXT NOT NULL DEFAULT ''"
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

        # Тексты сайта набираются с обычным дефисом. В справочнике методов
        # остались длинные тире от прежних версий - заменяем только сам
        # знак, остальное содержимое не трогаем. Отзывы и заявки не правим:
        # это чужой текст, а не наш.
        conn.execute(
            "UPDATE methods SET name = REPLACE(name, char(8212), '-'),"
            " description = REPLACE(description, char(8212), '-')"
            " WHERE name LIKE '%' || char(8212) || '%'"
            " OR description LIKE '%' || char(8212) || '%'"
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
