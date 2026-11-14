"""Проверки динамики подключений.

Запуск из корня проекта:

    python3 -m unittest discover tests

Модуль `app.growth` нарочно не тянет за собой ни FastAPI, ни базу, поэтому
тест запускается где угодно, в том числе на старом Python, где остальной
проект не поднимется.

Главное, что здесь проверяется, - день считается по времени Казахстана.
В базе время гринвичское, и заявка, поданная поздним вечером, без перевода
пояса попала бы во вчерашний столбик. На этом один раз уже споткнулась
страница «Посетители».
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.growth import KZ_TIME, plural_applications, series  # noqa: E402


def заявка(created_at, by_admin=0, kind="organization", provider_id=None):
    return {
        "created_at": created_at,
        "by_admin": by_admin,
        "applicant_kind": kind,
        "provider_id": provider_id,
    }


def момент(text):
    return datetime.fromisoformat(text).astimezone(KZ_TIME)


class ДниПоКазахстану(unittest.TestCase):
    def test_вечерняя_заявка_попадает_в_завтра(self):
        """19:30 по Гринвичу - это 00:30 следующего дня в Казахстане."""
        точки = series([заявка("2026-11-14T19:30:00+00:00")], step="day", days=3,
                       now=момент("2026-11-15T12:00:00+05:00"))
        по_дням = {т["key"]: т["total"] for т in точки}
        self.assertEqual(по_дням["2026-11-15"], 1)
        self.assertEqual(по_дням["2026-11-14"], 0)

    def test_утренняя_заявка_остаётся_в_своём_дне(self):
        точки = series([заявка("2026-11-14T04:00:00+00:00")], step="day", days=3,
                       now=момент("2026-11-15T12:00:00+05:00"))
        по_дням = {т["key"]: т["total"] for т in точки}
        self.assertEqual(по_дням["2026-11-14"], 1)
        self.assertEqual(по_дням["2026-11-15"], 0)

    def test_запись_без_пояса_считается_гринвичской(self):
        """Старые записи могли лечь без пояса - именно так их и писали."""
        точки = series([заявка("2026-11-14T20:00:00")], step="day", days=2,
                       now=момент("2026-11-15T12:00:00+05:00"))
        по_дням = {т["key"]: т["total"] for т in точки}
        self.assertEqual(по_дням["2026-11-15"], 1)


class ПустыеДни(unittest.TestCase):
    def test_день_без_заявок_остаётся_нулём(self):
        """Провал должен быть виден как провал, а не как пропуск столбика."""
        точки = series([заявка("2026-11-10T06:00:00+00:00")], step="day", days=5,
                       now=момент("2026-11-12T12:00:00+05:00"))
        self.assertEqual(len(точки), 5)
        self.assertEqual([т["total"] for т in точки], [0, 0, 1, 0, 0])

    def test_дни_идут_по_возрастанию(self):
        точки = series([], step="day", days=4,
                       now=момент("2026-11-12T12:00:00+05:00"))
        ключи = [т["key"] for т in точки]
        self.assertEqual(ключи, sorted(ключи))
        self.assertEqual(ключи[-1], "2026-11-12")


class КтоЗаполнилЗаявку(unittest.TestCase):
    def test_свои_и_чужие_считаются_отдельно(self):
        точки = series(
            [
                заявка("2026-11-12T06:00:00+00:00", by_admin=0),
                заявка("2026-11-12T07:00:00+00:00", by_admin=0),
                заявка("2026-11-12T08:00:00+00:00", by_admin=1),
            ],
            step="day", days=1, now=момент("2026-11-12T20:00:00+05:00"))
        self.assertEqual(точки[0]["own"], 2)
        self.assertEqual(точки[0]["by_admin"], 1)
        self.assertEqual(точки[0]["total"], 3)

    def test_пустая_отметка_считается_чужой_заявкой(self):
        """У заявок, поданных до появления столбца, отметки нет. Гадать
        задним числом нельзя - считаем, что пришли со стороны."""
        точки = series([заявка("2026-11-12T06:00:00+00:00", by_admin=None)],
                       step="day", days=1,
                       now=момент("2026-11-12T20:00:00+05:00"))
        self.assertEqual(точки[0]["own"], 1)
        self.assertEqual(точки[0]["by_admin"], 0)

    def test_подпись_столбика_называет_своих(self):
        точки = series(
            [заявка("2026-11-12T06:00:00+00:00"),
             заявка("2026-11-12T07:00:00+00:00", by_admin=1)],
            step="day", days=1, now=момент("2026-11-12T20:00:00+05:00"))
        self.assertEqual(точки[0]["title"],
                         "12 ноября 2026 - 2 заявки, из них сами 1")


class СталиКарточкой(unittest.TestCase):
    def test_заявка_с_карточкой_считается_отдельно(self):
        точки = series(
            [
                заявка("2026-11-12T06:00:00+00:00", provider_id=7),
                заявка("2026-11-12T07:00:00+00:00", provider_id=None),
            ],
            step="day", days=1, now=момент("2026-11-12T20:00:00+05:00"))
        self.assertEqual(точки[0]["total"], 2)
        self.assertEqual(точки[0]["cards"], 1)

    def test_частный_специалист_считается_отдельно(self):
        точки = series(
            [
                заявка("2026-11-12T06:00:00+00:00", kind="organization"),
                заявка("2026-11-12T07:00:00+00:00", kind="specialist"),
                заявка("2026-11-12T08:00:00+00:00", kind="doctor"),
            ],
            step="day", days=1, now=момент("2026-11-12T20:00:00+05:00"))
        self.assertEqual(точки[0]["specialists"], 1)
        self.assertEqual(точки[0]["total"], 3)


class ПоМесяцам(unittest.TestCase):
    def test_месяцы_идут_подряд_без_пропусков(self):
        точки = series(
            [заявка("2026-09-10T06:00:00+00:00"),
             заявка("2026-11-10T06:00:00+00:00")],
            step="month", now=момент("2026-11-12T20:00:00+05:00"))
        self.assertEqual([т["key"] for т in точки],
                         ["2026-09", "2026-10", "2026-11"])
        self.assertEqual([т["total"] for т in точки], [1, 0, 1])

    def test_подпись_месяца_в_именительном_падеже(self):
        точки = series([заявка("2026-11-10T06:00:00+00:00")], step="month",
                       now=момент("2026-11-12T20:00:00+05:00"))
        self.assertEqual(точки[-1]["period"], "ноябрь 2026")
        self.assertEqual(точки[-1]["label"], "ноя 2026")

    def test_пустой_список_даёт_текущий_месяц(self):
        точки = series([], step="month",
                       now=момент("2026-11-12T20:00:00+05:00"))
        self.assertEqual([т["key"] for т in точки], ["2026-11"])
        self.assertEqual(точки[0]["total"], 0)


class ЗаПределамиОкна(unittest.TestCase):
    def test_старые_заявки_не_попадают_в_показанный_срок(self):
        """Заявка двухмесячной давности не должна приписываться первому
        показанному дню."""
        точки = series(
            [заявка("2026-09-01T06:00:00+00:00"),
             заявка("2026-11-12T06:00:00+00:00")],
            step="day", days=2, now=момент("2026-11-12T20:00:00+05:00"))
        self.assertEqual([т["total"] for т in точки], [0, 1])


class Окончания(unittest.TestCase):
    def test_слово_заявка_склоняется(self):
        self.assertEqual(plural_applications(1), "заявка")
        self.assertEqual(plural_applications(3), "заявки")
        self.assertEqual(plural_applications(5), "заявок")
        self.assertEqual(plural_applications(11), "заявок")
        self.assertEqual(plural_applications(21), "заявка")
        self.assertEqual(plural_applications(0), "заявок")


if __name__ == "__main__":
    unittest.main()
