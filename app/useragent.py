"""Разбор подписи браузера: робот это или человек, и с чего он смотрит.

Подпись (User-Agent) присылает сам браузер, и подделать её может кто угодно.
Поэтому здесь не защита, а статистика: отсеять заведомых роботов, чтобы
счётчик посещений показывал людей, а не обход поисковика.

Модуль нарочно ни от чего не зависит и написан без новой записи типов -
чтобы тест на него запускался и там, где само приложение не поднимается.
"""

# Слово «bot» в подписи - самый частый признак робота, но далеко не
# единственный. Google ходит на сайт не только Googlebot'ом: Google-Lens,
# Google-InspectionTool, GoogleOther - всё это обходчики, и слова «bot» в
# них нет. На этом счётчик уже один раз посчитал обход Google за людей.
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
    return not low or any(mark in low for mark in BOT_MARKERS)


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
