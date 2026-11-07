"""Проверки блока платных мест (app/promo.py).

Проверяется то, что легко сломать незаметно: порог в шесть карточек,
размер блока, отсутствие дублей и ротация по часам. Запускается и на
старом Python: модуль чистый, базы и приложения ему не нужно.
"""

import unittest
from datetime import datetime

from app import promo
from app.timeutil import KZ_TIME

MOMENT = datetime(2026, 11, 7, 10, 0, tzinfo=KZ_TIME)


def rows(count, paid_ids=(), until="2099-01-01"):
    return [
        {"id": i, "name": "Место %s" % i,
         "promo_until": until if i in paid_ids else ""}
        for i in range(1, count + 1)
    ]


class PromoBlockTest(unittest.TestCase):
    def test_korotkiy_spisok_bez_bloka(self):
        """Меньше шести найденных - блока нет, список не тронут."""
        found = rows(5, paid_ids=(1, 2))
        block, rest = promo.split(found, MOMENT)
        self.assertEqual(block, [])
        self.assertEqual(rest, found)

    def test_nikto_ne_oplatil(self):
        block, rest = promo.split(rows(10), MOMENT)
        self.assertEqual(block, [])
        self.assertEqual(len(rest), 10)

    def test_men_she_trjoh_oplativshih(self):
        """Двое оплативших - оба в блоке, и в списке их больше нет."""
        block, rest = promo.split(rows(8, paid_ids=(2, 5)), MOMENT)
        self.assertEqual([r["id"] for r in block], [2, 5])
        self.assertNotIn(2, [r["id"] for r in rest])
        self.assertEqual(len(rest), 6)

    def test_blok_ne_bolshe_trjoh(self):
        block, rest = promo.split(rows(12, paid_ids=(1, 2, 3, 4, 5)), MOMENT)
        self.assertEqual(len(block), promo.BLOCK_SIZE)
        self.assertEqual(len(rest), 9)

    def test_bez_dublej(self):
        """Карточка из блока не повторяется в списке ниже."""
        block, rest = promo.split(rows(12, paid_ids=(1, 2, 3, 4, 5)), MOMENT)
        self.assertFalse({r["id"] for r in block} & {r["id"] for r in rest})

    def test_istjokshij_srok_ne_schitaetsja(self):
        found = rows(8, paid_ids=(1, 2), until="2020-01-01")
        block, rest = promo.split(found, MOMENT)
        self.assertEqual(block, [])
        self.assertEqual(len(rest), 8)

    def test_posledniy_den_eshhjo_schitaetsja(self):
        """Срок «до сегодня» означает, что сегодня место ещё в блоке."""
        found = rows(8, paid_ids=(1, 2), until=MOMENT.date().isoformat())
        block, _ = promo.split(found, MOMENT)
        self.assertEqual([r["id"] for r in block], [1, 2])

    def test_cherez_chas_okno_sdvinulos(self):
        """Через час состав меняется на одного, двое остаются."""
        found = rows(12, paid_ids=(1, 2, 3, 4, 5))
        first, _ = promo.split(found, MOMENT)
        later, _ = promo.split(found, MOMENT.replace(hour=11))
        self.assertNotEqual([r["id"] for r in first], [r["id"] for r in later])
        self.assertEqual(len(set(r["id"] for r in first) & set(r["id"] for r in later)), 2)

    def test_za_sutki_pobyvali_vse(self):
        """При пяти оплативших за пять часов наверху побывает каждый."""
        found = rows(12, paid_ids=(1, 2, 3, 4, 5))
        seen = set()
        for hour in range(5):
            block, _ = promo.split(found, MOMENT.replace(hour=hour))
            seen |= {r["id"] for r in block}
        self.assertEqual(seen, {1, 2, 3, 4, 5})

    def test_chasy_ne_zakreplajutsja_za_mestom(self):
        """При двенадцати оплативших часы не повторяются день в день.

        Без суточной добавки к сдвигу число оплативших, которое делит
        сутки нацело, закрепило бы за каждым одни и те же часы навсегда.
        """
        found = rows(20, paid_ids=tuple(range(1, 13)))
        today, _ = promo.split(found, MOMENT)
        tomorrow, _ = promo.split(found, MOMENT.replace(day=8))
        self.assertNotEqual([r["id"] for r in today], [r["id"] for r in tomorrow])


class PromoCitiesTest(unittest.TestCase):
    def test_tolko_goroda_s_shestju_i_bolshe(self):
        counts = {"Астана": 16, "Алматы": 10, "Шымкент": 7,
                  "Атырау": 5, "Тараз": 1}
        self.assertEqual(promo.promo_cities(counts), ["Алматы", "Астана", "Шымкент"])

    def test_rovno_shest_prohodit(self):
        self.assertEqual(promo.promo_cities({"Актау": 6}), ["Актау"])

    def test_pustoy_spravochnik(self):
        self.assertEqual(promo.promo_cities({}), [])
        self.assertEqual(promo.promo_cities(None), [])


if __name__ == "__main__":
    unittest.main()
