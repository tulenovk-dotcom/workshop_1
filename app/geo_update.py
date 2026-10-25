"""Скачать свежий справочник местоположений DB-IP «IP to City Lite».

Запуск: `python -m app.geo_update`

Что делает, по шагам:

1. Смотрит, какой месяц у справочника, который уже лежит на месте. Если
   этот месяц - текущий, ничего не качает: обновлять нечего.
2. Качает файл за текущий месяц. В первые дни месяца нового файла может
   ещё не быть - тогда берёт прошлый месяц.
3. Распаковывает во временный файл рядом с целевым и проверяет: файл
   открывается и по известному адресу находит страну.
4. Только после проверки подменяет старый файл новым одним действием.
   Сайт подхватит новый файл сам, перезапуск не нужен.

Если что-то пошло не так - нет сети, сайт DB-IP недоступен, файл битый, -
старый справочник остаётся на месте и сайт работает как раньше. Команда
при этом выходит с кодом 1, чтобы ошибку было видно в журнале.

Где лежит файл - см. `app/geo.py`, переменная окружения `GEOIP_DB`.
"""

import gzip
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from .geo import GEO_ASN_DB_PATH, GEO_DB_PATH

log = logging.getLogger("app")

URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"

# Второй справочник - про владельца адреса. Лежит там же и выходит теми же
# месячными выпусками. Нужен, чтобы отличить домашний интернет от
# арендованного сервера: см. geo.hosting().
URL_ASN = "https://download.db-ip.com/free/dbip-asn-lite-{month}.mmdb.gz"

# Адрес для проверки: публичный DNS Google, у него страна известна всегда.
CHECK_IP = "8.8.8.8"

TIMEOUT_SECONDS = 120


def say(text: str) -> None:
    print(f"[справочник мест] {text}", flush=True)


