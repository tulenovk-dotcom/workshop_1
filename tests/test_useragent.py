"""Проверки разбора подписи браузера.

Запуск из корня проекта:

    python3 -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.useragent import BOT_MARKERS, device_from_agent, looks_like_bot  # noqa: E402

# Подписи настоящих браузеров. Ни одна из них не должна быть принята за
# робота: иначе счётчик перестанет видеть живых людей.
ЛЮДИ = {
    "Chrome на Windows": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Safari на Mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
        " (KHTML, like Gecko) Version/17.6 Safari/605.1.15"
    ),
    "Safari на iPhone": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X)"
        " AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6"
        " Mobile/15E148 Safari/604.1"
    ),
    "Chrome на Android": (
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36"
    ),
    "планшет iPad": (
        "Mozilla/5.0 (iPad; CPU OS 17_6 like Mac OS X) AppleWebKit/605.1.15"
        " (KHTML, like Gecko) Version/17.6 Safari/604.1"
    ),
    "Яндекс.Браузер": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/128.0.0.0 YaBrowser/24.10.0.0"
        " Safari/537.36"
    ),
}

# Роботы. У части из них слова «bot» в подписи нет - именно на таких
# счётчик и спотыкался.
РОБОТЫ = {
    "Google-Lens": "Google-Lens",
    "Googlebot": (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "Google-InspectionTool": (
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P)"
        " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile"
        " Safari/537.36 (compatible; Google-InspectionTool/1.0)"
    ),
    "GoogleOther": "Mozilla/5.0 (compatible; GoogleOther)",
    "YandexBot": "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    "Bytespider": "Mozilla/5.0 (compatible; Bytespider; spider-feedback@bytedance.com)",
    "Facebook": "facebookexternalhit/1.1",
    "curl": "curl/8.7.1",
    "пустая подпись": "",
}


class ОтсевРоботов(unittest.TestCase):
    def test_живые_браузеры_не_считаются_роботами(self):
        for название, подпись in ЛЮДИ.items():
            with self.subTest(название):
                self.assertFalse(
                    looks_like_bot(подпись), f"{название} приняли за робота"
                )

    def test_роботы_отсеиваются(self):
        for название, подпись in РОБОТЫ.items():
            with self.subTest(название):
                self.assertTrue(
                    looks_like_bot(подпись), f"{название} прошёл как человек"
                )

    def test_google_lens_именно_тот_случай(self):
        """Подпись, из-за которой обход Google попал в счётчик как люди."""
        self.assertTrue(looks_like_bot("Google-Lens"))

    def test_пробелы_библиотеки_закрыты_своим_списком(self):
        """Этих подписей в списке crawlerdetect на 30.07.2026 нет.

        Проверяем именно свой список, а не общую функцию: если однажды его
        решат выбросить как лишний, тест упадёт и напомнит, почему он есть.
        """
        for подпись in ("Google-Lens", "Bytespider"):
            with self.subTest(подпись):
                низ = подпись.lower()
                self.assertTrue(
                    any(mark in низ for mark in BOT_MARKERS),
                    f"{подпись} держится только на своём списке - не убирайте его",
                )

    def test_подпись_отсутствует(self):
        self.assertTrue(looks_like_bot(None))
        self.assertTrue(looks_like_bot(""))


class ПроверкаВладельца(unittest.TestCase):
    """Четыре случая, которые владелец просил проверить отдельно.

    Они собраны в своём наборе нарочно: это договорённость о поведении,
    а не просто ещё несколько примеров.
    """

    def test_обычный_визит_засчитывается(self):
        self.assertFalse(looks_like_bot(ЛЮДИ["Chrome на Windows"]))
        self.assertFalse(looks_like_bot(ЛЮДИ["Safari на iPhone"]))

    def test_яндекс_браузер_засчитывается(self):
        """Живой браузер, подпись которого легче всего принять за робота."""
        self.assertFalse(looks_like_bot(ЛЮДИ["Яндекс.Браузер"]))

    def test_превью_из_telegram_не_засчитывается(self):
        self.assertTrue(looks_like_bot("TelegramBot (like TwitterBot)"))

    def test_превью_из_whatsapp_не_засчитывается(self):
        """WhatsApp есть в списке библиотеки, но проверяем свой список:
        если библиотека не поставится, превью всё равно не должно считаться
        посетителем."""
        for подпись in ("WhatsApp/2.23.20.0", "WhatsApp/2.19.81 A"):
            with self.subTest(подпись):
                низ = подпись.lower()
                self.assertTrue(any(mark in низ for mark in BOT_MARKERS))

    def test_превью_из_viber_не_засчитывается(self):
        """Viber не знает ни библиотека, ни чужие списки - только наш."""
        self.assertTrue(looks_like_bot("Viber/22.4.0"))


class ОпределениеУстройства(unittest.TestCase):
    def test_телефон(self):
        self.assertEqual(device_from_agent(ЛЮДИ["Safari на iPhone"]), "телефон")
        self.assertEqual(device_from_agent(ЛЮДИ["Chrome на Android"]), "телефон")

    def test_планшет(self):
        self.assertEqual(device_from_agent(ЛЮДИ["планшет iPad"]), "планшет")
        self.assertEqual(
            device_from_agent("Mozilla/5.0 (Linux; Android 14; Tab S9)"), "планшет"
        )

    def test_компьютер(self):
        self.assertEqual(device_from_agent(ЛЮДИ["Chrome на Windows"]), "компьютер")
        self.assertEqual(device_from_agent(ЛЮДИ["Safari на Mac"]), "компьютер")

    def test_пустая_подпись(self):
        self.assertEqual(device_from_agent(None), "компьютер")


if __name__ == "__main__":
    unittest.main()
