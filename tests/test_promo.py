"""Проверки блока платных мест (app/promo.py).

Проверяется то, что легко сломать незаметно: размер блока, отсутствие
дублей и смена очереди по часам. Запускается и на
старом Python: модуль чистый, базы и приложения ему не нужно.
"""

import unittest
from datetime import date, datetime

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
    def test_korotkiy_spisok_s_blokom(self):
        """Даже при двух найденных оплативший стоит в блоке наверху."""
        found = rows(2, paid_ids=(2,))
        block, rest = promo.split(found, MOMENT)
        self.assertEqual([r["id"] for r in block], [2])
        self.assertEqual([r["id"] for r in rest], [1])

    def test_nikto_ne_oplatil(self):
        block, rest = promo.split(rows(10), MOMENT)
        self.assertEqual(block, [])
        self.assertEqual(len(rest), 10)

    def test_men_she_trjoh_oplativshih(self):
        """Двое оплативших - оба в блоке, и в списке их больше нет."""
        block, rest = promo.split(rows(8, paid_ids=(2, 5)), MOMENT)
        self.assertEqual({r["id"] for r in block}, {2, 5})
        self.assertNotIn(2, [r["id"] for r in rest])
        self.assertEqual(len(rest), 6)

    def test_dvoe_menjajutsja_mestami_cherez_tri_chasa(self):
        """При двух оплативших первое место переходит раз в три часа."""
        found = rows(8, paid_ids=(2, 5))
        first = [promo.split(found, MOMENT.replace(hour=h))[0][0]["id"]
                 for h in range(24)]
        # Внутри трёхчасового окна первый не меняется, на границе - меняется.
        self.assertEqual(first[9:12], [first[9]] * 3)
        self.assertNotEqual(first[11], first[12])
        self.assertEqual(set(first), {2, 5})

    def test_troe_pobyvali_pervymi(self):
        """При трёх оплативших за сутки первым стоит каждый."""
        found = rows(8, paid_ids=(1, 4, 7))
        first = {promo.split(found, MOMENT.replace(hour=h))[0][0]["id"]
                 for h in range(24)}
        self.assertEqual(first, {1, 4, 7})

    def test_sostav_bloka_ot_porjadka_ne_zavisit(self):
        """Меняются только места: все трое в блоке в любой час."""
        found = rows(8, paid_ids=(1, 4, 7))
        for hour in range(24):
            block, rest = promo.split(found, MOMENT.replace(hour=hour))
            self.assertEqual({r["id"] for r in block}, {1, 4, 7})
            self.assertEqual(len(rest), 5)

    def test_chasy_ne_zakreplajutsja_pri_dvuh_i_trjoh(self):
        """Через сутки в тот же час первым стоит другой.

        Восемь трёхчасовых окон делятся и на двоих, и на четверых, так что
        без суточной добавки за каждым закрепились бы одни и те же часы.
        """
        for paid_ids in ((2, 5), (1, 4, 7)):
            found = rows(8, paid_ids=paid_ids)
            today, _ = promo.split(found, MOMENT)
            tomorrow, _ = promo.split(found, MOMENT.replace(day=8))
            self.assertNotEqual([r["id"] for r in today],
                                [r["id"] for r in tomorrow])

    def test_pjatero_oplativshih_stojat_vse(self):
        """Пятеро помещаются в блок целиком: место есть для каждого."""
        block, rest = promo.split(rows(12, paid_ids=(1, 2, 3, 4, 5)), MOMENT)
        self.assertEqual({r["id"] for r in block}, {1, 2, 3, 4, 5})
        self.assertEqual(len(rest), 7)

    def test_blok_ne_bolshe_pjati(self):
        block, rest = promo.split(rows(12, paid_ids=(1, 2, 3, 4, 5, 6, 7)), MOMENT)
        self.assertEqual(len(block), promo.BLOCK_SIZE)
        self.assertEqual(len(rest), 7)

    def test_bez_dublej(self):
        """Карточка из блока не повторяется в списке ниже."""
        block, rest = promo.split(rows(12, paid_ids=(1, 2, 3, 4, 5, 6, 7)), MOMENT)
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
        self.assertEqual({r["id"] for r in block}, {1, 2})

    def test_cherez_chas_okno_sdvinulos(self):
        """Через час состав меняется на одного, четверо остаются."""
        found = rows(12, paid_ids=(1, 2, 3, 4, 5, 6, 7))
        first, _ = promo.split(found, MOMENT)
        later, _ = promo.split(found, MOMENT.replace(hour=11))
        self.assertNotEqual([r["id"] for r in first], [r["id"] for r in later])
        self.assertEqual(len(set(r["id"] for r in first) & set(r["id"] for r in later)), 4)

    def test_za_sutki_pobyvali_vse(self):
        """При семи оплативших за семь часов наверху побывает каждый."""
        found = rows(12, paid_ids=(1, 2, 3, 4, 5, 6, 7))
        seen = set()
        for hour in range(7):
            block, _ = promo.split(found, MOMENT.replace(hour=hour))
            seen |= {r["id"] for r in block}
        self.assertEqual(seen, {1, 2, 3, 4, 5, 6, 7})

    def test_chasy_ne_zakreplajutsja_za_mestom(self):
        """При двенадцати оплативших часы не повторяются день в день.

        Без суточной добавки к сдвигу число оплативших, которое делит
        сутки нацело, закрепило бы за каждым одни и те же часы навсегда.
        """
        found = rows(20, paid_ids=tuple(range(1, 13)))
        today, _ = promo.split(found, MOMENT)
        tomorrow, _ = promo.split(found, MOMENT.replace(day=8))
        self.assertNotEqual([r["id"] for r in today], [r["id"] for r in tomorrow])


