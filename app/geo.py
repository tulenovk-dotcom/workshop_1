"""Откуда зашёл посетитель: страна и город по IP-адресу.

Определение идёт по файлу-справочнику на нашем же сервере: DB-IP «IP to
City Lite» в формате MMDB. Адрес никуда не отправляется - ни в сторонние
сервисы, ни в сам DB-IP. Справочник раз в месяц обновляет отдельная
команда `python -m app.geo_update`; сайт подхватывает новый файл сам, без
перезапуска.

Лицензия справочника - CC BY 4.0. Она требует ссылку на DB-IP на каждой
странице, где показываются результаты: см. `ATTRIBUTION_URL` и шаблон
`admin/visitors.html`.

Точность. Страна почти всегда верна. Город для домашнего интернета чаще
верен, для мобильного часто нет: операторы выпускают абонентов в сеть
через несколько крупных узлов, и человек из Тараза может оказаться
«Алматы». Поэтому город - это примерная картина, а не факт о человеке.

Сайт не должен падать ни при каких проблемах со справочником: нет файла,
файл битый, нет библиотеки для чтения. Во всех этих случаях место просто
«не определено».

Модуль нарочно написан без новой записи типов (`str | None`): его читает
тест, который надо иметь возможность запустить и на старом Python.
"""

import ipaddress
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Iterable, Optional

log = logging.getLogger("app")

# Где лежит справочник. По умолчанию - рядом с базой сайта: на боевом
# сервере это папка данных, куда сайту разрешено писать, на стенде -
# папка проекта. Путь к базе вычисляется так же, как в database.py, но
# без импорта оттуда: модуль должен грузиться и на старом Python в тестах.
_PROJECT_DIR = Path(__file__).resolve().parent.parent
_SITE_DB = Path(os.environ.get("DB_PATH") or _PROJECT_DIR / "catalog.db")
GEO_DB_PATH = Path(os.environ.get("GEOIP_DB") or _SITE_DB.parent / "geoip-city.mmdb")

ATTRIBUTION_URL = "https://db-ip.com"

UNKNOWN = "не определено"
KAZAKHSTAN_ISO = "KZ"

_lock = threading.Lock()
_reader = None
_reader_mtime = None  # type: Optional[float]
_warned = False


def _open_reader():
    """Открыть справочник или вернуть уже открытый.

    Если файл заменили (ежемесячное обновление), открываем заново: так
    свежие данные начинают работать без перезапуска сайта.
    """
    global _reader, _reader_mtime, _warned
    try:
        mtime = GEO_DB_PATH.stat().st_mtime
    except OSError:
        if not _warned:
            log.warning(
                "Справочника местоположений нет (%s): место посетителей"
                " будет «не определено». Скачать: python -m app.geo_update",
                GEO_DB_PATH,
            )
            _warned = True
        return None
    with _lock:
        if _reader is not None and _reader_mtime == mtime:
            return _reader
        try:
            import maxminddb
        except ImportError:
            if not _warned:
                log.warning("Не установлен пакет maxminddb: место не определяется.")
                _warned = True
            return None
        try:
            fresh = maxminddb.open_database(str(GEO_DB_PATH))
        except Exception as error:  # битый или недокачанный файл
            log.warning("Не открылся справочник %s: %s", GEO_DB_PATH, error)
            return None
        old, _reader, _reader_mtime = _reader, fresh, mtime
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        return _reader


# В бесплатном справочнике у многих городов есть только английское
# название. Для городов Казахстана - а это почти все посетители - держим
# русские сами. Несколько написаний одного города: справочник пишет
# по-разному (старые и новые названия, казахская и русская латиница).
KZ_CITIES_RU = {
    "almaty": "Алматы", "alma-ata": "Алматы",
    "astana": "Астана", "nur-sultan": "Астана", "nursultan": "Астана",
    "shymkent": "Шымкент", "chimkent": "Шымкент",
    "karaganda": "Караганда", "qaraghandy": "Караганда", "karagandy": "Караганда",
    "aktobe": "Актобе", "aqtobe": "Актобе",
    "taraz": "Тараз",
    "pavlodar": "Павлодар",
    "oskemen": "Усть-Каменогорск", "ust-kamenogorsk": "Усть-Каменогорск",
    "semey": "Семей", "semipalatinsk": "Семей",
    "atyrau": "Атырау",
    "kostanay": "Костанай", "qostanay": "Костанай", "kostanai": "Костанай",
    "kyzylorda": "Кызылорда", "qyzylorda": "Кызылорда",
    "oral": "Уральск", "uralsk": "Уральск",
    "petropavl": "Петропавловск", "petropavlovsk": "Петропавловск",
    "aktau": "Актау", "aqtau": "Актау",
    "temirtau": "Темиртау",
    "turkistan": "Туркестан", "turkestan": "Туркестан",
    "kokshetau": "Кокшетау",
    "taldykorgan": "Талдыкорган", "taldyqorghan": "Талдыкорган",
    "ekibastuz": "Экибастуз",
    "rudnyy": "Рудный", "rudny": "Рудный",
    "zhezkazgan": "Жезказган",
    "balkhash": "Балхаш",
    "kaskelen": "Каскелен",
    "konaev": "Конаев", "qonaev": "Конаев", "kapchagay": "Конаев",
    "talgar": "Талгар",
    "zhanaozen": "Жанаозен",
    "satpayev": "Сатпаев",
    "kentau": "Кентау",
    "shchuchinsk": "Щучинск",
    "stepnogorsk": "Степногорск",
    "esik": "Есик", "issyk": "Есик",
}


