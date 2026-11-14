"""Динамика подключений: кто и когда просился в каталог.

Отвечает на вопрос владельца «сколько специалистов разместили свои
карточки» - по дням, чтобы видеть будни, и по месяцам, чтобы видеть общую
линию.

Считается **заявка на размещение по дате подачи**, а не по дате появления
карточки. Разница не умозрительная: карточка появляется, когда заявку
одобрили, а одобряют их пачками. На живом сайте 1 ноября 2026 года в
каталоге прибавилось сразу 21 карточка - это был разбор накопившегося, а
не двадцать один человек, пришедший за один день. По дате подачи виден
ритм людей, по дате карточки - ритм администратора.

Заявки делятся на два вида: заполненные самим специалистом и заведённые
администратором - по телефону или со слов организации. Для владельца это
разные вещи: первое показывает, что о каталоге узнают и идут сами, второе
- что каталог пополняется его собственными руками. Отличаются они по
столбцу `by_admin`; у заявок, поданных до появления этого столбца, он
пустой, и их можно отметить задним числом по отпечатку адреса.

День берётся по времени Казахстана: в базе время гринвичское, и заявка,
поданная поздним вечером, иначе попала бы во вчерашний столбик. Это та же
ошибка, на которой один раз споткнулась страница «Посетители».

Модуль нарочно написан без новой записи типов (`str | None`): его читает
тест, который надо иметь возможность запустить и на старом Python, где
само приложение не поднимается.
"""

from datetime import datetime, timedelta

from .timeutil import KZ_TIME, to_local

# Какой вид заявителя считается частным специалистом; всё остальное -
# организация. Код берётся из `reference.APPLICANT_KINDS`.
SPECIALIST_KIND = "specialist"

MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн",
                "июл", "авг", "сен", "окт", "ноя", "дек")
MONTHS_FULL = ("января", "февраля", "марта", "апреля", "мая", "июня",
               "июля", "августа", "сентября", "октября", "ноября", "декабря")
# Именительный падеж нужен отдельно: подпись месяца читается «ноябрь 2026»,
# а не «ноября 2026».
MONTHS_NAMED = ("январь", "февраль", "март", "апрель", "май", "июнь",
                "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")

# Сроки, за которые можно посмотреть разбивку по дням.
DAY_PERIODS = (7, 30, 90)
# Сколько месяцев показываем, если каталог живёт дольше.
MONTHS_SHOWN = 24

STEPS = ("day", "month")


def plural_applications(count):
    """«1 заявка», «2 заявки», «5 заявок»."""
    if 11 <= count % 100 <= 14:
        return "заявок"
    tail = count % 10
    if tail == 1:
        return "заявка"
    if tail in (2, 3, 4):
        return "заявки"
    return "заявок"


def _field(row, name, default=0):
    """Поле строки базы или обычного словаря - тест обходится без базы."""
    try:
        value = row[name]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _month_key(moment):
    return moment.strftime("%Y-%m")


def _day_key(moment):
    return moment.strftime("%Y-%m-%d")


def _day_label(key):
    _, month, day = key.split("-")
    return "%d %s" % (int(day), MONTHS_SHORT[int(month) - 1])


def _day_title(key):
    year, month, day = key.split("-")
    return "%d %s %s" % (int(day), MONTHS_FULL[int(month) - 1], year)


def _month_label(key):
    year, month = key.split("-")
    return "%s %s" % (MONTHS_SHORT[int(month) - 1], year)


def _month_title(key):
    year, month = key.split("-")
    return "%s %s" % (MONTHS_NAMED[int(month) - 1], year)


def _shift_month(key, back):
    """Ключ месяца, отстоящий на `back` месяцев назад."""
    year, month = (int(part) for part in key.split("-"))
    index = year * 12 + (month - 1) - back
    return "%04d-%02d" % (index // 12, index % 12 + 1)


def _keys(step, days, first, today):
    """Подписи столбиков по возрастанию времени.

    Пустые дни и месяцы не пропускаются: провал на графике должен быть
    виден как провал, а не как отсутствие столбика.
    """
    if step == "month":
        last = _month_key(today)
        if first is None:
            return [last]
        keys = []
        key = first
        while key <= last and len(keys) < MONTHS_SHOWN:
            keys.append(key)
            year, month = (int(part) for part in key.split("-"))
            index = year * 12 + month
            key = "%04d-%02d" % (index // 12, index % 12 + 1)
        # Каталог старше срока показа - оставляем последние месяцы.
        if key <= last:
            keys = [_shift_month(last, back)
                    for back in range(MONTHS_SHOWN - 1, -1, -1)]
        return keys
    return [
        _day_key(today - timedelta(days=back)) for back in range(days - 1, -1, -1)
    ]


def series(rows, step="day", days=30, now=None):
    """Заявки по дням или по месяцам, от старых к новым.

    `rows` - записи с полями `created_at`, `by_admin`, `applicant_kind` и
    `provider_id`, как их отдаёт `crud.application_growth_rows`. Подойдёт и
    обычный словарь с теми же ключами: так тест обходится без базы.

    У каждой точки: сколько заявок подали сами специалисты, сколько завёл
    администратор, сколько всего, сколько из них уже стали карточкой и
    сколько пришло от частных специалистов.
    """
    if step not in STEPS:
        step = "day"
    today = (now or datetime.now(KZ_TIME)).astimezone(KZ_TIME)

    counted = []
    for row in rows:
        moment = to_local(_field(row, "created_at", ""))
        if moment is None:
            # Битая дата - заявку не теряем, но в столбик её поставить
            # некуда.
            continue
        key = _month_key(moment) if step == "month" else _day_key(moment)
        counted.append({
            "key": key,
            "by_admin": 1 if _field(row, "by_admin") else 0,
            "card": 1 if _field(row, "provider_id", None) else 0,
            "specialist": 1 if _field(row, "applicant_kind", "") == SPECIALIST_KIND else 0,
        })
    counted.sort(key=lambda item: item["key"])

    keys = _keys(step, days, counted[0]["key"] if counted else None, today)
    known = set(keys)

    buckets = {}
    for item in counted:
        if item["key"] not in known:
            continue
        bucket = buckets.setdefault(
            item["key"], {"own": 0, "by_admin": 0, "cards": 0, "specialists": 0}
        )
        bucket["by_admin" if item["by_admin"] else "own"] += 1
        bucket["cards"] += item["card"]
        bucket["specialists"] += item["specialist"]

    points = []
    for key in keys:
        bucket = buckets.get(key, {"own": 0, "by_admin": 0, "cards": 0,
                                   "specialists": 0})
        total = bucket["own"] + bucket["by_admin"]
        title = _month_title(key) if step == "month" else _day_title(key)
        points.append({
            "key": key,
            "label": _month_label(key) if step == "month" else _day_label(key),
            "period": title,
            "title": "%s - %d %s, из них сами %d"
                     % (title, total, plural_applications(total), bucket["own"]),
            "own": bucket["own"],
            "by_admin": bucket["by_admin"],
            "total": total,
            "cards": bucket["cards"],
            "specialists": bucket["specialists"],
        })
    return points