class PromoAllowedTest(unittest.TestCase):
    def test_lyuboy_gorod(self):
        self.assertTrue(promo.promo_allowed("Тараз"))
        self.assertTrue(promo.promo_allowed("Жезказган"))

    def test_bez_goroda(self):
        self.assertFalse(promo.promo_allowed(""))
        self.assertFalse(promo.promo_allowed("   "))
        self.assertFalse(promo.promo_allowed(None))

class SravnenieSObychnoyTest(unittest.TestCase):
    """Сравнение с карточкой, за которую не платили.

    Главное, что тут проверяется: возраст карточки не должен портить
    сравнение. Иначе оплативший, появившийся на сайте вчера, выглядел бы
    хуже всех только потому, что вчера появился.
    """

    ОКНО = date(2026, 10, 18)
    СЕГОДНЯ = date(2026, 11, 17)

    def дней(self, появилась):
        return promo.days_online(появилась, self.ОКНО, self.СЕГОДНЯ)

    def test_vozrast_schitaetsya_ot_poyavleniya(self):
        self.assertEqual(self.дней("2026-11-14"), 4)
        self.assertEqual(self.дней("2026-11-17"), 1)

    def test_staraya_kartochka_zhivyot_vsyo_okno(self):
        self.assertEqual(self.дней("2026-01-01"), 31)

    def test_vremya_v_date_ne_meshaet(self):
        self.assertEqual(self.дней("2026-11-14T09:30:00+00:00"), 4)

    def test_pustaya_data_schitaetsya_kak_vsyo_okno(self):
        # Так среднее у обычных карточек занижается, а не завышается:
        # ошибка в данных не должна делать продвижение красивее.
        self.assertEqual(self.дней(""), 31)
        self.assertEqual(self.дней("не дата"), 31)

    def test_data_iz_budushchego_ne_daet_nol_dney(self):
        self.assertEqual(self.дней("2027-01-01"), 1)

    def test_srednee_v_den_ne_zavisit_ot_vozrasta(self):
        # Две карточки получают одинаково - по одному открытию в день.
        # Одна висит всё окно, вторая появилась четыре дня назад.
        счётчики = {1: 31, 2: 4}
        даты = {1: "2026-01-01", 2: "2026-11-14"}
        в_день = promo.usual_per_day([1, 2], счётчики, даты, self.ОКНО, self.СЕГОДНЯ)
        self.assertAlmostEqual(в_день, 1.0)

    def test_odna_populyarnaya_ne_pereveshivaet_desyatok_obychnyh(self):
        # Среднее берётся из дневных долей, а не делением общей суммы:
        # иначе одна карточка с сотней открытий решала бы всё.
        счётчики = {1: 100}
        счётчики.update({i: 0 for i in range(2, 12)})
        даты = {i: "2026-01-01" for i in range(1, 12)}
        в_день = promo.usual_per_day(
            list(range(1, 12)), счётчики, даты, self.ОКНО, self.СЕГОДНЯ
        )
        self.assertLess(в_день, 0.4)

    def test_bez_obychnyh_kartochek_sravnivat_ne_s_chem(self):
        self.assertEqual(promo.usual_per_day([], {}, {}, self.ОКНО, self.СЕГОДНЯ), 0.0)

    def test_ozhidanie_za_stolko_zhe_dney(self):
        self.assertAlmostEqual(promo.usual_for_days(0.5, 4), 2.0)
        self.assertEqual(promo.usual_for_days(0.5, 0), 0)

    def test_podpis_okruglyaetsya_i_ne_vryot_nulyom(self):
        self.assertEqual(promo.usual_text(0), "0")
        self.assertEqual(promo.usual_text(0.2), "меньше 1")
        self.assertEqual(promo.usual_text(0.6), "1")
        self.assertEqual(promo.usual_text(2.4), "2")


if __name__ == "__main__":
    unittest.main()
