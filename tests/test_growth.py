"""Проверки динамики подключений.

Запуск из корня проекта:

    python3 -m unittest discover tests

Модуль `app.growth` нарочно не тянет за собой ни FastAPI, ни базу, поэтому
тест запускается где угодно, в том числе на старом Python, где остальной
проект не поднимется.

Главное, что здесь проверяется, - день считается по времени Казахстана.
В базе время гринвичское, и карточка, заведённая поздним вечером, без
перевода пояса попала бы во вчерашний столбик. На этом один раз уже
споткнулась страница «Посетители».
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.growth import KZ_TIME, plural_cards, series  # noqa: E402


def карточка(created_at, kind="center"):
    return (created_at, kind)


def момент(text):
    return datetime.fromisoformat(text).astimezone(KZ_TIME)


class ДниПоКазахстану(unittest.TestCase):
    def test_вечерняя_карточка_попадает_в_завтра(self):
        """19:30 по Гринвичу - это 00:30 следующего дня в Казахстане."""
        точки = series(
            [карточка("2026-11-14T19:30:00+00:00")],
            step="day",
            days=3,
            now=момент("2026-11-15T12:00:00+05:00"),
        )
        по_дням = {точка["key"]: точка["total"] for точка in точки}
        self.assertEqual(по_дням["2026-11-15"], 1)
        self.assertEqual(по_дням["2026-11-14"], 0)

    def test_утренняя_карточка_остаётся_в_своём_дне(self):
        точки = series(
            [карточка("2026-11-14T04:00:00+00:00")],
            step="day",
            days=3,
            now=момент("2026-11-15T12:00:00+05:00"),
        )
        по_дням = {точка["key"]: точка["total"] for точка in точки}
        self.assertEqual(по_дням["2026-11-14"], 1)
        self.assertEqual(по_дням["2026-11-15"], 0)

    def test_запись_без_пояса_считается_гринвичской(self):
        """Старые записи могли лечь без пояса - именно так их и писали."""
        точки = series(
            [карточка("2026-11-14T20:00:00")],
            step="day",
            days=2,
            now=момент("2026-11-15T12:00:00+05:00"),
        )
        по_дням = {точка["key"]: точка["total"] for точка in точки}
        self.assertEqual(по_дням["2026-11-15"], 1)


class ПустыеДни(unittest.TestCase):
    def test_день_без_подключений_остаётся_нулём(self):
        """Провал должен быть виден как провал, а не как пропуск столбика."""
        точки = series(
            [карточка("2026-11-10T06:00:00+00:00")],
            step="day",
            days=5,
            now=момент("2026-11-12T12:00:00+05:00"),
        )
        self.assertEqual(len(точки), 5)
        self.assertEqual([точка["total"] for точка in точки], [0, 0, 1, 0, 0])

    def test_дни_идут_по_возрастанию(self):
        точки = series([], step="day", days=4,
                       now=момент("2026-11-12T12:00:00+05:00"))
        ключи = [точка["key"] for точка in точки]
        self.assertEqual(ключи, sorted(ключи))
        self.assertEqual(ключи[-1], "2026-11-12")


class ЦентрыИСпециалисты(unittest.TestCase):
    def test_частный_специалист_считается_отдельно(self):
        точки = series(
            [
                карточка("2026-11-12T06:00:00+00:00", "center"),
                карточка("2026-11-12T07:00:00+00:00", "correction"),
                карточка("2026-11-12T08:00:00+00:00", "specialist"),
            ],
            step="day",
            days=1,
            now=момент("2026-11-12T20:00:00+05:00"),
        )
        self.assertEqual(точки[0]["centers"], 2)
        self.assertEqual(точки[0]["specialists"], 1)
        self.assertEqual(точки[0]["total"], 3)


class НакопленныйИтог(unittest.TestCase):
    def test_старые_карточки_входят_в_накопленное(self):
        """За окном графика каталог не начинается с нуля."""
        точки = series(
            [
                карточка("2026-09-01T06:00:00+00:00"),
                карточка("2026-09-02T06:00:00+00:00"),
                карточка("2026-11-12T06:00:00+00:00"),
            ],
            step="day",
            days=2,
            now=момент("2026-11-12T20:00:00+05:00"),
        )
        self.assertEqual(точки[0]["running"], 2)
        self.assertEqual(точки[-1]["running"], 3)

    def test_накопленное_не_убывает(self):
        точки = series(
            [карточка("2026-11-%02dT06:00:00+00:00" % день) for день in range(1, 13)],
            step="day",
            days=12,
            now=момент("2026-11-12T20:00:00+05:00"),
        )
        итоги = [точка["running"] for точка in точки]
        self.assertEqual(итоги, sorted(итоги))
        self.assertEqual(итоги[-1], 12)


class ПоМесяцам(unittest.TestCase):
    def test_месяцы_идут_подряд_без_пропусков(self):
        точки = series(
            [
                карточка("2026-09-10T06:00:00+00:00"),
                карточка("2026-11-10T06:00:00+00:00"),
            ],
            step="month",
            now=момент("2026-11-12T20:00:00+05:00"),
        )
        self.assertEqual([точка["key"] for точка in точки],
                         ["2026-09", "2026-10", "2026-11"])
        self.assertEqual([точка["total"] for точка in точки], [1, 0, 1])

    def test_подпись_месяца_в_именительном_падеже(self):
        точки = series(
            [карточка("2026-11-10T06:00:00+00:00")],
            step="month",
            now=момент("2026-11-12T20:00:00+05:00"),
        )
        self.assertEqual(точки[-1]["period"], "ноябрь 2026")
        self.assertEqual(точки[-1]["label"], "ноя 2026")

    def test_пустой_каталог_даёт_текущий_месяц(self):
        точки = series([], step="month",
                       now=момент("2026-11-12T20:00:00+05:00"))
        self.assertEqual([точка["key"] for точка in точки], ["2026-11"])
        self.assertEqual(точки[0]["total"], 0)


class Окончания(unittest.TestCase):
    def test_слово_карточка_склоняется(self):
        self.assertEqual(plural_cards(1), "карточка")
        self.assertEqual(plural_cards(3), "карточки")
        self.assertEqual(plural_cards(5), "карточек")
        self.assertEqual(plural_cards(11), "карточек")
        self.assertEqual(plural_cards(21), "карточка")
        self.assertEqual(plural_cards(0), "карточек")


if __name__ == "__main__":
    unittest.main()
