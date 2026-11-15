"""Проверки оповещений в Телеграм.

Запуск из корня проекта:

    python3 -m unittest discover tests

В сеть тест не выходит: отправка подменяется. Модуль `app.notifications`
нарочно не тянет за собой ни FastAPI, ни базу, поэтому тест запускается и на
старом Python, где остальной проект не поднимется.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import notifications  # noqa: E402

БЕЗ_НАСТРОЕК = {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}
С_НАСТРОЙКАМИ = {"TELEGRAM_BOT_TOKEN": "123:проверочный", "TELEGRAM_CHAT_ID": "4242"}

ЗАЯВКА = {
    "id": 7,
    "applicant_kind": "organization",
    "name": "Детский центр «Солнышко»",
    "city": "Алматы",
    "contact_person": "Айгуль",
    "phone": "+7 701 234 56 78",
    "wants_promo": 1,
    "promo_term": "6m",
    "pricing": "free",
    "created_at": "2026-11-15T09:32:00",
}


def заявка(**поля):
    данные = dict(ЗАЯВКА)
    данные.update(поля)
    return данные


class ОтветТелеграма:
    """Заглушка вместо ответа сервера: urlopen отдаёт её как контекст."""

    def __init__(self, тело):
        self.тело = json.dumps(тело).encode("utf-8")

    def read(self):
        return self.тело

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ТекстОповещения(unittest.TestCase):
    @mock.patch.dict("os.environ", {"SITE_URL": "https://erekshe.kz"})
    def test_платный_вариант_с_сроком(self):
        текст = notifications.application_text(заявка())
        self.assertIn("Детский центр «Солнышко» — организация", текст)
        self.assertIn("Город: Алматы", текст)
        self.assertIn("Размещение: платное, 6 месяцев (9 999 ₸)", текст)
        self.assertIn("Связаться: Айгуль, +7 701 234 56 78", текст)
        self.assertIn("https://erekshe.kz/admin/applications/7", текст)

    def test_бесплатный_вариант(self):
        текст = notifications.application_text(заявка(wants_promo=0, promo_term=""))
        self.assertIn("Размещение: бесплатное", текст)
        # «бесплатное» содержит «платное», поэтому проверяем со запятой:
        # так пишется только платный вариант.
        self.assertNotIn("платное,", текст)

    def test_платный_вариант_без_срока(self):
        """Срок - намерение: человек мог отметить платное и не выбрать срок."""
        текст = notifications.application_text(заявка(promo_term=""))
        self.assertIn("Размещение: платное, срок не выбран", текст)

    def test_время_казахстанское(self):
        """В базе время по Гринвичу, в сообщении - по Казахстану, +5 часов."""
        текст = notifications.application_text(заявка())
        self.assertIn("Подана: 15.11.2026 14:32", текст)
        self.assertNotIn("09:32", текст)

    def test_оповещение_короткое(self):
        """Это уведомление, а не отчёт: комментарий и почта в него не идут."""
        текст = notifications.application_text(
            заявка(comment="Длинный рассказ о центре", email="pochta@example.kz")
        )
        self.assertLessEqual(len(текст.splitlines()), 9)
        self.assertNotIn("pochta@example.kz", текст)

    @mock.patch.dict("os.environ", {"SITE_URL": "", "RENDER_EXTERNAL_HOSTNAME": "erekshe-test.onrender.com"})
    def test_ссылка_на_стенд(self):
        """На стенде ссылка ведёт на стенд, а не на живой сайт."""
        self.assertEqual(
            notifications.admin_url(7),
            "https://erekshe-test.onrender.com/admin/applications/7",
        )


class Отправка(unittest.TestCase):
    @mock.patch.dict("os.environ", БЕЗ_НАСТРОЕК)
    def test_без_переменных_в_сеть_не_ходим(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            получилось, причина = notifications.send_message("проверка")
        urlopen.assert_not_called()
        self.assertFalse(получилось)
        self.assertIn("TELEGRAM_BOT_TOKEN", причина)

    @mock.patch.dict("os.environ", С_НАСТРОЙКАМИ)
    def test_сообщение_уходит_боту_и_в_нужный_чат(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = ОтветТелеграма({"ok": True})
            получилось, причина = notifications.send_message("проверка")
        self.assertTrue(получилось, причина)
        запрос = urlopen.call_args[0][0]
        self.assertTrue(
            запрос.full_url.startswith("https://api.telegram.org/bot123:")
        )
        отправлено = json.loads(запрос.data.decode("utf-8"))
        self.assertEqual(отправлено["chat_id"], "4242")
        self.assertEqual(отправлено["text"], "проверка")

    @mock.patch.dict("os.environ", С_НАСТРОЙКАМИ)
    def test_отказ_телеграма_объясняется(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = ОтветТелеграма(
                {"ok": False, "description": "chat not found"}
            )
            получилось, причина = notifications.send_message("проверка")
        self.assertFalse(получилось)
        self.assertIn("chat not found", причина)

    @mock.patch.dict("os.environ", С_НАСТРОЙКАМИ)
    def test_обрыв_сети_не_выпускает_исключение(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("сеть молчит")):
            получилось, причина = notifications.send_message("проверка")
        self.assertFalse(получилось)
        self.assertIn("сеть молчит", причина)


class ПриёмЗаявки(unittest.TestCase):
    @mock.patch.dict("os.environ", БЕЗ_НАСТРОЕК)
    def test_без_переменных_заявка_проходит_молча(self):
        with mock.patch.object(notifications, "send_in_background") as фон:
            self.assertIsNone(notifications.notify_new_application(заявка()))
        фон.assert_not_called()

    @mock.patch.dict("os.environ", С_НАСТРОЙКАМИ)
    def test_отправка_уходит_в_фон(self):
        """Посетитель не ждёт Телеграм: запрос делает отдельный поток."""
        with mock.patch.object(notifications, "send_in_background") as фон:
            notifications.notify_new_application(заявка())
        фон.assert_called_once()
        текст = фон.call_args[0][0]
        self.assertIn("Новая заявка на размещение", текст)


if __name__ == "__main__":
    unittest.main()
