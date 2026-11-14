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


# Обращения по персональным данным в том виде, в каком они лежат на боевой
# базе до появления выбора «что нужно сделать».
СТАРЫЕ_ОБРАЩЕНИЯ = """
CREATE TABLE requests (
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


# Заявки на размещение в том виде, в каком они лежат на боевой базе до
# появления отметки «заявку заполнил администратор».
СТАРЫЕ_ЗАЯВКИ = """
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    applicant_kind TEXT NOT NULL,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    contact_person TEXT NOT NULL,
    phone TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    admin_note TEXT NOT NULL DEFAULT '',
    provider_id INTEGER,
    consent_at TEXT NOT NULL,
    author_ip_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


# Места занятий в том виде, в каком они лежат на боевой базе до появления
# отметки «предупредил о продлении». Только нужные тесту столбцы.
СТАРЫЕ_МЕСТА = """
CREATE TABLE providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_type TEXT NOT NULL,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    promo_until TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
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
    if "kind" not in столбцы(conn, "requests"):
        conn.execute("ALTER TABLE requests ADD COLUMN kind TEXT NOT NULL DEFAULT ''")
    if "by_admin" not in столбцы(conn, "applications"):
        conn.execute(
            "ALTER TABLE applications ADD COLUMN by_admin INTEGER NOT NULL DEFAULT 0"
        )
    for имя in ("promo_notified_for", "promo_notified_at"):
        if имя not in столбцы(conn, "providers"):
            conn.execute(
                f"ALTER TABLE providers ADD COLUMN {имя} TEXT NOT NULL DEFAULT ''"
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

    def test_старым_заявкам_добавляется_отметка(self):
        """Столбца `by_admin` на боевой базе ещё нет: таблица создана
        раньше, а `CREATE TABLE IF NOT EXISTS` её не меняет."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЕ_ЗАЯВКИ)
        conn.execute(
            "INSERT INTO applications (applicant_kind, name, city,"
            " contact_person, phone, consent_at, created_at, updated_at)"
            " VALUES ('organization', 'Центр', 'Астана', 'Айгуль',"
            " '+77000000000', '2026-11-01T06:00:00+00:00',"
            " '2026-11-01T06:00:00+00:00', '2026-11-01T06:00:00+00:00')"
        )
        обновить(conn)
        self.assertIn("by_admin", столбцы(conn, "applications"))

    def test_старые_заявки_считаются_пришедшими_со_стороны(self):
        """Гадать задним числом, кто заполнил заявку, нельзя: отметку
        ставит администратор руками по отпечатку адреса."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЕ_ЗАЯВКИ)
        conn.execute(
            "INSERT INTO applications (applicant_kind, name, city,"
            " contact_person, phone, consent_at, created_at, updated_at)"
            " VALUES ('specialist', 'Логопед', 'Алматы', 'Асем',"
            " '+77000000001', '2026-11-01T06:00:00+00:00',"
            " '2026-11-01T06:00:00+00:00', '2026-11-01T06:00:00+00:00')"
        )
        обновить(conn)
        строка = conn.execute("SELECT by_admin FROM applications").fetchone()
        self.assertEqual(строка[0], 0)

    def test_обновление_можно_повторять(self):
        """Сайт перезапускают часто, и каждый запуск проходит этот путь."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЙ_ЖУРНАЛ)
        обновить(conn)
        обновить(conn)
        обновить(conn)
        self.assertIn("is_bot", столбцы(conn, "visit_log"))

    def test_таблица_переходов_появляется_на_старой_базе(self):
        """Счётчик переходов добавлен позже остальных таблиц.

        На боевой базе таблицы contact_clicks нет, а индексы по ней есть в
        INDEXES. Порядок в init_db такой, что таблица создаётся раньше: если
        его однажды сломают, упадёт здесь, а не при выкате.
        """
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЙ_ЖУРНАЛ)
        обновить(conn)
        имена = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE '%click%'"
            )
        }
        self.assertIn("contact_clicks", имена)
        self.assertIn("idx_clicks_provider", имена)
        self.assertIn("idx_clicks_time", имена)

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
        for нужная in ("providers", "reviews", "applications", "visit_log",
                       "visit_days", "contact_clicks"):
            self.assertIn(нужная, таблицы)
        self.assertIn("is_bot", столбцы(conn, "visit_log"))

    def test_выбор_просьбы_появляется_у_старых_обращений(self):
        """Столбец «что нужно сделать» добавлен позже самой таблицы.

        На боевой базе обращения уже есть, и у них этого столбца нет.
        Обновление должно его добавить, а присланный человеком текст -
        оставить на месте: по нему и видно, чего он просил.
        """
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЕ_ОБРАЩЕНИЯ)
        conn.execute(
            "INSERT INTO requests (name, contact, message, created_at, updated_at)"
            " VALUES ('Асель', 'asel@mail.kz', 'Удалите мой отзыв',"
            " '2026-10-20T10:00:00+00:00', '2026-10-20T10:00:00+00:00')"
        )
        обновить(conn)
        self.assertIn("kind", столбцы(conn, "requests"))
        строка = conn.execute("SELECT kind, message FROM requests").fetchone()
        self.assertEqual(строка[0], "")
        self.assertEqual(строка[1], "Удалите мой отзыв")

    def test_обновление_обращений_можно_повторять(self):
        """Второй запуск не должен спотыкаться об уже добавленный столбец."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЕ_ОБРАЩЕНИЯ)
        обновить(conn)
        обновить(conn)
        self.assertIn("kind", столбцы(conn, "requests"))

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
        self.assertLess(
            тело.index("migrate_request_columns(conn)"),
            индексы,
            "migrate_request_columns должен вызываться до создания индексов",
        )



class ОплатыПродвиженияНаСтаройБазе(unittest.TestCase):
    """Журнал оплат и отметка о напоминании появились 14.11.2026.

    На боевой базе таблицы promo_payments нет, а у providers нет столбцов
    отметки. Проверяем, что обновление проходит и не трогает уже
    поставленный срок продвижения.
    """

    def старая_база(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(СТАРЫЕ_МЕСТА)
        conn.execute(
            "INSERT INTO providers (provider_type, name, city, promo_until, created_at)"
            " VALUES ('center', 'Сенім', 'Астана', '2026-12-14',"
            " '2026-11-14T06:00:00+00:00')"
        )
        обновить(conn)
        return conn

    def test_столбцы_отметки_появляются(self):
        conn = self.старая_база()
        self.assertIn("promo_notified_for", столбцы(conn, "providers"))
        self.assertIn("promo_notified_at", столбцы(conn, "providers"))

    def test_срок_продвижения_не_тронут(self):
        conn = self.старая_база()
        строка = conn.execute(
            "SELECT promo_until, promo_notified_for FROM providers"
        ).fetchone()
        self.assertEqual(строка, ("2026-12-14", ""))

    def test_таблица_и_индексы_оплат_создаются(self):
        conn = self.старая_база()
        имена = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE '%promo_payments%'"
            )
        }
        self.assertIn("promo_payments", имена)
        self.assertIn("idx_promo_payments_provider", имена)
        self.assertIn("idx_promo_payments_day", имена)

    def test_удаление_карточки_не_стирает_оплату(self):
        """Деньги получены - запись о них остаётся, даже если карточки нет."""
        conn = self.старая_база()
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO promo_payments (provider_id, provider_name, plan, months,"
            " amount, paid_on, period_from, period_until, created_at)"
            " VALUES (1, 'Сенім', '1m', 1, 1999, '2026-11-14', '2026-11-14',"
            " '2026-12-14', '2026-11-14T06:00:00+00:00')"
        )
        conn.execute("DELETE FROM providers WHERE id = 1")
        строка = conn.execute(
            "SELECT provider_id, provider_name, amount FROM promo_payments"
        ).fetchone()
        self.assertEqual(строка, (None, "Сенім", 1999))


if __name__ == "__main__":
    unittest.main()
