"""Оплаты продвижения: сроки, суммы и кому пора написать.

Весь счёт по деньгам и датам собран здесь, отдельно от страниц и базы.
Причина простая: ошибка в этих правилах стоит дороже остальных. Ошибёшься
в дате - человек заплатил и не получил показ или получил лишний месяц;
ошибёшься в сумме - разойдётся учёт. Поэтому правила лежат одним модулем,
читаются целиком и проверяются тестами без базы и без приложения.

Что здесь решено:

- **Срок считается от прежнего срока, а не от дня оплаты.** Если человек
  платит, когда предыдущий месяц ещё не кончился, новый месяц встаёт в
  очередь за ним. Иначе продление заранее отнимало бы у него дни, и
  выгоднее было бы тянуть до последнего.
- **Дата окончания входит в срок.** «Оплачено до 14.12» означает, что
  четырнадцатого карточка ещё стоит в блоке: так же считает `promo.is_paid`.
- **Месяц прибавляется к числу, а не тридцатью днями.** Оплата 31 января
  на месяц кончается 28 февраля, а не 2 марта: короткий месяц не повод
  выдавать лишние дни, но и месяц обещан целиком.
- **Напоминание живёт неделю до конца срока и две недели после.** До -
  чтобы успеть написать, после - чтобы не потерять того, кто просто
  забыл продлить. Дальше запись уходит из списка «кому написать» и
  остаётся в таблице: вечно напоминать о прошлогоднем некому.

Модуль нарочно написан без новой записи типов (`str | None`): его читает
тест, который надо иметь возможность запустить и на старом Python.
"""

import calendar
from datetime import date, datetime

from .timeutil import KZ_TIME

# За сколько дней до конца срока показывать запись в списке «кому написать».
DUE_SOON_DAYS = 7

# Сколько дней после конца срока ещё напоминать о себе.
DUE_PAST_DAYS = 14


def today_local():
    """Сегодняшнее число по Казахстану - то же «сегодня», что у админа."""
    return datetime.now(KZ_TIME).date()


def today_iso():
    return today_local().isoformat()


def parse_day(value):
    """Строка «ГГГГ-ММ-ДД» в дату. Непонятное - None, а не падение."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def add_months(day, months):
    """Та же дата через N месяцев.

    В коротком месяце берётся его последнее число: 31 января плюс месяц -
    28 февраля. Иначе пришлось бы выдавать 3 марта, то есть лишние дни.
    """
    total = day.month - 1 + int(months)
    year = day.year + total // 12
    month = total % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def term(current_until, paid_on, months):
    """Срок, который даёт эта оплата: («показ с», «оплачено до»).

    Если прежний срок ещё не кончился, новый встаёт за ним. Если кончился
    или его не было - показ идёт со дня оплаты.
    """
    start = parse_day(paid_on) or today_local()
    previous = parse_day(current_until)
    if previous and previous >= start:
        start = previous
    return start.isoformat(), add_months(start, max(1, int(months))).isoformat()


def days_left(until, today=None):
    """Сколько дней осталось до конца срока. Отрицательное - уже кончился.

    None, если срока нет или он записан непонятно.
    """
    end = parse_day(until)
    if end is None:
        return None
    return (end - (today or today_local())).days


def plural_days(count):
    """«1 день», «2 дня», «5 дней»."""
    count = abs(count)
    if 11 <= count % 100 <= 14:
        return "дней"
    tail = count % 10
    if tail == 1:
        return "день"
    if tail in (2, 3, 4):
        return "дня"
    return "дней"


def plural_payments(count):
    """«1 оплата», «2 оплаты», «5 оплат»."""
    if 11 <= count % 100 <= 14:
        return "оплат"
    tail = count % 10
    if tail == 1:
        return "оплата"
    if tail in (2, 3, 4):
        return "оплаты"
    return "оплат"


def left_text(left):
    """Срок словами: «осталось 3 дня», «кончается сегодня», «кончилось 5 дней назад»."""
    if left is None:
        return ""
    if left == 0:
        return "кончается сегодня"
    if left > 0:
        return "осталось %d %s" % (left, plural_days(left))
    return "кончилось %d %s назад" % (-left, plural_days(left))


def needs_message(until, notified_for, today=None):
    """Пора ли писать об этой записи.

    Пора, если срок кончается в ближайшие DUE_SOON_DAYS дней или кончился
    не больше DUE_PAST_DAYS дней назад - и об этом сроке ещё не писали.
    Отметка хранит сам срок, а не дату разговора: продлили - отметка
    перестала совпадать, и напоминание придёт заново само.
    """
    left = days_left(until, today)
    if left is None:
        return False
    if left > DUE_SOON_DAYS or left < -DUE_PAST_DAYS:
        return False
    return (notified_for or "").strip() != (until or "").strip()
