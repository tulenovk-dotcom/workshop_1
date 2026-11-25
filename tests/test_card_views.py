"""Проверка дневного свода открытий карточек.

Свод нужен затем, что журнал посещений живёт тридцать дней: в нём
настоящие адреса. Числа «карточка, день, сколько раз открыли» - не
персональные данные, и они остаются насовсем, иначе на странице
«Переходы» за девяносто дней и за всё время открытий не посчитать.

Приложение целиком на старом Python не запускается, поэтому тест берёт
из исходников только схему базы и сам запрос - проверяется настоящий SQL,
а не переписанная в тест копия.

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
СВОД = _запрос("crud.py", "rollup_card_views", "card_views_daily")
ПЕРВЫЙ_ДЕНЬ = _запрос("crud.py", "card_views_first_day", "card_views_daily")


class СводОткрытий(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(СХЕМА["SCHEMA"])
        self.conn.executescript(СХЕМА["INDEXES"])
        for номер in (7, 8):
            self.conn.execute(
                "INSERT INTO providers (id, provider_type, name, city, phone,"
                " description, created_at)"
                " VALUES (?, 'center', 'Место', 'Астана', '', '', '2026-11-01')",
                (номер,),
            )

    def tearDown(self):
        self.conn.close()

    def открыли(self, когда, путь, робот=0):
        """Одно открытие страницы. Время - по Гринвичу, как в журнале."""
        self.conn.execute(
            "INSERT INTO visit_log (ip, created_at, path, user_agent, device,"
            " is_bot) VALUES ('1.1.1.1', ?, ?, '', '', ?)",
            (когда, путь, робот),
        )

    def свести(self, сегодня="2026-11-25"):
        return self.conn.execute(СВОД, (сегодня,)).rowcount

    def свод(self):
        return [
            (r["day"], r["provider_id"], r["views"])
            for r in self.conn.execute(
                "SELECT * FROM card_views_daily ORDER BY day, provider_id"
            )
        ]

    def test_день_считается_по_казахстану_а_не_по_гринвичу(self):
        # 19:30 по Гринвичу - это уже половина первого ночи следующего дня
        # в Алматы. Такое открытие должно лечь в 21-е, а не в 20-е.
        self.открыли("2026-11-20T19:30:00+00:00", "/providers/7")
        self.открыли("2026-11-20T10:00:00+00:00", "/providers/7")
        self.свести()
        self.assertEqual(self.свод(), [("2026-11-20", 7, 1), ("2026-11-21", 7, 1)])

    def test_казахская_страница_идёт_в_тот_же_счёт(self):
        self.открыли("2026-11-20T10:00:00+00:00", "/providers/7")
        self.открыли("2026-11-20T10:05:00+00:00", "/kk/providers/7")
        self.свести()
        self.assertEqual(self.свод(), [("2026-11-20", 7, 2)])

    def test_роботы_в_свод_не_идут(self):
        self.открыли("2026-11-20T10:00:00+00:00", "/providers/8", робот=1)
        self.свести()
        self.assertEqual(self.свод(), [])

    def test_сегодняшний_день_не_сводится_он_ещё_идёт(self):
        self.открыли("2026-11-25T05:00:00+00:00", "/providers/7")
        self.свести(сегодня="2026-11-25")
        self.assertEqual(self.свод(), [])

    def test_повторный_запуск_ничего_не_удваивает(self):
        self.открыли("2026-11-20T10:00:00+00:00", "/providers/7")
        self.свести()
        self.assertEqual(self.свести(), 0)
        self.assertEqual(self.свод(), [("2026-11-20", 7, 1)])

    def test_удалённая_карточка_свод_не_роняет(self):
        self.открыли("2026-11-20T10:00:00+00:00", "/providers/99")
        self.открыли("2026-11-20T10:01:00+00:00", "/providers/7")
        self.свести()
        self.assertEqual(self.свод(), [("2026-11-20", 7, 1)])

    def test_первый_день_известен_и_пуст_пока_свода_нет(self):
        self.assertIsNone(self.conn.execute(ПЕРВЫЙ_ДЕНЬ).fetchone()["day"])
        self.открыли("2026-11-18T10:00:00+00:00", "/providers/7")
        self.открыли("2026-11-20T10:00:00+00:00", "/providers/7")
        self.свести()
        день = self.conn.execute(ПЕРВЫЙ_ДЕНЬ).fetchone()["day"]
        self.assertEqual(день, "2026-11-18")

    def test_свод_переживает_чистку_журнала(self):
        self.открыли("2026-11-20T10:00:00+00:00", "/providers/7")
        self.свести()
        self.conn.execute("DELETE FROM visit_log")
        self.assertEqual(self.свод(), [("2026-11-20", 7, 1)])

    def test_удаление_карточки_уносит_её_свод(self):
        self.открыли("2026-11-20T10:00:00+00:00", "/providers/7")
        self.свести()
        self.conn.execute("DELETE FROM providers WHERE id = 7")
        self.assertEqual(self.свод(), [])


if __name__ == "__main__":
    unittest.main()
