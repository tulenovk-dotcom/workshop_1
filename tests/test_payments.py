"""Проверки правил оплат продвижения (app/payments.py).

Здесь ошибка стоит денег: не тот срок - человек заплатил и не получил
показ, или получил лишний месяц. Поэтому проверяется каждое правило
отдельно. Модуль чистый, базы и приложения ему не нужно, и тест
запускается и на старом Python.
"""

import unittest
from datetime import date

from app import payments

СЕГОДНЯ = date(2026, 11, 14)


class ПрибавлениеМесяцев(unittest.TestCase):
    def test_обычный_месяц(self):
        self.assertEqual(payments.add_months(date(2026, 11, 14), 1), date(2026, 12, 14))

    def test_через_новый_год(self):
        self.assertEqual(payments.add_months(date(2026, 12, 20), 1), date(2027, 1, 20))
        self.assertEqual(payments.add_months(date(2026, 11, 14), 12), date(2027, 11, 14))

    def test_короткий_месяц_берёт_последнее_число(self):
        """31 января плюс месяц - 28 февраля, а не 3 марта."""
        self.assertEqual(payments.add_months(date(2027, 1, 31), 1), date(2027, 2, 28))
        self.assertEqual(payments.add_months(date(2028, 1, 31), 1), date(2028, 2, 29))

    def test_назад(self):
        """Демо-оплаты стенда считаются от конца срока назад."""
        self.assertEqual(payments.add_months(date(2027, 1, 10), -1), date(2026, 12, 10))
        self.assertEqual(payments.add_months(date(2027, 3, 31), -1), date(2027, 2, 28))


class СрокОплаты(unittest.TestCase):
    def test_первая_оплата_со_дня_оплаты(self):
        """Тот самый случай «Сенім»: 14.11 на месяц - до 14.12."""
        self.assertEqual(
            payments.term("", "2026-11-14", 1), ("2026-11-14", "2026-12-14")
        )

    def test_продление_встаёт_за_прежним_сроком(self):
        """Заплатил за неделю до конца - эта неделя не пропадает."""
        self.assertEqual(
            payments.term("2026-12-14", "2026-12-07", 1), ("2026-12-14", "2027-01-14")
        )

    def test_кончившийся_срок_не_в_счёт(self):
        """Срок кончился месяц назад - новый идёт со дня оплаты, а не от старого."""
        self.assertEqual(
            payments.term("2026-10-01", "2026-11-14", 6), ("2026-11-14", "2027-05-14")
        )

    def test_оплата_в_последний_день_срока(self):
        """Последний день ещё оплачен, поэтому новый месяц идёт за ним."""
        self.assertEqual(
            payments.term("2026-11-14", "2026-11-14", 1), ("2026-11-14", "2026-12-14")
        )

    def test_непонятный_прежний_срок_не_ломает_расчёт(self):
        self.assertEqual(
            payments.term("мусор", "2026-11-14", 1), ("2026-11-14", "2026-12-14")
        )


class ОстатокСрока(unittest.TestCase):
    def test_дни(self):
        self.assertEqual(payments.days_left("2026-11-17", СЕГОДНЯ), 3)
        self.assertEqual(payments.days_left("2026-11-14", СЕГОДНЯ), 0)
        self.assertEqual(payments.days_left("2026-11-09", СЕГОДНЯ), -5)
        self.assertIsNone(payments.days_left("", СЕГОДНЯ))

    def test_словами(self):
        self.assertEqual(payments.left_text(1), "осталось 1 день")
        self.assertEqual(payments.left_text(3), "осталось 3 дня")
        self.assertEqual(payments.left_text(11), "осталось 11 дней")
        self.assertEqual(payments.left_text(21), "осталось 21 день")
        self.assertEqual(payments.left_text(0), "кончается сегодня")
        self.assertEqual(payments.left_text(-5), "кончилось 5 дней назад")
        self.assertEqual(payments.left_text(-2), "кончилось 2 дня назад")
        self.assertEqual(payments.left_text(None), "")

    def test_оплаты_словами(self):
        self.assertEqual(payments.plural_payments(1), "оплата")
        self.assertEqual(payments.plural_payments(3), "оплаты")
        self.assertEqual(payments.plural_payments(11), "оплат")
        self.assertEqual(payments.plural_payments(25), "оплат")


class КомуНаписать(unittest.TestCase):
    def test_за_неделю_до_конца_пора(self):
        self.assertTrue(payments.needs_message("2026-11-21", "", СЕГОДНЯ))

    def test_раньше_недели_рано(self):
        self.assertFalse(payments.needs_message("2026-11-22", "", СЕГОДНЯ))

    def test_две_недели_после_конца_ещё_напоминаем(self):
        self.assertTrue(payments.needs_message("2026-10-31", "", СЕГОДНЯ))

    def test_дольше_двух_недель_уже_нет(self):
        self.assertFalse(payments.needs_message("2026-10-30", "", СЕГОДНЯ))

    def test_предупредили_о_сроке_больше_не_напоминаем(self):
        self.assertFalse(payments.needs_message("2026-11-17", "2026-11-17", СЕГОДНЯ))

    def test_после_продления_отметка_не_подходит(self):
        """Предупреждали о сроке 17.11, продлили до 17.12 - к 10.12 снова пора."""
        self.assertTrue(
            payments.needs_message("2026-12-17", "2026-11-17", date(2026, 12, 10))
        )

    def test_без_срока_не_напоминаем(self):
        self.assertFalse(payments.needs_message("", "", СЕГОДНЯ))


if __name__ == "__main__":
    unittest.main()
