"""Проверка обновления уже существующей базы.

Этот тест написан по следам поломки 05.10.2026. Новый столбец `is_bot` в
журнале посещений добавлялся миграцией, но миграция стояла **после**
создания индексов, а один из индексов строится как раз по этому столбцу.
На новой базе всё работало: столбец приходил из `SCHEMA`. На боевой базе,
где таблица уже была, создание индекса падало с «no such column: is_bot»,
приложение не запускалось, и выкат откатывался на прежнюю версию.

Стенд этого поймать не мог: там база создаётся заново при каждом запуске.
Поэтому проверка нужна отдельная - на базе, созданной по старой схеме.

Запуск из корня проекта:

    python3 -m unittest discover tests
"""

import ast
import sqlite3
import sys
import unittest
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ))

# Схему и индексы читаем из исходника, не выполняя модуль: он тянет за собой
# остальной проект, которому нужен Python новее.
_дерево = ast.parse((КОРЕНЬ / "app" / "database.py").read_text())
_блоки = {
    узел.targets[0].id: ast.literal_eval(узел.value)
    for узел in _дерево.body
    if isinstance(узел, ast.Assign)
    and getattr(узел.targets[0], "id", "") in ("SCHEMA", "INDEXES")
}

# Журнал посещений в том виде, в каком он лежит на боевой базе до обновления.
СТАРЫЙ_ЖУРНАЛ = """
CREATE TABLE visit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    created_at TEXT NOT NULL,
    path TEXT NOT NULL,
    user_agent TEXT NOT NULL DEFAULT '',
    device TEXT NOT NULL DEFAULT ''
);
"""


def столбцы(conn, таблица):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({таблица})")}


def обновить(conn):
    """Повторяет порядок действий из init_db: схема, миграции, индексы."""
    conn.executescript(_блоки["SCHEMA"])
    if "is_bot" not in столбцы(conn, "visit_log"):
        conn.execute(
            "ALTER TABLE visit_log ADD COLUMN is_bot INTEGER NOT NULL DEFAULT 0"
        )
    conn.executescript(_блоки["INDEXES"])


class ОбновлениеСуществующейБазы(unittest.TestCase):
    def test_старая_база_обновляется_без_ошибок(self):
        """Главный случай: таблица уже есть, столбца ещё нет."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЙ_ЖУРНАЛ)
        conn.execute(
            "INSERT INTO visit_log (ip, created_at, path, user_agent, device)"
            " VALUES ('1.2.3.4', '2026-10-05T10:00:00+00:00', '/', 'Firefox', 'компьютер')"
        )
        обновить(conn)
        self.assertIn("is_bot", столбцы(conn, "visit_log"))

    def test_старые_записи_остаются_людьми(self):
        """Записи, сделанные до обновления, не должны вдруг стать роботами."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЙ_ЖУРНАЛ)
        conn.execute(
            "INSERT INTO visit_log (ip, created_at, path, user_agent, device)"
            " VALUES ('1.2.3.4', '2026-10-05T10:00:00+00:00', '/', 'Firefox', 'компьютер')"
        )
        обновить(conn)
        строка = conn.execute("SELECT is_bot FROM visit_log").fetchone()
        self.assertEqual(строка[0], 0)

    def test_индекс_по_новому_столбцу_создаётся(self):
        """Та самая строчка, на которой всё падало."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЙ_ЖУРНАЛ)
        обновить(conn)
        индексы = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        self.assertIn("idx_visit_log_people", индексы)

    def test_обновление_можно_повторять(self):
        """Сайт перезапускают часто, и каждый запуск проходит этот путь."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЙ_ЖУРНАЛ)
        обновить(conn)
        обновить(conn)
        обновить(conn)
        self.assertIn("is_bot", столбцы(conn, "visit_log"))

    def test_новая_база_собирается_целиком(self):
        """Путь стенда: базы ещё нет вовсе."""
        conn = sqlite3.connect(":memory:")
        обновить(conn)
        таблицы = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        for нужная in ("providers", "reviews", "applications", "visit_log", "visit_days"):
            self.assertIn(нужная, таблицы)
        self.assertIn("is_bot", столбцы(conn, "visit_log"))

    def test_порядок_в_коде_именно_такой(self):
        """Миграция столбцов должна стоять ДО создания индексов.

        Проверяем исходник: если однажды строки переставят местами, тест
        упадёт здесь, а не на боевом сервере.
        """
        код = (КОРЕНЬ / "app" / "database.py").read_text()
        начало = код.index("def init_db()")
        тело = код[начало:]
        миграция = тело.index("migrate_visit_log_columns(conn)")
        индексы = тело.index("conn.executescript(INDEXES)")
        self.assertLess(
            миграция,
            индексы,
            "migrate_visit_log_columns должен вызываться до создания индексов",
        )


if __name__ == "__main__":
    unittest.main()
