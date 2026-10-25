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


class КогдаКачать(unittest.TestCase):
    """Правило обновления: одно скачивание в месяц, начиная с 5-го числа."""

    def setUp(self):
        from app import geo_update

        self.gu = geo_update
        self.папка = tempfile.TemporaryDirectory()
        self.файл = Path(self.папка.name) / "geo.mmdb"
        self.прежний = geo_update.file_month

    def tearDown(self):
        self.gu.file_month = self.прежний
        self.папка.cleanup()

    def месяц_файла(self, месяц):
        self.файл.write_bytes(b"x")
        self.gu.file_month = lambda path: месяц

    def test_нет_файла_качать_в_любой_день(self):
        from datetime import date

        self.assertTrue(self.gu.update_due(self.файл, date(2026, 10, 2)))

    def test_до_пятого_числа_старый_файл_не_трогаем(self):
        from datetime import date

        self.месяц_файла("2026-09")
        self.assertFalse(self.gu.update_due(self.файл, date(2026, 10, 4)))

    def test_с_пятого_числа_старый_файл_обновляем(self):
        from datetime import date

        self.месяц_файла("2026-09")
        self.assertTrue(self.gu.update_due(self.файл, date(2026, 10, 5)))
        self.assertTrue(self.gu.update_due(self.файл, date(2026, 10, 20)))

    def test_битый_файл_заменяем_сразу(self):
        from datetime import date

        self.месяц_файла(None)
        self.assertTrue(self.gu.update_due(self.файл, date(2026, 10, 2)))

    def test_свежий_файл_не_качаем(self):
        from datetime import date

        self.месяц_файла("2026-10")
        self.assertFalse(self.gu.update_due(self.файл, date(2026, 10, 20)))


class ВладелецАдреса(unittest.TestCase):
    """Отличить домашний интернет от арендованного сервера (geo.hosting).

    Справочник владельцев здесь тоже не нужен: проверяется разбор записи и
    список признаков. Без справочника всё должно считаться человеком -
    сомнение толкуем в его пользу.
    """

    def test_имя_владельца_из_записи(self):
        self.assertEqual(
            geo.organisation({"autonomous_system_organization": "Google LLC"}),
            "Google LLC",
        )

    def test_другое_название_поля(self):
        self.assertEqual(geo.organisation({"organization": "OVH SAS"}), "OVH SAS")

    def test_пустая_запись(self):
        self.assertEqual(geo.organisation(None), "")
        self.assertEqual(geo.organisation({}), "")

    def test_хостинги_опознаются(self):
        for имя in (
            "Google LLC",
            "Amazon.com, Inc.",
            "DigitalOcean, LLC",
            "The Constant Company, LLC",
            "Hetzner Online GmbH",
            "FranTech Solutions",
            "Alibaba Cloud LLC",
            "Omegatech LTD",
            "1337 Services GmbH",
            "TC DATACENTER LIMITED",
            "IP Volume inc",
        ):
            self.assertTrue(geo.looks_like_hosting(имя), имя)

    def test_провайдеры_связи_не_хостинги(self):
        """Казахстанские операторы - живые люди, их помечать нельзя."""
        for имя in (
            "Kazakhtelecom JSC",
            "Kar-Tel LLC",
            "JSC Kcell",
            "Mobile Telecom Service",
            "Beeline Kazakhstan",
            "Transtelecom JSC",
            "",
        ):
            self.assertFalse(geo.looks_like_hosting(имя), имя)

    def test_без_справочника_считаем_человеком(self):
        прежний = geo.GEO_ASN_DB_PATH
        geo.GEO_ASN_DB_PATH = Path(tempfile.gettempdir()) / "нет-такого-файла.mmdb"
        try:
            self.assertEqual(geo.org("8.8.8.8"), "")
            self.assertFalse(geo.hosting("8.8.8.8"))
        finally:
            geo.GEO_ASN_DB_PATH = прежний

    def test_служебные_адреса_не_ищем(self):
        self.assertEqual(geo.org("127.0.0.1"), "")
        self.assertEqual(geo.org("не адрес"), "")


if __name__ == "__main__":
    unittest.main()
