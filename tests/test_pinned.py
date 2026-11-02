"""Закрепление карточки первой в выдаче по своему городу.

Проверяется две вещи.

1. На уже существующей базе столбец `is_pinned` добавляется миграцией и по
   умолчанию равен нулю, то есть порядок выдачи у старой базы не меняется.
   Стенд такое не ловит: база там создаётся заново при каждом запуске.
2. Сортировка действительно ставит закреплённую карточку первой, даже если
   у неё оценка ниже. Запрос берётся из `app/crud.py`, а не пишется заново:
   иначе тест проверял бы сам себя.

Запуск из корня проекта:

    python3 -m unittest discover tests
"""

import ast
import re
import sqlite3
import sys
import unittest
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ))

# Модули проекта не импортируем: им нужен Python новее, чем стоит у владельца.
# Берём из исходников только нужные строки.
_исходник_базы = (КОРЕНЬ / "app" / "database.py").read_text()
_исходник_crud = (КОРЕНЬ / "app" / "crud.py").read_text()

_блоки = {
    узел.targets[0].id: ast.literal_eval(узел.value)
    for узел in ast.parse(_исходник_базы).body
    if isinstance(узел, ast.Assign)
    and getattr(узел.targets[0], "id", "") in ("SCHEMA", "INDEXES")
}
RATING_COLUMNS = {
    узел.targets[0].id: ast.literal_eval(узел.value)
    for узел in ast.parse(_исходник_crud).body
    if isinstance(узел, ast.Assign)
    and getattr(узел.targets[0], "id", "") == "RATING_COLUMNS"
}["RATING_COLUMNS"]

# Строка сортировки для случая «город выбран» - ровно та, что уходит в базу.
_сортировки = re.findall(r'"(ORDER BY [^"]+)"', _исходник_crud)
СОРТИРОВКА_С_ГОРОДОМ = next(s for s in _сортировки if "is_pinned" in s)

# Места занятий в том виде, в каком таблица лежит на боевой базе до обновления:
# без столбца закрепления.
СТАРАЯ_ТАБЛИЦА = """
CREATE TABLE providers (
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
    lat REAL,
    lng REAL,
    created_at TEXT NOT NULL
);
"""


def столбцы(conn, таблица):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({таблица})")}


def обновить(conn):
    """Повторяет порядок действий из init_db: схема, миграции, индексы."""
    conn.executescript(_блоки["SCHEMA"])
    if "is_pinned" not in столбцы(conn, "providers"):
        conn.execute(
            "ALTER TABLE providers ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0"
        )
    conn.executescript(_блоки["INDEXES"])


def добавить(conn, название, оценка=None, закреплено=0):
    conn.execute(
        "INSERT INTO providers (provider_type, name, city, pricing, is_pinned,"
        " created_at) VALUES ('center', ?, 'Алматы', 'paid', ?, '2026-11-02')",
        (название, закреплено),
    )
    pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if оценка is not None:
        conn.execute(
            "INSERT INTO reviews (provider_id, author_name, rating, text, status,"
            " created_at) VALUES (?, 'Родитель', ?, 'отзыв', 'published', '2026-11-02')",
            (pid, оценка),
        )
    return pid


def выдача(conn, город="Алматы"):
    sql = (
        f"SELECT p.name, {RATING_COLUMNS} FROM providers p"
        f" WHERE p.city = ? {СОРТИРОВКА_С_ГОРОДОМ}"
    )
    return [row[0] for row in conn.execute(sql, (город,))]


class СтараяБазаОбновляется(unittest.TestCase):
    def test_столбец_добавляется_к_существующей_таблице(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРАЯ_ТАБЛИЦА)
        conn.execute(
            "INSERT INTO providers (provider_type, name, city, pricing, created_at)"
            " VALUES ('center', 'Старая запись', 'Алматы', 'paid', '2026-10-01')"
        )
        обновить(conn)
        self.assertIn("is_pinned", столбцы(conn, "providers"))

    def test_у_старых_записей_закрепления_нет(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРАЯ_ТАБЛИЦА)
        conn.execute(
            "INSERT INTO providers (provider_type, name, city, pricing, created_at)"
            " VALUES ('center', 'Старая запись', 'Алматы', 'paid', '2026-10-01')"
        )
        обновить(conn)
        значение = conn.execute("SELECT is_pinned FROM providers").fetchone()[0]
        self.assertEqual(значение, 0)


class ПорядокВыдачи(unittest.TestCase):
    def подготовить(self):
        conn = sqlite3.connect(":memory:")
        обновить(conn)
        return conn

    def test_закреплённая_идёт_первой_даже_с_низкой_оценкой(self):
        conn = self.подготовить()
        добавить(conn, "Отличный центр", оценка=5)
        добавить(conn, "Хороший центр", оценка=4)
        добавить(conn, "Qabilet", оценка=3, закреплено=1)
        self.assertEqual(выдача(conn)[0], "Qabilet")

    def test_без_закрепления_порядок_прежний(self):
        conn = self.подготовить()
        добавить(conn, "Отличный центр", оценка=5)
        добавить(conn, "Хороший центр", оценка=4)
        добавить(conn, "Qabilet", оценка=3)
        self.assertEqual(выдача(conn)[0], "Отличный центр")

    def test_остальные_сохраняют_порядок_по_оценке(self):
        conn = self.подготовить()
        добавить(conn, "Отличный центр", оценка=5)
        добавить(conn, "Хороший центр", оценка=4)
        добавить(conn, "Без отзывов")
        добавить(conn, "Qabilet", оценка=3, закреплено=1)
        self.assertEqual(
            выдача(conn),
            ["Qabilet", "Отличный центр", "Хороший центр", "Без отзывов"],
        )

    def test_закрепление_не_действует_в_чужом_городе(self):
        conn = self.подготовить()
        добавить(conn, "Qabilet", оценка=3, закреплено=1)
        conn.execute(
            "INSERT INTO providers (provider_type, name, city, pricing, is_pinned,"
            " created_at) VALUES ('center', 'Астанинский центр', 'Астана', 'paid',"
            " 0, '2026-11-02')"
        )
        self.assertEqual(выдача(conn, "Астана"), ["Астанинский центр"])


if __name__ == "__main__":
    unittest.main()
