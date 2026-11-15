"""Оповещения администратора о событиях сайта.

Сейчас здесь одно оповещение: новая заявка на размещение уходит владельцу
сообщением в Телеграм. Бот и чат задаются переменными окружения
`TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`. В коде и в репозитории их быть
не должно: репозиторий публичный, а по токену бота можно писать от его имени.

Правила, которые нельзя нарушать:

1. **Сбой оповещения не мешает основному действию.** Человек отправил
   заявку - он должен увидеть страницу «заявка отправлена», даже если
   Телеграм лежит, а переменные не заданы. Поэтому запрос уходит в отдельном
   потоке, а всё, что в нём случилось, пишется в журнал и там остаётся.
2. **Посетитель не ждёт Телеграм.** Ответ страницы не должен зависеть от
   чужого сервера: запрос идёт в фоне, страница отдаётся сразу.
3. **Токен не попадает в журнал.** Он стоит в адресе запроса, поэтому адрес
   целиком никуда не выводится - только свой текст ошибки.
4. **Время в базе по Гринвичу.** Подставлять его в текст как есть нельзя:
   владелец прочитает время на пять часов меньше своего. Берётся
   `app.timeutil.local_time`.

Запрос делается через `urllib` из стандартной библиотеки. Отдельного клиента
вроде `httpx` в зависимостях проекта нет, и ради одного POST в сутки его
ставить не стоит: лишняя зависимость - лишний повод сборке упасть.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request

from .reference import APPLICANT_KINDS, promo_plan
from .timeutil import local_time

log = logging.getLogger("erekshe.notifications")

# Сколько ждём ответа Телеграма. Запрос идёт в отдельном потоке, посетителя
# это время не задерживает, но висеть вечно потоку тоже незачем.
TIMEOUT = 10


def bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def is_configured() -> bool:
    """Заданы ли бот и чат. Без них оповещения просто не отправляются."""
    return bool(bot_token() and chat_id())


def admin_url(application_id: int) -> str:
    """Адрес заявки в админке.

    На боевом сервере задана переменная `SITE_URL`. На стенде её нет, зато
    Render передаёт адрес сервиса в `RENDER_EXTERNAL_HOSTNAME` - ссылка ведёт
    на стенд, а не на живой сайт, и это то, что нужно при проверке.
    """
    site = os.environ.get("SITE_URL", "").strip()
    if not site:
        host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
        site = f"https://{host}" if host else "https://erekshe.kz"
    return f"{site.rstrip('/')}/admin/applications/{application_id}"


def money(amount: int) -> str:
    """9999 -> «9 999». Пробел тут обычный: Телеграм не вёрстка."""
    return f"{amount:,}".replace(",", " ")


def plan_line(application: dict) -> str:
    """Тариф размещения: платный вариант или бесплатный.

    Поле `pricing` к тарифу отношения не имеет - там сказано, платные ли
    занятия у самого специалиста. Тариф размещения - это `wants_promo`.
    """
    if not application.get("wants_promo"):
        return "Размещение: бесплатное"
    plan = promo_plan(application.get("promo_term") or "")
    if not plan:
        # Платный вариант отмечен, срок не выбран: так бывает, срок -
        # намерение, а не обязательство.
        return "Размещение: платное, срок не выбран"
    return f"Размещение: платное, {plan['label']} ({money(plan['price'])} ₸)"


def application_text(application: sqlite3.Row | dict) -> str:
    """Текст оповещения о новой заявке.

    Коротко: кто подал, какой тариф, город и как связаться. Подробности
    владелец смотрит по ссылке в админке.
    """
    row = dict(application)
    kind = APPLICANT_KINDS.get(row.get("applicant_kind", ""), "")
    who = row.get("name") or "без названия"
    if kind:
        who = f"{who} — {kind.lower()}"

    lines = ["Новая заявка на размещение", "", who]
    if row.get("city"):
        lines.append(f"Город: {row['city']}")
    lines.append(plan_line(row))

    contact = ", ".join(
        part for part in (row.get("contact_person"), row.get("phone")) if part
    )
    if contact:
        lines.append(f"Связаться: {contact}")
    if row.get("created_at"):
        lines.append(f"Подана: {local_time(row['created_at'])}")
    if row.get("id"):
        lines += ["", admin_url(row["id"])]
    return "\n".join(lines)


def send_message(text: str) -> tuple[bool, str]:
    """Отправить сообщение владельцу. Возвращает «получилось» и причину.

    Исключения наружу не выпускает: вызов стоит на пути приёма заявки.
    Разметку не используем - Телеграм ругается на непарные символы в
    названиях организаций, а простой текст он принимает любой.
    """
    if not is_configured():
        return False, "не заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID"

    payload = json.dumps(
        {
            "chat_id": chat_id(),
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token()}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            answer = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        # Телеграм объясняет отказ в теле ответа: «chat not found»,
        # «Unauthorized» и прочее. Адрес запроса не выводим: в нём токен.
        detail = ""
        try:
            body = json.loads(error.read().decode("utf-8", "replace"))
            detail = str(body.get("description") or "")
        except Exception:
            detail = ""
        return False, f"Телеграм ответил {error.code}" + (f": {detail}" if detail else "")
    except Exception as error:  # сеть, таймаут, неожиданный ответ
        return False, f"{type(error).__name__}: {error}"

    if not answer.get("ok"):
        return False, str(answer.get("description") or "ответ без ok")
    return True, ""


def _send_and_log(text: str, event: str) -> None:
    sent, reason = send_message(text)
    if sent:
        log.info("Оповещение в Телеграм отправлено (%s).", event)
    else:
        log.warning("Оповещение в Телеграм не отправлено (%s): %s", event, reason)


def send_in_background(text: str, event: str) -> None:
    """Отдать сообщение отдельному потоку и сразу вернуться.

    Поток служебный (daemon): если сайт выключают, он не держит остановку.
    Потерять при этом можно только оповещение, сама заявка уже в базе.
    """
    thread = threading.Thread(
        target=_send_and_log,
        args=(text, event),
        name="telegram-notify",
        daemon=True,
    )
    thread.start()


def notify_new_application(application: sqlite3.Row | dict) -> None:
    """Сообщить владельцу о новой заявке на размещение."""
    if not is_configured():
        log.info(
            "Оповещение о заявке не отправлено: не заданы TELEGRAM_BOT_TOKEN"
            " и TELEGRAM_CHAT_ID."
        )
        return
    # Текст собираем здесь, в потоке запроса: строка из базы дальше не уходит.
    send_in_background(application_text(application), "новая заявка")