def _name(record, key: str) -> str:
    """Название по-русски, если есть, иначе по-английски."""
    names = ((record or {}).get(key) or {}).get("names") or {}
    return names.get("ru") or names.get("en") or ""


def _city_name(record) -> str:
    names = ((record or {}).get("city") or {}).get("names") or {}
    if names.get("ru"):
        return names["ru"]
    english = names.get("en") or ""
    return KZ_CITIES_RU.get(english.strip().lower(), english)


def describe(record) -> Dict[str, str]:
    """Запись справочника в то, что показываем: страна, город, подпись."""
    if not record:
        return {"country": "", "iso": "", "city": "", "label": UNKNOWN}
    country = _name(record, "country")
    iso = ((record.get("country") or {}).get("iso_code") or "").upper()
    city = _city_name(record)
    if country and city:
        label = f"{country}, {city}"
    else:
        label = country or city or UNKNOWN
    return {"country": country, "iso": iso, "city": city, "label": label}


def _usable(ip: str) -> bool:
    """Свои, локальные и прочие служебные адреса искать бессмысленно."""
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    return address.is_global


def locate_many(ips: Iterable[str]) -> Dict[str, Dict[str, str]]:
    """Место для каждого адреса из списка. Неизвестные - «не определено»."""
    result = {}
    reader = None
    opened = False
    for ip in ips:
        if ip in result:
            continue
        record = None
        if _usable(ip):
            if not opened:
                reader, opened = _open_reader(), True
            if reader is not None:
                try:
                    record = reader.get(ip.strip())
                except Exception:
                    record = None
        result[ip] = describe(record)
    return result


def locate(ip: str) -> Dict[str, str]:
    return locate_many([ip])[ip]


def summary(places: Iterable[Dict[str, str]], top: int = 10) -> Dict:
    """Сводка «откуда заходят»: по подписи места, самые частые сверху.

    На входе - по одному месту на уникального посетителя. Всё, что не
    вошло в первые `top`, складывается в строку «другие места».
    """
    counts = {}  # type: Dict[str, int]
    total = 0
    kz = 0
    known = 0
    for place in places:
        total += 1
        counts[place["label"]] = counts.get(place["label"], 0) + 1
        if place["label"] != UNKNOWN:
            known += 1
        if place.get("iso") == KAZAKHSTAN_ISO:
            kz += 1
    ordered = sorted(
        counts.items(), key=lambda item: (item[0] == UNKNOWN, -item[1], item[0])
    )
    rows = [{"label": label, "n": n} for label, n in ordered[:top]]
    rest = sum(n for _, n in ordered[top:])
    if rest:
        rows.append({"label": "другие места", "n": rest})
    return {
        "rows": rows,
        "total": total,
        "known": known,
        "kz": kz,
        "kz_share": round(kz / known * 100) if known else 0,
        "max": max((row["n"] for row in rows), default=0),
    }


def database_available() -> bool:
    return _open_reader() is not None


# Справочник обновляется раз в месяц. Если ему больше двух месяцев, значит
# обновление несколько раз подряд не удалось - об этом надо сказать.
STALE_DAYS = 70


def database_age_days() -> Optional[int]:
    """Сколько дней назад собран справочник, или None, если его нет."""
    reader = _open_reader()
    if reader is None:
        return None
    try:
        import time

        return int((time.time() - reader.metadata().build_epoch) // 86400)
    except Exception:
        return None
