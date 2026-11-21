"""Проверки страниц «город + направление» (app/reference.py).

Главное, за чем здесь следят: направление привязано к специальности и
методу по названию, а названия живут в других справочниках. Переименуют
специальность в SPECIALTIES или код метода в DEFAULT_METHODS - страница
останется, но станет пустой, и узнать об этом из диффа нельзя. Тест
ловит именно это.

Запускается и на старом Python, как и остальные: справочник обходится
без аннотаций, которых там нет.
"""

import unittest

from app.reference import (
    DEFAULT_METHODS,
    DIRECTION_MIN_CARDS,
    DIRECTION_PAGES,
    SPECIALTIES,
    direction_matches,
)

ОЖИДАЕМЫЕ_АДРЕСА = {
    "logoped",
    "defektolog",
    "aba",
    "psiholog",
    "neiropsiholog",
    "ergoterapevt",
    "nevrolog",
}

МЕТОДЫ = {code: level for code, _name, level, _text in DEFAULT_METHODS}


class Справочник(unittest.TestCase):
    def test_адреса_на_месте(self):
        self.assertEqual(set(DIRECTION_PAGES), ОЖИДАЕМЫЕ_АДРЕСА)

    def test_специальность_есть_в_справочнике(self):
        for slug, page in DIRECTION_PAGES.items():
            with self.subTest(slug):
                self.assertIn(page["specialty"], SPECIALTIES)

    def test_метод_есть_в_справочнике(self):
        for slug, page in DIRECTION_PAGES.items():
            if not page["method"]:
                continue
            with self.subTest(slug):
                self.assertIn(page["method"], МЕТОДЫ)

    def test_метод_показывают_в_карточках(self):
        """Метод без доказательств в карточках и фильтре не показывается.

        Собирать по такому методу страницу нельзя: человек увидел бы
        список мест, а в карточках - ни слова о том, за что они туда
        попали.
        """
        for slug, page in DIRECTION_PAGES.items():
            if not page["method"]:
                continue
            with self.subTest(slug):
                self.assertIn(МЕТОДЫ[page["method"]], ("proven", "limited"))

    def test_формы_слов_заполнены(self):
        for slug, page in DIRECTION_PAGES.items():
            for key in ("label_ru", "label_kk", "phrase_kk", "one_ru", "one_kk"):
                with self.subTest(slug=slug, key=key):
                    self.assertTrue(page.get(key))

    def test_порог_не_ниже_трёх(self):
        self.assertGreaterEqual(DIRECTION_MIN_CARDS, 3)


class Отбор(unittest.TestCase):
    def test_специальность_подходит(self):
        self.assertTrue(
            direction_matches(DIRECTION_PAGES["logoped"], "Логопед", set())
        )

    def test_парный_метод_подходит(self):
        self.assertTrue(
            direction_matches(DIRECTION_PAGES["logoped"], "", {"speech"})
        )

    def test_чужой_метод_не_подходит(self):
        self.assertFalse(
            direction_matches(DIRECTION_PAGES["logoped"], "", {"aba", "pecs"})
        )

    def test_без_парного_метода_только_специальность(self):
        """У психолога пары в справочнике методов нет."""
        page = DIRECTION_PAGES["psiholog"]
        self.assertTrue(direction_matches(page, "Психолог", set()))
        self.assertFalse(direction_matches(page, "", {"speech", "aba"}))

    def test_пустая_специальность_не_подходит(self):
        """У места занятий специальность пустая, и пустое с пустым не
        совпадает: иначе на страницу попали бы все центры подряд."""
        self.assertFalse(
            direction_matches(DIRECTION_PAGES["nevrolog"], "", set())
        )


if __name__ == "__main__":
    unittest.main()
