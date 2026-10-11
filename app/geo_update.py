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
import os
import shutil
import sys
import tempfile
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from .geo import GEO_DB_PATH

URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"

# Адрес для проверки: публичный DNS Google, у него страна известна всегда.
CHECK_IP = "8.8.8.8"

TIMEOUT_SECONDS = 120


def say(text: str) -> None:
    print(f"[справочник мест] {text}", flush=True)


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


def download(month: str, folder: Path) -> Path:
    """Скачать и распаковать справочник за месяц во временный файл."""
    url = URL.format(month=month)
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
    target = GEO_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
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
            fresh = download(month, target.parent)
        except Exception as error:
            say(f"за {month} скачать не удалось: {error}")
            continue
        try:
            check(fresh)
        except Exception as error:
            fresh.unlink(missing_ok=True)
            say(f"файл за {month} не прошёл проверку: {error}")
            continue
        os.chmod(fresh, 0o644)
        os.replace(fresh, target)
        say(f"готово, справочник за {month}: {target}")
        return 0

    if target.exists():
        say("обновить не получилось, остался прежний справочник")
    else:
        say("обновить не получилось, справочника нет: место будет «не определено»")
    return 1


if __name__ == "__main__":
    sys.exit(main())
