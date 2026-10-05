"""Проверки показа времени.

Запуск из корня проекта:

    python3 -m unittest discover tests

Модуль `app.timeutil` нарочно не тянет за собой ни FastAPI, ни базу, поэтому
тест запускается где угодно, в том числе на старом Python, где остальной
проект не поднимется.
"""

import sys
import unittest
from datetime import timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.timeutil import KZ_TIME, local_date, local_time, to_local  # noqa: E402


class ПоказВремени(unittest.TestCase):
    def test_пояс_казахстанский(self):
        """Смещение +5 часов - то, по которому живёт Казахстан."""
        moment = to_local("2026-10-05T16:17:00+00:00")
        self.assertEqual(moment.utcoffset(), timedelta(hours=5))

    def test_обычное_время(self):
        """Тот самый случай, с которого всё началось: 16:17 по Гринвичу -
        это 21:17 по Казахстану."""
        self.assertEqual(local_time("2026-10-05T16:17:00+00:00"), "05.10.2026 21:17")
        self.assertEqual(local_date("2026-10-05T16:17:00+00:00"), "05.10.2026")

    def test_полночь_по_казахстану_это_вчера_по_гринвичу(self):
        """Главная ловушка. 19:00 по Гринвичу - уже следующие сутки в
        Казахстане, и дата должна смениться вместе со временем."""
        self.assertEqual(local_time("2026-10-05T19:00:00+00:00"), "06.10.2026 00:00")
        self.assertEqual(local_date("2026-10-05T19:00:00+00:00"), "06.10.2026")

    def test_полночь_по_гринвичу_это_ещё_вчерашний_вечер(self):
        """Обратный край суток: 00:00 по Гринвичу - это 05:00 того же дня."""
        self.assertEqual(local_time("2026-10-05T00:00:00+00:00"), "05.10.2026 05:00")

    def test_пустое_значение(self):
        """Пустое поле не должно ронять страницу."""
        for empty in ("", None):
            self.assertEqual(local_time(empty), "")
            self.assertEqual(local_date(empty), "")
            self.assertIsNone(to_local(empty))

    def test_мусор_вместо_времени(self):
        """Если в поле не время, показываем как есть, но не падаем."""
        self.assertEqual(local_time("не дата"), "не дата")
        self.assertEqual(local_date("2026-13-45"), "2026-13-45")

    def test_запись_без_пояса(self):
        """Старые записи могли лечь без пояса - считаем их гринвичскими."""
        self.assertEqual(local_time("2026-10-05T16:17:00"), "05.10.2026 21:17")

    def test_пояс_задан_именем_а_не_числом(self):
        """Имя пояса переживёт смену правил, записанное число - нет."""
        self.assertNotEqual(KZ_TIME, timezone(timedelta(hours=5)))


if __name__ == "__main__":
    unittest.main()
