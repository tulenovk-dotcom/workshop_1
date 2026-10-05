"""Разбор подписи браузера: робот это или человек, и с чего он смотрит.

Подпись (User-Agent) присылает сам браузер, и подделать её может кто угодно.
Поэтому здесь не защита, а статистика: отсеять заведомых роботов, чтобы
счётчик посещений показывал людей, а не обход поисковика.

Проверок две, и одна другую не заменяет.

Первая - библиотека `crawlerdetect`: около полутора тысяч правил, которые
поддерживает кто-то кроме нас. Она ловит то, о чём мы бы сами не вспомнили:
скрейперы, архиваторы, библиотеки запросов, служебные обходчики.

Вторая - короткий список ниже, на её пробелы. Он нужен не для порядка: в
списке библиотеки на 30.07.2026 **нет подписи `Google-Lens`**, а именно она
и попала в счётчик как живой посетитель. Нет там и `Bytespider`. Выбросив
этот список, мы вернули бы ровно ту ошибку, из-за которой всё затевалось.
Проверено чтением списка библиотеки, а не предположением.

Если библиотека почему-то не поставится, остаётся короткий список и сайт
продолжает работать: отсев станет грубее, но ничего не сломается.

Модуль нарочно не зависит ни от FastAPI, ни от базы и написан без новой
записи типов - чтобы тест на него запускался и там, где само приложение
не поднимается.
"""

try:
    from crawlerdetect import CrawlerDetect

    _detector = CrawlerDetect()
except Exception:  # pragma: no cover - зависит от окружения
    _detector = None


BOT_MARKERS = (
    # Общие слова.
    "bot",
    "crawler",
    "spider",
    "slurp",
    # Роботы Google без слова «bot» в подписи.
    "google-",
    "googleother",
    "google favicon",
    # Прочие обходчики, у которых «bot» в подписи тоже нет.
    "yandex.com/bots",
    "bytespider",
    "facebookexternalhit",
    "meta-externalagent",
    "chatgpt-user",
    "dataforseo",
    "bingpreview",
    "ia_archiver",
    "feedfetcher",
    # Превью ссылок в мессенджерах: человек ссылку ещё не открыл, а запрос
    # к сайту уже пришёл. WhatsApp есть в библиотеке, Viber - нигде.
    "whatsapp",
    "viber",
    # Не браузеры вовсе: сетевые утилиты и проверки доступности.
    "curl",
    "wget",
    "python-requests",
    "httpx",
    "headless",
    "monitor",
    "uptime",
    "lighthouse",
    "pingdom",
)


def looks_like_bot(agent):
    """Похожа ли подпись на робота.

    Пустая подпись тоже считается роботом: у настоящего браузера она есть
    всегда.
    """
    low = (agent or "").lower()
    if not low:
        return True
    if any(mark in low for mark in BOT_MARKERS):
        return True
    if _detector is None:
        return False
    try:
        return bool(_detector.isCrawler(agent))
    except Exception:  # pragma: no cover - на чужой код не полагаемся
        return False


def device_from_agent(agent):
    """Телефон, планшет или компьютер - по подписи браузера.

    Это догадка, а не точное знание: подпись можно подделать, а некоторые
    браузеры врут нарочно. Для статистики этого довольно, для чего-то
    серьёзнее - нет.
    """
    low = (agent or "").lower()
    if "ipad" in low or "tablet" in low:
        return "планшет"
    if "android" in low and "mobi" not in low:
        # Android без пометки Mobi - обычно планшет.
        return "планшет"
    if "mobi" in low or "android" in low or "iphone" in low:
        return "телефон"
    return "компьютер"
