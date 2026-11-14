"""Динамика подключений: сколько карточек появлялось в каталоге и когда.

Отвечает на вопрос владельца «растём ли мы и с какой скоростью»: по дням -
чтобы видеть будни, по месяцам - чтобы видеть общую линию.

Подключением считается появление карточки в каталоге, а не поданная заявка.
Заявку могут отклонить, прислать дважды или завести карточку без заявки
вовсе - руками в админке. Если считать заявки, каталог будет выглядеть
больше, чем он есть.

Карточки делятся на организации и частных специалистов. Слово «центр» в
обиходе означает организацию, а четверть каталога - частные специалисты, и
складывать их в одно число значит отвечать не на тот вопрос.

День берётся по времени Казахстана: в базе время гринвичское, и карточка,
заведённая вечером, иначе попала бы во вчерашний столбик. Это та же
ошибка, на которой один раз споткнулась страница «Посетители».

Модуль нарочно написан без новой записи типов (`str | None`): его читает
тест, который надо иметь возможность запустить и на старом Python, где
само приложение не поднимается.
"""

from datetime import datetime, timedelta

from .timeutil import KZ_TIME, to_local

# Какой тип места считается частным специалистом; всё остальное -
# организация. Код типа берётся из `reference.PROVIDER_TYPES`.
SPECIALIST_TYPE = "specialist"

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


def plural_cards(count):
    """«1 карточка», «2 карточки», «5 карточек»."""
    if 11 <= count % 100 <= 14:
        return "карточек"
    tail = count % 10
    if tail == 1:
        return "карточка"
    if tail in (2, 3, 4):
        return "карточки"
    return "карточек"


def _month_key(moment):
    return moment.strftime("%Y-%m")


def _day_key(moment):
    return moment.strftime("%Y-%m-%d")


def _bucket(moment, step):
    return _month_key(moment) if step == "month" else _day_key(moment)


def _day_label(key):
    year, month, day = key.split("-")
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
            keys = [_shift_month(last, back) for back in range(MONTHS_SHOWN - 1, -1, -1)]
        return keys
    return [
        _day_key(today - timedelta(days=back)) for back in range(days - 1, -1, -1)
    ]


def series(rows, step="day", days=30, now=None):
    """Подключения по дням или по месяцам, от старых к новым.

    `rows` - записи с полями `created_at` и `provider_type`, как их отдаёт
    `crud.provider_growth_rows`. Принимаем и обычные пары, чтобы тест мог
    обойтись без базы.

    У каждой точки: сколько появилось организаций, сколько частных
    специалистов, сколько всего и сколько карточек в каталоге накопилось к
    концу этого дня или месяца. Накопленное считается по всему каталогу, а
    не по показанному окну: иначе «всего» на графике за неделю разошлось бы
    с числом карточек в каталоге.
    """
    if step not in STEPS:
        step = "day"
    today = (now or datetime.now(KZ_TIME)).astimezone(KZ_TIME)

    counted = []
    for row in rows:
        created = row["created_at"] if hasattr(row, "keys") else row[0]
        kind = row["provider_type"] if hasattr(row, "keys") else row[1]
        moment = to_local(created)
        if moment is None:
            # Битая дата - запись не выбрасываем из каталога, но и в
            # столбик поставить её некуда.
            continue
        counted.append((_bucket(moment, step), kind == SPECIALIST_TYPE))
    counted.sort()

    first = counted[0][0] if counted else None
    if step == "month" and first is not None:
        first = first[:7]
    keys = _keys(step, days, first, today)

    buckets = {}
    for key, is_specialist in counted:
        centers, specialists = buckets.get(key, (0, 0))
        buckets[key] = (centers + (0 if is_specialist else 1),
                        specialists + (1 if is_specialist else 0))

    points = []
    running = 0
    index = 0
    for key in keys:
        # Всё, что появилось до начала этого столбика, уже в каталоге.
        while index < len(counted) and counted[index][0] < key:
            running += 1
            index += 1
        centers, specialists = buckets.get(key, (0, 0))
        running += centers + specialists
        index += centers + specialists
        total = centers + specialists
        label = _month_label(key) if step == "month" else _day_label(key)
        title = _month_title(key) if step == "month" else _day_title(key)
        points.append({
            "key": key,
            "label": label,
            "title": "%s - %d %s" % (title, total, plural_cards(total)),
            "period": title,
            "centers": centers,
            "specialists": specialists,
            "total": total,
            "running": running,
        })
    return points
