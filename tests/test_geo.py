"""Проверки определения места по адресу (app/geo.py).

Справочник DB-IP здесь не нужен: проверяется разбор записей, сводка и то,
что без справочника сайт не падает, а пишет «не определено». Тест
запускается и на старом Python, как и остальные.
"""

import os
import tempfile
import unittest
from pathlib import Path

from app import geo


def запись(iso, страна_ru, город_ru=None, страна_en="X", город_en="Y"):
    record = {"country": {"iso_code": iso, "names": {"ru": страна_ru, "en": страна_en}}}
    if город_ru:
        record["city"] = {"names": {"ru": город_ru, "en": город_en}}
    return record


class Подпись(unittest.TestCase):
    def test_страна_и_город(self):
        self.assertEqual(
            geo.describe(запись("KZ", "Казахстан", "Алматы"))["label"],
            "Казахстан, Алматы",
        )

    def test_только_страна(self):
        self.assertEqual(geo.describe(запись("US", "США"))["label"], "США")

    def test_без_русского_названия_берётся_английское(self):
        record = {"country": {"iso_code": "DE", "names": {"en": "Germany"}}}
        self.assertEqual(geo.describe(record)["label"], "Germany")

    def test_город_казахстана_без_русского_названия(self):
        record = {
            "country": {"iso_code": "KZ", "names": {"ru": "Казахстан"}},
            "city": {"names": {"en": "Almaty"}},
        }
        self.assertEqual(geo.describe(record)["label"], "Казахстан, Алматы")

    def test_незнакомый_город_остаётся_как_есть(self):
        record = {"country": {"names": {"ru": "Германия"}}, "city": {"names": {"en": "Berlin"}}}
        self.assertEqual(geo.describe(record)["label"], "Германия, Berlin")

    def test_пустая_запись(self):
        self.assertEqual(geo.describe(None)["label"], geo.UNKNOWN)


class Сводка(unittest.TestCase):
    def test_доля_казахстана_считается_от_определённых(self):
        места = [
            geo.describe(запись("KZ", "Казахстан", "Алматы")),
            geo.describe(запись("KZ", "Казахстан", "Алматы")),
            geo.describe(запись("RU", "Россия", "Москва")),
            geo.describe(None),
        ]
        итог = geo.summary(места)
        self.assertEqual(итог["total"], 4)
        self.assertEqual(итог["known"], 3)
        self.assertEqual(итог["kz"], 2)
        self.assertEqual(итог["kz_share"], 67)
        self.assertEqual(итог["rows"][0], {"label": "Казахстан, Алматы", "n": 2})
        # «Не определено» всегда внизу, даже если таких много.
        self.assertEqual(итог["rows"][-1]["label"], geo.UNKNOWN)

    def test_хвост_складывается_в_другие_места(self):
        места = [geo.describe(запись("KZ", "Казахстан", "Город %d" % i)) for i in range(12)]
        строки = geo.summary(места, top=10)["rows"]
        self.assertEqual(len(строки), 11)
        self.assertEqual(строки[-1], {"label": "другие места", "n": 2})

    def test_пусто(self):
        итог = geo.summary([])
        self.assertEqual((итог["total"], итог["kz_share"], итог["rows"]), (0, 0, []))


class БезСправочника(unittest.TestCase):
    def test_нет_файла_значит_не_определено(self):
        прежний = geo.GEO_DB_PATH
        with tempfile.TemporaryDirectory() as папка:
            geo.GEO_DB_PATH = Path(папка) / "нет-такого.mmdb"
            try:
                места = geo.locate_many(["37.99.87.182", "10.0.0.1", "мусор"])
            finally:
                geo.GEO_DB_PATH = прежний
        self.assertEqual({м["label"] for м in места.values()}, {geo.UNKNOWN})

    def test_служебные_адреса_не_ищутся(self):
        for адрес in ("127.0.0.1", "10.1.2.3", "192.168.0.5", "::1", "", "abc"):
            self.assertFalse(geo._usable(адрес), адрес)
        self.assertTrue(geo._usable("37.99.87.182"))


if __name__ == "__main__":
    unittest.main()
