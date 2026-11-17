"""Проверка счётчика показов блока продвижения.

Приложение целиком на старом Python не запускается, поэтому тест берёт из
исходников только то, что ему нужно: схему базы из `app/database.py` и сами
запросы из `app/crud.py`. Так проверяется настоящий SQL, а не его копия,
переписанная в тест.

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


def _присваивания(файл, имена):
    дерево = ast.parse((КОРЕНЬ / "app" / файл).read_text())
    return {
        узел.targets[0].id: ast.literal_eval(узел.value)
        for узел in дерево.body
        if isinstance(узел, ast.Assign)
        and getattr(узел.targets[0], "id", "") in имена
    }


def _строки_функции(файл, имя):
    """Строковые литералы внутри функции - в них и лежит запрос."""
    дерево = ast.parse((КОРЕНЬ / "app" / файл).read_text())
    for узел in ast.walk(дерево):
        if isinstance(узел, ast.FunctionDef) and узел.name == имя:
            return [
                вложенный.value
                for вложенный in ast.walk(узел)
                if isinstance(вложенный, ast.Constant)
                and isinstance(вложенный.value, str)
            ]
    raise AssertionError(f"в {файл} нет функции {имя}")


def _запрос(файл, имя, признак):
    подходящие = [s for s in _строки_функции(файл, имя) if признак in s]
    assert подходящие, f"в {имя} нет запроса со словом {признак}"
    return max(подходящие, key=len)


СХЕМА = _присваивания("database.py", ("SCHEMA", "INDEXES"))
ЗАПИСЬ = _запрос("crud.py", "record_promo_views", "promo_views")
ВЫБОРКА = _запрос("crud.py", "promo_views_by_provider", "promo_views")
ПЕРВЫЙ_ДЕНЬ = _запрос("crud.py", "promo_views_first_day", "promo_views")


class ПоказыБлока(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        # Связь «нет карточки - нет показов» работает только при включённых
        # внешних ключах, и включать их надо до первой записи: внутри уже
        # начатой транзакции PRAGMA молча ничего не делает.
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(СХЕМА["SCHEMA"])
        self.conn.executescript(СХЕМА["INDEXES"])
        self.conn.execute(
            "INSERT INTO providers (id, provider_type, name, city, phone,"
            " description, created_at)"
            " VALUES (7, 'center', 'Место', 'Астана', '', '', '2026-11-01')"
        )

    def tearDown(self):
        self.conn.close()

    def показать(self, день, *места):
        self.conn.executemany(ЗАПИСЬ, [(день, место) for место in места])

    def test_повторный_показ_прибавляет_а_не_плодит_строки(self):
        self.показать("2026-11-18", 7)
        self.показать("2026-11-18", 7)
        строк = self.conn.execute("SELECT COUNT(*) AS n FROM promo_views").fetchone()
        самих = self.conn.execute("SELECT views FROM promo_views").fetchone()
        self.assertEqual(строк["n"], 1)
        self.assertEqual(самих["views"], 2)

    def test_разные_дни_лежат_отдельно_а_в_сумме_складываются(self):
        self.показать("2026-11-17", 7)
        self.показать("2026-11-18", 7)
        self.показать("2026-11-18", 7)
        всего = self.conn.execute(ВЫБОРКА, ("2026-11-01",)).fetchall()
        self.assertEqual([(r["provider_id"], r["views"]) for r in всего], [(7, 3)])

    def test_старые_дни_в_срок_не_попадают(self):
        self.показать("2026-10-01", 7)
        self.показать("2026-11-18", 7)
        срок = self.conn.execute(ВЫБОРКА, ("2026-11-01",)).fetchall()
        self.assertEqual(срок[0]["views"], 1)

    def test_первый_день_известен_и_пуст_пока_показов_нет(self):
        пусто = self.conn.execute(ПЕРВЫЙ_ДЕНЬ).fetchone()
        self.assertIsNone(пусто["day"])
        self.показать("2026-11-18", 7)
        self.показать("2026-11-17", 7)
        self.assertEqual(self.conn.execute(ПЕРВЫЙ_ДЕНЬ).fetchone()["day"], "2026-11-17")

    def test_удаление_карточки_уносит_её_показы(self):
        self.показать("2026-11-18", 7)
        self.conn.execute("DELETE FROM providers WHERE id = 7")
        осталось = self.conn.execute("SELECT COUNT(*) AS n FROM promo_views").fetchone()
        self.assertEqual(осталось["n"], 0)


if __name__ == "__main__":
    unittest.main()
