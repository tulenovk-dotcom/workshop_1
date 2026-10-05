"""Время сайта: хранится по Гринвичу, показывается по Казахстану.

Разделение намеренное. В базе у всех записей единый отсчёт - так сравнение
не зависит ни от часового пояса сервера, ни от перевода часов. Но человеку
время надо показывать его собственное: администратор в Казахстане, увидев
время на пять часов меньше своего, решит, что счётчик врёт. Так уже и
случилось на странице «Посетители».

Пояс берём по имени `Asia/Almaty`, а не числом «плюс пять». Сейчас это одно
и то же - Казахстан перешёл на единое время UTC+5 в марте 2024 года, - но
правила стран меняются, и имя пояса переживёт очередную такую перемену,
а записанное число нет.

Модуль нарочно написан без новой записи типов (`str | None`): его читает
тест, который надо иметь возможность запустить и на старом Python.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("app")

KZ_ZONE_NAME = "Asia/Almaty"

# Запасной вариант на случай, если на машине нет базы часовых поясов.
# Лучше показать время с запасным смещением, чем уронить сайт при запуске.
KZ_FALLBACK = timezone(timedelta(hours=5))


def _resolve_zone():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(KZ_ZONE_NAME)
    except Exception:
        log.warning(
            "Не нашёл часовой пояс %s, время показываю со смещением +5."
            " Поставьте пакет tzdata.",
            KZ_ZONE_NAME,
        )
        return KZ_FALLBACK


KZ_TIME = _resolve_zone()


def to_local(value: str) -> Optional[datetime]:
    """Строка из базы в момент времени по Казахстану.

    Возвращает None, если на вход пришло не время: пустое поле, обрезанная
    строка, мусор. Падать из-за этого нельзя - сломается вся страница.
    """
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        # Старые записи могли лечь без пояса. Считаем их гринвичскими:
        # именно так их и писали.
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KZ_TIME)


def local_time(value: str) -> str:
    """Дата и время по Казахстану: «05.10.2026 21:17»."""
    moment = to_local(value)
    return moment.strftime("%d.%m.%Y %H:%M") if moment else (value or "")


def local_date(value: str) -> str:
    """Только дата по Казахстану: «05.10.2026»."""
    moment = to_local(value)
    return moment.strftime("%d.%m.%Y") if moment else (value or "")