def _locked(folder: Path):
    """Не дать двум обновлениям идти одновременно (сайт и ручной запуск).

    Возвращает открытый файл-замок или None, если замок уже занят.
    """
    try:
        import fcntl
    except ImportError:  # не Linux - просто без замка
        return open(os.devnull, "w")
    handle = open(folder / ".geo-update.lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def months_to_try(today: date) -> list:
    current = f"{today:%Y-%m}"
    if today.month == 1:
        previous = f"{today.year - 1}-12"
    else:
        previous = f"{today.year}-{today.month - 1:02d}"
    return [current, previous]


def file_month(path: Path):
    """Месяц сборки справочника из его же служебных данных, или None."""
    try:
        import maxminddb

        with maxminddb.open_database(str(path)) as reader:
            built = datetime.fromtimestamp(reader.metadata().build_epoch, timezone.utc)
        return f"{built:%Y-%m}"
    except Exception:
        return None


def check(path: Path) -> None:
    """Файл открывается и находит страну. Иначе - исключение."""
    import maxminddb

    with maxminddb.open_database(str(path)) as reader:
        record = reader.get(CHECK_IP) or {}
    if not (record.get("country") or {}).get("iso_code"):
        raise ValueError(f"по адресу {CHECK_IP} страна не нашлась")


def check_asn(path: Path) -> None:
    """Файл открывается и находит владельца адреса. Иначе - исключение."""
    import maxminddb

    from .geo import organisation

    with maxminddb.open_database(str(path)) as reader:
        record = reader.get(CHECK_IP) or {}
    if not organisation(record):
        raise ValueError(f"по адресу {CHECK_IP} владелец не нашёлся")


def download(month: str, folder: Path, url_template: str = URL) -> Path:
    """Скачать и распаковать справочник за месяц во временный файл."""
    url = url_template.format(month=month)
    say(f"качаю {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "erekshe.kz geo update"})
    fd, packed = tempfile.mkstemp(prefix=".geo-", suffix=".gz", dir=folder)
    os.close(fd)
    fd, unpacked = tempfile.mkstemp(prefix=".geo-", suffix=".mmdb", dir=folder)
    os.close(fd)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            with open(packed, "wb") as out:
                shutil.copyfileobj(response, out)
        with gzip.open(packed, "rb") as src, open(unpacked, "wb") as out:
            shutil.copyfileobj(src, out)
    except BaseException:
        Path(unpacked).unlink(missing_ok=True)
        raise
    finally:
        Path(packed).unlink(missing_ok=True)
    return Path(unpacked)


def main() -> int:
    """Обновить оба справочника: места и владельцев адресов.

    Владелец - вещь полезная, но не обязательная: без него сайт работает,
    просто не отличает арендованный сервер от домашнего интернета. Поэтому
    его неудача на итог команды не влияет, а сообщение в журнале остаётся.
    """
    target = GEO_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = _locked(target.parent)
    if lock is None:
        say("обновление уже идёт в другом процессе, пропускаю")
        return 0
    try:
        code = _update(target)
        _update(GEO_ASN_DB_PATH, URL_ASN, check_asn, "справочник владельцев")
        return code
    finally:
        lock.close()


def _update(
    target: Path,
    url_template: str = URL,
    checker=check,
    label: str = "справочник",
) -> int:
    try:
        import maxminddb  # noqa: F401
    except ImportError:
        # Без библиотеки скачанный файл не проверить и не прочитать:
        # качать сотню мегабайт впустую незачем.
        say("не установлен пакет maxminddb: pip install -r requirements.txt")
        return 1
    today = date.today()
    months = months_to_try(today)

    if target.exists():
        have = file_month(target)
        if have == months[0]:
            say(f"уже свежий ({have}), обновлять нечего: {target}")
            return 0
        say(f"сейчас лежит справочник за {have or 'неизвестный месяц'}")

    for month in months:
        try:
            fresh = download(month, target.parent, url_template)
        except Exception as error:
            say(f"{label} за {month} скачать не удалось: {error}")
            continue
        try:
            checker(fresh)
        except Exception as error:
            fresh.unlink(missing_ok=True)
            say(f"файл за {month} не прошёл проверку: {error}")
            continue
        os.chmod(fresh, 0o644)
        os.replace(fresh, target)
        say(f"готово, {label} за {month}: {target}")
        return 0

    if target.exists():
        say(f"обновить не получилось, остался прежний {label}")
    else:
        say(f"обновить не получилось, {label} отсутствует")
    return 1


# --- Обновление изнутри сайта ----------------------------------------------
#
# Чтобы на боевом сервере не настраивать отдельное расписание, сайт сам
# следит за справочником по простому правилу:
#
# 1. Файла нет совсем - скачать (через AUTO_FIRST_DELAY после запуска).
# 2. Справочник выходит раз в месяц, в первых числах. Начиная с UPDATE_DAY
#    числа, если лежит файл за прошлый месяц, - скачать новый. Привязка к
#    числу месяца, а не к «прошло N дней», поэтому перезапуски при выкатах
#    расписание не сбивают.
# 3. Не скачалось - следующая попытка на другой день, пока работает
#    прошлый файл.
#
# Сколько бы раз сайт ни перезапускали, скачивание - одно в месяц. Раз в
# сутки сайт только смотрит на календарь и на месяц файла; в интернет при
# этом не ходит.
#
# Задержка перед первой проверкой нужна из-за выката: скрипт выката
# запускает новую версию на отдельном порту, проверяет и гасит. Такой
# пробный запуск живёт меньше минуты и качать ничего не должен.
#
# Выключается переменной GEOIP_AUTO_UPDATE=0 - например, если на сервере
# настроен таймер из deploy/erekshe-geo-update.timer.

UPDATE_DAY = 5
AUTO_FIRST_DELAY = 10 * 60
CHECK_EVERY = 24 * 60 * 60
_started = False


def update_due(target: Path, today: date) -> bool:
    """Пора ли качать: файла нет, или наступило UPDATE_DAY, а файл старый."""
    if not target.exists():
        return True
    have = file_month(target)
    if have is None:  # файл битый - заменить, не дожидаясь 5-го
        return True
    if today.day < UPDATE_DAY:
        return False
    return have != f"{today:%Y-%m}"


def _auto_loop() -> None:
    time.sleep(AUTO_FIRST_DELAY)
    while True:
        try:
            today = date.today()
            if update_due(GEO_DB_PATH, today) or update_due(GEO_ASN_DB_PATH, today):
                main()
        except Exception:
            log.exception("Фоновое обновление справочника мест упало")
        time.sleep(CHECK_EVERY)


def start_background() -> bool:
    """Запустить фоновое слежение за справочником. True, если запущено."""
    global _started
    if _started or os.environ.get("GEOIP_AUTO_UPDATE", "1") == "0":
        return False
    _started = True
    threading.Thread(target=_auto_loop, name="geo-update", daemon=True).start()
    return True


if __name__ == "__main__":
    sys.exit(main())
