"""Проверки разбора подписи браузера.

Запуск из корня проекта:

    python3 -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.useragent import device_from_agent, looks_like_bot  # noqa: E402

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

    def test_подпись_отсутствует(self):
        self.assertTrue(looks_like_bot(None))
        self.assertTrue(looks_like_bot(""))


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
