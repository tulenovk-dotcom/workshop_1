import json
import logging
import os
import re
import secrets
import time
import zlib
from html import escape
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import crud
from .database import DB_PATH, db_session, init_db, read_or_create_secret
from .notifications import notify_new_application
from .i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    is_supported,
    localized_field,
    translate,
)
from .personal_data import (
    CONSENT_PURPOSES,
    CONSENT_TEXTS,
    POLICY_UPDATED,
    POLICY_VERSION,
    SUBJECT_TYPES,
    hash_ip,
    health_markers,
    mask_contact,
    mask_email,
    mask_phone,
    short_hash,
)
from .reference import (
    AGE_RANGE_BOUNDS,
    AGE_RANGES,
    APPLICANT_KINDS,
    APPLICATION_STATUSES,
    CITIES,
    CITY_NAMES,
    CITY_OTHER,
    EVIDENCE_LEVELS,
    MEDICAL_SPECIALTIES,
    OFFERED_EVIDENCE_LEVELS,
    ORGANIZATION_TYPES,
    PRICING,
    PROVIDER_TYPES,
    REQUEST_ANSWER_DAYS,
    REQUEST_STATUSES,
    SPECIALTIES,
    TYPES_WITH_SPECIALTY,
    normalize_city,
)
from .seed import seed_if_empty
from .timeutil import local_date, local_time
from .useragent import device_from_agent, looks_like_bot

log = logging.getLogger("app")

BASE_DIR = Path(__file__).resolve().parent

# На хостинге загруженные файлы лежат на подключённом диске, локально -
# внутри проекта. Адрес в браузере в обоих случаях один: /static/uploads/.
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR") or BASE_DIR / "static" / "uploads")

MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_APPLICATIONS_PER_HOUR = 3

# Пароля по умолчанию нет: без заданных переменных вход в админку закрыт.
ADMIN_LOGIN = os.environ.get("ADMIN_LOGIN", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_ENABLED = bool(ADMIN_LOGIN and ADMIN_PASSWORD)

# Перебор пароля к админке: пять неудач с адреса - и он ждёт четверть часа.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_BLOCK_SECONDS = 15 * 60

SHOW_TEST_BANNER = os.environ.get("SHOW_TEST_BANNER") == "1"

# Уведомление о тестовом режиме: тонкая полоса над шапкой и окно при первом
# визите. Включено по умолчанию; чтобы убрать, достаточно задать TEST_NOTICE=0
# в настройках сервера - править код и выкатывать новую версию не нужно.
TEST_NOTICE = os.environ.get("TEST_NOTICE", "1") != "0"
NOINDEX = os.environ.get("NOINDEX") == "1"

# Демонстрационные записи наливаются в пустую базу только по явной просьбе.
# На боевом сервере переменной нет, и каталог начинается с чистого листа.
SEED_DEMO = os.environ.get("SEED_DEMO") == "1"

# Cookie администратора уходит только по HTTPS, когда сайт за TLS.
# Локально по http флаг выключен, иначе вход не работал бы.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE") == "1"

# Адрес сайта: нужен для ссылок в sitemap.xml и для Open Graph, где
# относительные адреса не годятся.
SITE_URL = (os.environ.get("SITE_URL") or "https://erekshe.kz").rstrip("/")

MAX_REQUESTS_PER_HOUR = 3


# Стоит ли верить заголовку X-Forwarded-For.
#
# За nginx или балансировщиком адрес подключения у всех посетителей один -
# настоящий лежит в заголовке. Напрямую заголовку верить нельзя: его
# подделает кто угодно и обойдёт счётчики заявок, отзывов и блокировку
# перебора пароля. Поэтому доверие включается только вручную, и включать
# его можно, лишь когда до приложения действительно нельзя достучаться
# мимо прокси. Раньше оно включалось само по переменной RENDER - для
# своего сервера такой подсказки нет, и угадывать мы не беремся.
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS") == "1"

REDIRECT = 303


def load_secret_key() -> str:
    """Ключ подписи cookie администратора.

    Хранится между запусками, иначе каждая перезагрузка процесса обнуляет
    сессию. Без переменной окружения ключ лежит в файле рядом с базой; на
    хостинге без постоянного диска такой файл исчезает при перезапуске
    сервиса, поэтому в логах об этом сказано.
    """
    if key := os.environ.get("SECRET_KEY"):
        return key
    log.warning(
        "SECRET_KEY не задан: ключ взят из файла %s рядом с базой."
        " Задайте переменную SECRET_KEY, иначе после перезапуска сервиса"
        " администратору придётся входить заново.",
        DB_PATH.parent / ".secret_key",
    )
    return read_or_create_secret(".secret_key")


SECRET_KEY = load_secret_key()

# Схема API и страницы /docs, /redoc выключены: публичному каталогу они
# не нужны, а показывать посторонним список админских адресов незачем.
app = FastAPI(
    title="Каталог помощи детям с РАС в Казахстане",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    SessionMiddleware, secret_key=SECRET_KEY, https_only=COOKIE_SECURE
)
# Папка загрузок монтируется первой: иначе её перехватит общий /static,
# который смотрит только внутрь проекта.
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")


def format_price(value) -> str:
    if value is None:
        return ""
    return f"{int(value):,}".replace(",", " ")


def wa_link(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return f"https://wa.me/{digits}" if digits else ""


def site_link(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value if value.startswith(("http://", "https://")) else f"https://{value}"


def instagram_link(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return f"https://instagram.com/{value.lstrip('@')}"


def request_ip(request: Request) -> str:
    """Адрес посетителя - для счётчиков отзывов, заявок и попыток входа.

    За балансировщиком берём первый адрес из X-Forwarded-For: там стоит тот,
    кто обратился к сайту, дальше идут промежуточные узлы.
    """
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def request_ip_hash(request: Request) -> str:
    """Хеш адреса: только он попадает в базу и в счётчики частоты."""
    return hash_ip(request_ip(request))


def user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:300]


# --- Счётчик посещений ------------------------------------------------------

# Считаются открытия страниц, а не посетители: посетитель не помечается ни
# в базе, ни в памяти, и второе открытие с того же устройства идёт наравне
# с первым. Отличить одного человека от другого сайт при этом не может -
# и не должен.

# Админка - это администратор, а не посетитель, и в счёт не идёт.
UNCOUNTED_PREFIXES = ("/static", "/admin", "/favicon", "/robots.txt", "/sitemap.xml")

# День, в который журнал посещений чистили в последний раз.
_visit_cleanup_day = ""


@app.middleware("http")
async def language_prefix(request: Request, call_next):
    """Срезает «/kk» с начала адреса и помечает запрос как казахский.

    Делается до выбора маршрута, поэтому все обработчики остаются прежними:
    они видят адрес без префикса и не знают про языки вовсе.
    """
    path = request.scope["path"]

    # Старый способ выбора языка - параметр ?lang=kk. Он успел побывать на
    # боевом сайте, поэтому уводим с него постоянным редиректом, а не просто
    # перестаём понимать: ссылки могли куда-то попасть.
    if request.query_params.get("lang"):
        rest = [
            f"{key}={value}"
            for key, value in request.query_params.multi_items()
            if key != "lang"
        ]
        target = path
        if request.query_params.get("lang") != DEFAULT_LANGUAGE:
            target = f"{KK_PREFIX}/" if path == "/" else KK_PREFIX + path
        if rest:
            target += "?" + "&".join(rest)
        return RedirectResponse(target, status_code=301)

    if path == KK_PREFIX:
        return RedirectResponse(KK_PREFIX + "/", status_code=301)

    if path.startswith(KK_PREFIX + "/"):
        rest = path[len(KK_PREFIX):]
        # Админки, статики и служебных файлов на казахском не бывает: они
        # одни на весь сайт. Иначе у каждой страницы появился бы двойник.
        if rest.startswith(NO_PREFIX_PATHS):
            return PlainTextResponse("Страница не найдена", status_code=404)
        request.scope["path"] = rest
        request.scope["lang_prefix"] = KK_PREFIX

    return await call_next(request)


@app.middleware("http")
async def count_visit(request: Request, call_next):
    """Считает открытия страниц сайта по дням.

    Считаются только успешно открытые страницы: не картинки, не формы,
    не перенаправления и не ошибки.
    """
    response = await call_next(request)
    if request.method != "GET" or response.status_code != 200:
        return response
    if request.url.path.startswith(UNCOUNTED_PREFIXES):
        return response
    if not response.headers.get("content-type", "").startswith("text/html"):
        return response
    if looks_like_bot(user_agent(request)):
        return response

    global _visit_cleanup_day
    agent = user_agent(request)
    day = crud.visit_day()
    try:
        with db_session() as conn:
            crud.record_visit(conn, day)
            crud.record_page_view(
                conn,
                request_ip(request),
                request.url.path,
                agent,
                device_from_agent(agent),
            )
            # Чистка журнала - раз в сутки, при первом посещении нового дня.
            # Отдельного планировщика в проекте нет, а привязка к запуску
            # сайта срок хранения не выдержит: сервер работает неделями.
            if day != _visit_cleanup_day:
                _visit_cleanup_day = day
                removed = crud.cleanup_visit_log(conn)
                if removed:
                    log.info("Удалено записей журнала посещений: %s", removed)
    except Exception:
        # Счётчик не должен ронять страницу: лучше потерять одну запись,
        # чем показать человеку ошибку вместо каталога.
        log.warning("Не удалось записать посещение", exc_info=True)
    return response


def consent_data(subject_type: str, record_id: int, request: Request) -> dict:
    """Отметка о согласии: что человек видел, когда и с какой страницы."""
    return {
        "subject_type": subject_type,
        "record_id": record_id,
        "purpose": CONSENT_PURPOSES[subject_type],
        "policy_version": POLICY_VERSION,
        "consent_text": CONSENT_TEXTS[subject_type],
        "ip_hash": request_ip_hash(request),
        "user_agent": user_agent(request),
    }


# Счётчик живёт в памяти процесса: отдельная таблица тут лишняя, а при
# перезапуске блокировки и так пора забывать. На нескольких процессах
# каждый будет считать своё - для стенда этого достаточно.
_login_failures: dict[str, list[float]] = {}
_login_blocked_until: dict[str, float] = {}


def login_block_seconds_left(ip: str) -> int:
    """Сколько секунд осталось ждать этому адресу. 0 - можно пробовать."""
    until = _login_blocked_until.get(ip, 0.0)
    left = until - time.time()
    if left <= 0:
        _login_blocked_until.pop(ip, None)
        return 0
    return int(left) + 1


def register_login_failure(ip: str) -> None:
    now = time.time()
    # Старые неудачи забываем, иначе они копятся месяцами.
    attempts = [t for t in _login_failures.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
    attempts.append(now)
    _login_failures[ip] = attempts
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        _login_blocked_until[ip] = now + LOGIN_BLOCK_SECONDS
        _login_failures.pop(ip, None)

    # Подчищаем адреса, о которых давно ничего не слышно.
    for old_ip, times in list(_login_failures.items()):
        if not times or now - times[-1] > LOGIN_WINDOW_SECONDS:
            _login_failures.pop(old_ip, None)


def forget_login_failures(ip: str) -> None:
    _login_failures.pop(ip, None)
    _login_blocked_until.pop(ip, None)


def minutes_word(minutes: int) -> str:
    if minutes % 10 == 1 and minutes % 100 != 11:
        return "минуту"
    if minutes % 10 in (2, 3, 4) and minutes % 100 not in (12, 13, 14):
        return "минуты"
    return "минут"


def normalize_phone(value: str) -> str | None:
    """Номер к виду «+7 707 123 45 67».

    В форме слева от поля стоит статичный «+7», и человек вводит десять
    цифр. Но вставить номер целиком тоже никто не мешает, поэтому здесь
    принимаются и «+7 707...», и «8 707...», и «87071234567»: лишние
    символы отбрасываются, код страны отрезается. Остаться должны ровно
    десять цифр, иначе номер не принимается.
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"+7 {digits[:3]} {digits[3:6]} {digits[6:8]} {digits[8:]}"


def phone_national(value: str) -> str:
    """Те самые десять цифр - чтобы вернуть их в поле, где «+7» уже нарисован
    слева. Номер в базе хранится целиком, а поле ждёт только остаток."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    if len(digits) != 10:
        return value or ""
    return f"{digits[:3]} {digits[3:6]} {digits[6:8]} {digits[8:]}"


def normalize_phone_or_raw(value: str) -> str:
    """Для админки: приводим номер к общему виду, а непонятную запись
    оставляем как есть - лучше странный номер, чем потерянный."""
    value = (value or "").strip()
    return normalize_phone(value) or value


def looks_like_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def initials(name: str) -> str:
    parts = [part for part in re.split(r"\W+", name or "", flags=re.UNICODE) if part]
    return "".join(part[0].upper() for part in parts[:2]) or "?"


def name_hue(name: str) -> int:
    """Стабильный оттенок для плашки с инициалами, когда фото не загружено."""
    return zlib.crc32((name or "").encode("utf-8")) % 360


def image_extension(data: bytes) -> str | None:
    """Расширение по сигнатуре файла: имени и content-type из браузера верить нельзя."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


async def read_image(upload) -> tuple[bytes, str] | None:
    """Прочитать и проверить картинку, ничего не записывая на диск.
    None означает «файла нет или он не подошёл»."""
    if upload is None or not getattr(upload, "filename", ""):
        return None
    data = await upload.read(MAX_LOGO_BYTES + 1)
    extension = image_extension(data)
    if extension is None or len(data) > MAX_LOGO_BYTES:
        return None
    return data, extension


def store_image(data: bytes, extension: str) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(8)}{extension}"
    (UPLOAD_DIR / name).write_bytes(data)
    return f"/static/uploads/{name}"


async def save_logo(upload, current: str) -> str:
    image = await read_image(upload)
    return store_image(*image) if image else current


templates.env.filters["local_time"] = local_time
templates.env.filters["local_date"] = local_date
templates.env.filters["price"] = format_price
templates.env.filters["initials"] = initials
templates.env.filters["hue"] = name_hue
templates.env.filters["wa_link"] = wa_link
templates.env.filters["site_link"] = site_link
templates.env.filters["instagram_link"] = instagram_link
# Контакты в списках показываются замаскированными, поэтому маскирование -
# такой же фильтр шаблона, как и остальное форматирование.
templates.env.filters["mask_phone"] = mask_phone
templates.env.filters["phone_national"] = phone_national
templates.env.filters["mask_email"] = mask_email
templates.env.filters["mask_contact"] = mask_contact
templates.env.filters["short_hash"] = short_hash


# Браузер держит style.css в кеше, и после правки стилей он может выдать
# старый файл к новой разметке - страница рассыпается. Метка версии в адресе
# считается от содержимого файла: пока файл не менялся, адрес прежний и кеш
# работает; поменялся - адрес другой, и файл скачивается заново.
_static_versions: dict[str, str] = {}


def static_url(name: str) -> str:
    if name not in _static_versions:
        try:
            data = (BASE_DIR / "static" / name).read_bytes()
            _static_versions[name] = format(zlib.crc32(data), "x")
        except OSError:
            _static_versions[name] = "0"
    return f"/static/{name}?v={_static_versions[name]}"


def moderation_counts() -> dict:
    """Сколько всего ждёт проверки. Меню админки показывает счётчик на
    каждой странице, поэтому считаем здесь, а не в каждом обработчике."""
    with db_session() as conn:
        reviews = crud.pending_count(conn)
        applications = crud.new_applications_count(conn)
        requests = crud.new_requests_count(conn)
    return {
        "reviews": reviews,
        "applications": applications,
        "requests": requests,
        "total": reviews + applications + requests,
    }


templates.env.globals.update(
    PROVIDER_TYPES=PROVIDER_TYPES,
    CITIES=CITIES,
    CITY_NAMES=CITY_NAMES,
    CITY_OTHER=CITY_OTHER,
    EVIDENCE_LEVELS=EVIDENCE_LEVELS,
    PRICING=PRICING,
    SPECIALTIES=SPECIALTIES,
    MEDICAL_SPECIALTIES=MEDICAL_SPECIALTIES,
    TYPES_WITH_SPECIALTY=TYPES_WITH_SPECIALTY,
    SHOW_TEST_BANNER=SHOW_TEST_BANNER,
    TEST_NOTICE=TEST_NOTICE,
    NOINDEX=NOINDEX,
    SITE_URL=SITE_URL,
    ADMIN_ENABLED=ADMIN_ENABLED,
    APPLICANT_KINDS=APPLICANT_KINDS,
    APPLICATION_STATUSES=APPLICATION_STATUSES,
    ORGANIZATION_TYPES=ORGANIZATION_TYPES,
    REQUEST_STATUSES=REQUEST_STATUSES,
    REQUEST_ANSWER_DAYS=REQUEST_ANSWER_DAYS,
    SUBJECT_TYPES=SUBJECT_TYPES,
    POLICY_VERSION=POLICY_VERSION,
    POLICY_UPDATED=POLICY_UPDATED,
    moderation_counts=moderation_counts,
    health_markers=health_markers,
    static_url=static_url,
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    seed_if_empty(with_demo=SEED_DEMO)
    # Сроки хранения проверяются при запуске: отдельного планировщика в
    # проекте нет, а сервис на хостинге и так перезапускается регулярно.
    with db_session() as conn:
        cleaned = crud.cleanup_personal_data(conn)
        # Журнал посещений чистится и при запуске, и раз в сутки из счётчика:
        # если сайт долго не перезапускали, срок хранения всё равно соблюдён.
        removed = crud.cleanup_visit_log(conn)
        # Записи роботов, попавшие в журнал, пока отсев их пропускал.
        # После починки отсева таких не появляется, и уборка находит ноль.
        bots = crud.purge_bot_visits(conn)
    if cleaned:
        log.info("Обезличено записей по истечении срока хранения: %s", cleaned)
    if removed:
        log.info("Удалено записей журнала посещений: %s", removed)
    if bots:
        log.info("Убрано из журнала записей роботов: %s", bots)


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.strip().replace(" ", "")
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def offered_methods(methods) -> list:
    """Методы, которые предлагаем в анкете и в фильтре и показываем в
    карточках. Методы без доказательств при РАС остаются в справочнике и на
    странице «Методы помощи», но выбирать и рекламировать их незачем."""
    return [m for m in methods if m["evidence_level"] in OFFERED_EVIDENCE_LEVELS]


def specialty_from_form(form, kind: str) -> str:
    """Специальность из той ветки анкеты, которую человек заполнял.

    У частного специалиста и у врача списки разные, поэтому и поля разные:
    иначе браузер отправил бы оба, и сервер не понял бы, какое из них
    настоящее.
    """
    if kind == "specialist":
        value = form.get("specialty", "")
        return value if value in SPECIALTIES else ""
    if kind == "doctor":
        value = form.get("doctor_specialty", "")
        return value if value in MEDICAL_SPECIALTIES else ""
    return ""


def city_from_form(form) -> str:
    """Город из пары полей: выпадающий список и «Другой город».

    В списке выбран город - берём его. Выбран последний пункт (или список
    вообще не пришёл, например из старой закладки) - берём текстовое поле.
    """
    choice = form.get("city_choice", "")
    raw = form.get("city_other", "") if choice in ("", CITY_OTHER) else choice
    return normalize_city(raw)


# Префикс казахской версии. Русская версия живёт без префикса, казахская -
# с ним: erekshe.kz/methods и erekshe.kz/kk/methods. Язык определяется только
# по адресу, cookie и язык браузера на выбор не влияют - иначе поисковик
# видел бы одну версию вместо двух, а посетитель по ссылке попадал бы не на
# тот язык, на который ему дали ссылку.
KK_PREFIX = "/kk"

# Что под префиксом не живёт: админка, статика и служебные файлы. Они одни
# на весь сайт, и второй их копии на казахском быть не должно.
NO_PREFIX_PATHS = ("/admin", "/static", "/robots.txt", "/sitemap.xml", "/lang")


def lang_prefix(request: Request) -> str:
    """«/kk» для казахской версии, пустая строка для русской."""
    return request.scope.get("lang_prefix", "")


def request_lang(request: Request) -> str:
    """Язык страницы. Решает только адрес."""
    return "kk" if lang_prefix(request) else DEFAULT_LANGUAGE


def local_path(request: Request, path: str) -> str:
    """Внутренний адрес в текущей языковой версии.

    На казахской странице все ссылки должны вести на казахские страницы,
    иначе посетитель вываливается в русскую версию с первого же перехода.
    """
    prefix = lang_prefix(request)
    if not prefix:
        return path
    return f"{prefix}/" if path == "/" else prefix + path


def local_redirect(request: Request, path: str) -> RedirectResponse:
    return RedirectResponse(local_path(request, path), status_code=REDIRECT)


def language_urls(path: str) -> dict:
    """Адреса этой же страницы на обоих языках - для canonical и hreflang.

    На вход идёт адрес без префикса, тот, что видит маршрут.
    """
    kk = f"{KK_PREFIX}/" if path == "/" else KK_PREFIX + path
    return {"ru": SITE_URL + path, "kk": SITE_URL + kk}


def language_links(request: Request) -> dict:
    """Куда ведёт переключатель языка: та же страница в другой версии.

    Параметры фильтров сохраняем - человек переключает язык, а не сбрасывает
    поиск.
    """
    path = request.url.path
    query = f"?{request.url.query}" if request.url.query else ""
    kk = f"{KK_PREFIX}/" if path == "/" else KK_PREFIX + path
    return {"ru": path + query, "kk": kk + query}


def render(request: Request, template: str, context: dict) -> HTMLResponse:
    lang = request_lang(request)
    context = {
        **context,
        "lang": lang,
        # Адрес страницы без параметров: для canonical и og:url. Параметры
        # фильтров в них не нужны - это одна и та же страница каталога.
        # canonical указывает сам на себя: русская и казахская версии -
        # разные страницы. Параметры фильтров в адрес не попадают: каталог
        # с фильтрами и без них это одна страница.
        "page_url": SITE_URL + local_path(request, request.url.path),
        # Адреса обеих версий - для тегов hreflang в шапке страницы.
        "alt_urls": language_urls(request.url.path),
        # Внутренняя ссылка в текущей языковой версии.
        "url": lambda path: local_path(request, path),
        # Куда ведёт переключатель языка.
        "lang_links": language_links(request),
        # Функция перевода привязана к языку запроса и поэтому не может
        # быть глобальной: у каждого посетителя свой язык.
        "t": lambda text: translate(text, lang),
        # Название и описание метода лежат в базе двумя парами колонок,
        # поэтому берутся не из словаря переводов, а из самой записи.
        "method_text": lambda row, field="name": localized_field(row, field, lang),
        # Города берутся из справочника, у них тоже пара колонок name/name_kk.
        "city_text": lambda row: localized_field(row, "name", lang),
        "LANGUAGES": LANGUAGES,
    }
    # Уведомление о тестовом режиме показывается только посетителям: в
    # админке оно ни к чему. На странице «Для специалистов» остаётся одна
    # полоса, без окна, - там форма, и закрывать её нечем нельзя.
    public = not request.url.path.startswith("/admin")
    context["notice_strip"] = TEST_NOTICE and public
    context["notice_modal"] = (
        context["notice_strip"] and request.url.path != "/dlya-specialistov"
    )
    return templates.TemplateResponse(request, template, context)


@app.get("/lang/{code}")
def set_language(request: Request, code: str, next: str = "/"):
    """Старый переключатель языка. Остался ради ссылок, которые уже где-то
    сохранены: теперь он просто отправляет на нужную версию адреса.

    Адрес возврата принимаем только свой: «//чужой-сайт» - это тоже
    относительный на вид адрес, но уводит он наружу.
    """
    if not is_supported(code):
        raise HTTPException(status_code=404, detail="Неизвестный язык")
    back = next if next.startswith("/") and not next.startswith("//") else "/"
    if back.startswith(KK_PREFIX + "/") or back == KK_PREFIX:
        back = back[len(KK_PREFIX):] or "/"
    if code != DEFAULT_LANGUAGE:
        back = f"{KK_PREFIX}/" if back == "/" else KK_PREFIX + back
    return RedirectResponse(back, status_code=301)


# --- Публичная часть --------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    city: str = "",
    provider_type: str = "",
    method: str = "",
    specialty: str = "",
    age: str = "",
    proven_only: str = "",
):
    # Пустое значение любого фильтра означает «показать все результаты».
    age_range = AGE_RANGE_BOUNDS.get(age)
    filters = {
        "q": q.strip(),
        "city": city,
        "provider_type": provider_type,
        "method": method,
        "specialty": specialty,
        "age_range": age_range,
        "proven_only": bool(proven_only),
    }
    with db_session() as conn:
        providers = crud.search_providers(conn, filters)
        methods_map = {
            pid: offered_methods(rows)
            for pid, rows in crud.methods_for_providers(
                conn, [p["id"] for p in providers]
            ).items()
        }
        context = {
            "providers": providers,
            "methods_map": methods_map,
            # В фильтре весь справочник, кроме методов без доказательств:
            # искать место занятий по ним незачем, а прочитать о них можно
            # на странице «Методы помощи».
            "filter_methods": offered_methods(crud.list_methods(conn)),
            "age_ranges": AGE_RANGES,
            "cities": crud.cities(conn),
            "specialties": crud.specialties_in_use(conn),
            "filters": filters,
            "raw": {
                "q": q,
                "city": city,
                "provider_type": provider_type,
                "method": method,
                "specialty": specialty,
                "age": age if age_range else "",
                "proven_only": bool(proven_only),
            },
        }
    return render(request, "index.html", context)


@app.get("/providers/{provider_id}", response_class=HTMLResponse)
def provider_detail(request: Request, provider_id: int, review: str = ""):
    with db_session() as conn:
        provider = crud.get_provider(conn, provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        context = {
            "provider": provider,
            "methods": offered_methods(
                crud.methods_for_providers(conn, [provider_id])[provider_id]
            ),
            "reviews": crud.published_reviews(conn, provider_id),
            "review_status": review,
        }
    return render(request, "provider.html", context)


@app.post("/providers/{provider_id}/reviews")
def add_review(
    request: Request,
    provider_id: int,
    author_name: str = Form(""),
    rating: str = Form(""),
    text: str = Form(""),
    consent: str = Form(""),
):
    author_name = author_name.strip()
    text = text.strip()
    rating_value = parse_int(rating)
    ip_hash = request_ip_hash(request)

    if not author_name or not text or rating_value not in (1, 2, 3, 4, 5):
        return RedirectResponse(
            f"/providers/{provider_id}?review=invalid#reviews", status_code=REDIRECT
        )
    if not consent:
        # Без согласия отзыв не сохраняется - ни текст, ни имя автора.
        return RedirectResponse(
            f"/providers/{provider_id}?review=consent#reviews", status_code=REDIRECT
        )

    with db_session() as conn:
        if crud.get_provider(conn, provider_id) is None:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        if crud.has_recent_review_from_ip(conn, provider_id, ip_hash):
            return RedirectResponse(
                f"/providers/{provider_id}?review=limit#reviews", status_code=REDIRECT
            )
        review_id = crud.create_review(
            conn,
            {
                "provider_id": provider_id,
                "author_name": author_name[:80],
                "rating": rating_value,
                "text": text[:2000],
                "author_ip_hash": ip_hash,
            },
        )
        crud.create_consent(conn, consent_data("review", review_id, request))
    return local_redirect(request, f"/providers/{provider_id}?review=ok#reviews")


@app.get("/methods", response_class=HTMLResponse)
def methods_page(request: Request):
    with db_session() as conn:
        methods = crud.list_methods(conn)
    grouped = {
        level: [m for m in methods if m["evidence_level"] == level]
        for level in EVIDENCE_LEVELS
    }
    return render(request, "methods.html", {"grouped": grouped})


@app.get("/early-signs", response_class=HTMLResponse)
def early_signs(request: Request):
    """Ранние признаки: список наблюдений, без форм и без подсчётов."""
    return render(request, "early_signs.html", {})


@app.get("/free-help", response_class=HTMLResponse)
def free_help(request: Request):
    return render(request, "free_help.html", {})


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return render(request, "privacy.html", {})


# --- Обращения по персональным данным ---------------------------------------

def clean_request(form: dict) -> tuple[dict, list[str]]:
    """Разбор формы обращения. Обязательны имя, контакт и суть обращения:
    без контакта ответить некуда, без сути непонятно, что человек просит."""
    errors: list[str] = []

    name = form.get("name", "").strip()
    if not name:
        errors.append("Укажите, как к вам обращаться.")

    contact = form.get("contact", "").strip()
    if not contact:
        errors.append("Укажите телефон или электронную почту для ответа.")

    message = form.get("message", "").strip()
    if not message:
        errors.append("Опишите, что нужно сделать с вашими данными.")

    data = {
        "name": name[:120],
        "contact": contact[:160],
        "message": message[:2000],
    }
    return data, errors


@app.get("/privacy/request", response_class=HTMLResponse)
def privacy_request_form(request: Request):
    return render(request, "privacy_request.html", {"form": {}, "errors": []})


@app.post("/privacy/request", response_class=HTMLResponse)
async def privacy_request_create(request: Request):
    form = {key: str(value) for key, value in (await request.form()).items()}
    ip_hash = request_ip_hash(request)

    # Та же ловушка для ботов, что и в заявке на размещение.
    if form.get("company_site", "").strip():
        return local_redirect(request, "/privacy/request/sent")

    data, errors = clean_request(form)
    with db_session() as conn:
        if not errors and (
            crud.requests_from_ip_last_hour(conn, ip_hash) >= MAX_REQUESTS_PER_HOUR
        ):
            errors.append(
                "С одного устройства принимаем не больше трёх обращений в час."
                " Попробуйте позже."
            )
        if errors:
            return render(
                request, "privacy_request.html", {"form": form, "errors": errors}
            )
        data["author_ip_hash"] = ip_hash
        crud.create_request(conn, data)
    return local_redirect(request, "/privacy/request/sent")


@app.get("/privacy/request/sent", response_class=HTMLResponse)
def privacy_request_sent(request: Request):
    return render(request, "privacy_request_sent.html", {})


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    """Тестовый стенд закрыт от поисковиков той же переменной, что и
    мета-тег noindex: включили NOINDEX=1 - закрыт и файл, и страницы.
    Карту сайта показываем только открытому сайту: закрытому она ни к чему."""
    if NOINDEX:
        return "User-agent: *\nDisallow: /\n"
    # Админка закрыта и так - без пароля туда не войти, - но и звать в неё
    # робота незачем: он будет ходить по страницам входа и ничего не найдёт.
    return (
        "User-agent: *\n"
        "Disallow: /admin\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )


# Страницы, которые есть всегда и не зависят от содержимого базы.
# «Помощь бесплатно» в карту не входит: страница пустая, и звать на неё
# поисковик - значит самим показать ему пустышку. Вернуть, когда наполнится.
SITEMAP_PAGES = (
    "/",
    "/methods",
    "/early-signs",
    "/dlya-specialistov",
    "/privacy",
)


@app.get("/sitemap.xml")
def sitemap() -> Response:
    """Карта сайта: постоянные страницы и карточки мест занятий.

    Тестовые записи в карту не попадают - в поиске им делать нечего.
    Закрытый от поисковиков сайт отдаёт пустую карту: так ответ остаётся
    валидным XML, а приглашать робота на закрытые страницы незачем.
    """
    paths = []
    if not NOINDEX:
        paths = list(SITEMAP_PAGES)
        with db_session() as conn:
            # Карточки берём из базы на каждый запрос: завели новое место -
            # оно появилось в карте само, без правки кода.
            paths += [
                f"/providers/{row['id']}"
                for row in crud.list_providers_admin(conn)
                if not row["is_test"]
            ]

    body = []
    for path in paths:
        alt = language_urls(path)
        # У каждой страницы два адреса - по одному на язык, - и в каждой
        # записи перечислены оба. Так положено: ссылки должны быть взаимными,
        # иначе поисковик связку не признает.
        links = "".join(
            f'<xhtml:link rel="alternate" hreflang="{code}" href="{escape(url)}"/>'
            for code, url in (("ru", alt["ru"]), ("kk", alt["kk"]))
        )
        links += (
            '<xhtml:link rel="alternate" hreflang="x-default"'
            f' href="{escape(alt["ru"])}"/>'
        )
        for url in (alt["ru"], alt["kk"]):
            body.append(f"<url><loc>{escape(url)}</loc>{links}</url>")

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        ' xmlns:xhtml="http://www.w3.org/1999/xhtml">'
        f'{"".join(body)}</urlset>'
    )
    return Response(content=xml, media_type="application/xml")


# --- Заявки на размещение ---------------------------------------------------

def application_form_context(conn, form: dict, errors: list[str]) -> dict:
    return {
        "methods": offered_methods(crud.list_methods(conn)),
        "form": form,
        "errors": errors,
        "selected_methods": set(form.get("methods", [])),
    }


def clean_application(form: dict, known_codes: set[str]) -> tuple[dict, list[str]]:
    """Разбор и проверка формы заявки. Возвращает данные и список ошибок."""
    errors: list[str] = []
    kind = form.get("applicant_kind", "")
    if kind not in APPLICANT_KINDS:
        errors.append(
            "Выберите, кто вы: организация, частный специалист"
            " или медицинский работник."
        )
        kind = ""

    name = form.get("org_name" if kind == "organization" else "person_name", "").strip()
    if kind and not name:
        errors.append(
            "Укажите название организации."
            if kind == "organization"
            else "Укажите фамилию, имя и отчество."
        )
    if len(name) > 160:
        errors.append("Название или ФИО не длиннее 160 символов.")

    city = city_from_form(form)
    if not city:
        errors.append("Укажите город.")
    if len(city) > 80:
        errors.append("Название города не длиннее 80 символов.")

    contact_person = form.get("contact_person", "").strip()
    if not contact_person:
        errors.append("Укажите контактное лицо.")
    if len(contact_person) > 120:
        errors.append("Имя контактного лица не длиннее 120 символов.")

    phone = normalize_phone(form.get("phone", ""))
    if phone is None:
        errors.append("Введите 10 цифр номера после +7.")

    whatsapp_raw = form.get("whatsapp", "").strip()
    whatsapp = normalize_phone(whatsapp_raw) if whatsapp_raw else ""
    if whatsapp_raw and whatsapp is None:
        errors.append("В WhatsApp введите 10 цифр номера после +7 или оставьте поле пустым.")
        whatsapp = ""

    email = form.get("email", "").strip()
    if email and not looks_like_email(email):
        errors.append("Проверьте адрес электронной почты.")
    if len(email) > 120:
        errors.append("Адрес почты не длиннее 120 символов.")

    comment = form.get("comment", "").strip()
    if len(comment) > 2000:
        errors.append("Комментарий не длиннее 2000 символов.")

    if not form.get("consent"):
        errors.append("Без согласия на обработку персональных данных заявку принять нельзя.")

    age_from = parse_int(form.get("age_from", ""))
    age_to = parse_int(form.get("age_to", ""))
    if age_from is not None and age_to is not None and age_from > age_to:
        errors.append("Возраст «от» больше, чем «до».")

    pricing = "free" if form.get("pricing_free") else "paid"
    price_from = None if pricing == "free" else parse_int(form.get("price_from", ""))
    price_to = None if pricing == "free" else parse_int(form.get("price_to", ""))
    if price_from is not None and price_to is not None and price_from > price_to:
        errors.append("Стоимость «от» больше, чем «до».")

    # Врач ведёт приём и диагностику, а не занятия по методикам: блок
    # методов ему не показывается, и присланные коды не принимаем.
    codes = (
        []
        if kind == "doctor"
        else [code for code in form.get("methods", []) if code in known_codes]
    )

    data = {
        "applicant_kind": kind,
        "name": name[:160],
        "provider_type": (
            form.get("provider_type", "") if kind == "organization" else ""
        ),
        "specialty": specialty_from_form(form, kind),
        "city": city[:80],
        "address": form.get("address", "").strip()[:200],
        "method_codes": json.dumps(codes, ensure_ascii=False),
        "age_from": age_from,
        "age_to": age_to,
        "price_from": price_from,
        "price_to": price_to,
        "pricing": pricing,
        "link": form.get("link", "").strip()[:200],
        "contact_person": contact_person[:120],
        "phone": phone or "",
        "whatsapp": whatsapp or "",
        "email": email[:120],
        "comment": comment[:2000],
    }
    if data["provider_type"] and data["provider_type"] not in ORGANIZATION_TYPES:
        data["provider_type"] = ""
    if data["specialty"] and data["specialty"] not in SPECIALTIES:
        data["specialty"] = ""
    return data, errors


@app.get("/dlya-specialistov", response_class=HTMLResponse)
def application_form(request: Request):
    with db_session() as conn:
        context = application_form_context(conn, {"applicant_kind": ""}, [])
    return render(request, "application_form.html", context)


@app.post("/dlya-specialistov", response_class=HTMLResponse)
async def application_create(request: Request):
    raw = await request.form()
    form = {
        key: str(value)
        for key, value in raw.items()
        if key not in ("methods", "logo")
    }
    form["methods"] = raw.getlist("methods")
    ip_hash = request_ip_hash(request)

    # Honeypot: поле спрятано от людей, его заполняют только боты.
    if form.get("company_site", "").strip():
        return local_redirect(request, "/dlya-specialistov/sent")

    upload = raw.get("logo")
    sent_file = upload is not None and getattr(upload, "filename", "")
    # Картинку проверяем сразу, а записываем на диск только если заявку
    # приняли: иначе каждая неудачная отправка оставляла бы мусорный файл.
    image = await read_image(upload)

    with db_session() as conn:
        known_codes = {row["code"] for row in offered_methods(crud.list_methods(conn))}
        data, errors = clean_application(form, known_codes)
        if sent_file and image is None:
            errors.append(
                "Фото не принято: нужен PNG, JPEG, WebP или GIF размером до 2 МБ."
            )
        if not errors and (
            crud.applications_from_ip_last_hour(conn, ip_hash)
            >= MAX_APPLICATIONS_PER_HOUR
        ):
            errors.append(
                "С одного устройства принимаем не больше трёх заявок в час."
                " Попробуйте позже или напишите нам другим способом."
            )
        if errors:
            context = application_form_context(conn, form, errors)
            return render(request, "application_form.html", context)

        data["logo_path"] = store_image(*image) if image else ""
        data["author_ip_hash"] = ip_hash
        application_id = crud.create_application(conn, data)
        crud.create_consent(conn, consent_data("application", application_id, request))
        application = crud.get_application(conn, application_id)

    try:
        notify_new_application(application)
    except Exception:
        # Оповещение не должно мешать приёму заявки.
        pass

    return local_redirect(request, "/dlya-specialistov/sent")


@app.get("/dlya-specialistov/sent", response_class=HTMLResponse)
def application_sent(request: Request):
    return render(request, "application_sent.html", {})


# --- Админка ----------------------------------------------------------------

def require_admin(request: Request) -> RedirectResponse | None:
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=REDIRECT)
    return None


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_form(request: Request, error: str = ""):
    client_ip = request_ip(request)
    seconds_left = login_block_seconds_left(client_ip)
    minutes_left = (seconds_left + 59) // 60
    return render(
        request,
        "admin/login.html",
        {
            "error": error,
            "blocked": seconds_left > 0,
            "minutes_left": minutes_left,
            "minutes_word": minutes_word(minutes_left),
            "max_attempts": LOGIN_MAX_ATTEMPTS,
        },
    )


@app.post("/admin/login")
def admin_login(request: Request, login: str = Form(""), password: str = Form("")):
    if not ADMIN_ENABLED:
        # Без заданных ADMIN_LOGIN и ADMIN_PASSWORD входить некуда.
        return RedirectResponse("/admin/login", status_code=REDIRECT)

    client_ip = request_ip(request)
    if login_block_seconds_left(client_ip):
        return RedirectResponse("/admin/login", status_code=REDIRECT)

    login_ok = secrets.compare_digest(login.strip(), ADMIN_LOGIN)
    password_ok = secrets.compare_digest(password, ADMIN_PASSWORD)
    if login_ok and password_ok:
        forget_login_failures(client_ip)
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=REDIRECT)

    register_login_failure(client_ip)
    return RedirectResponse("/admin/login?error=1", status_code=REDIRECT)


@app.get("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=REDIRECT)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        context = {
            "providers": crud.list_providers_admin(conn),
            "methods_count": len(crud.list_methods(conn)),
            "new_applications": crud.list_applications(conn, "new", limit=5),
            "pending_reviews": crud.pending_reviews(conn, 5),
            "new_requests": crud.list_requests(conn, "new", limit=5),
        }
    return render(request, "admin/providers.html", context)


# --- График посещений -------------------------------------------------------

MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн",
                "июл", "авг", "сен", "окт", "ноя", "дек")
MONTHS_FULL = ("января", "февраля", "марта", "апреля", "мая", "июня",
               "июля", "августа", "сентября", "октября", "ноября", "декабря")

# За какие сроки можно посмотреть график.
VISIT_PERIODS = (7, 30, 90)

# Размеры картинки. Она тянется по ширине страницы, но считается в этих
# числах: так столбики остаются одинаковой толщины и не плывут.
CHART_WIDTH = 720
CHART_TOP = 16
CHART_PLOT = 130
CHART_BASE = CHART_TOP + CHART_PLOT
# Под столбиками - строка с числами месяца, слева - полоса под подписи шкалы.
# На телефоне картинка сжимается, а шрифт в ней задаётся крупнее, поэтому
# места заложено с запасом: иначе «100» обрезается, а дни налезают на столбики.
CHART_LABEL_Y = CHART_BASE + 20
CHART_HEIGHT = CHART_BASE + 34
CHART_GUTTER = 60
# Поле справа: подпись последнего дня стоит по центру столбика и выступает
# за его край, иначе у неё срезается хвост.
CHART_RIGHT = 28
CHART_GAP = 2


def plural_views(count: int) -> str:
    """«1 открытие», «2 открытия», «5 открытий»."""
    if 11 <= count % 100 <= 14:
        return "открытий"
    tail = count % 10
    if tail == 1:
        return "открытие"
    if tail in (2, 3, 4):
        return "открытия"
    return "открытий"


def day_parts(day: str) -> tuple[int, int]:
    """«2026-10-04» -> (4, 9): число и номер месяца с нуля."""
    _, month, number = day.split("-")
    return int(number), int(month) - 1


def nice_ceiling(value: int) -> int:
    """Круглая величина сверху для шкалы: 34 -> 50, 7 -> 10, 0 -> 5.

    Без этого верхняя подпись шкалы была бы вроде «34», и глазу не на что
    опереться при сравнении соседних дней.
    """
    if value <= 5:
        return 5
    step = 10 ** (len(str(value)) - 1)
    for factor in (1, 2, 5):
        if value <= step * factor:
            return step * factor
    return step * 10


def visits_chart(series: list[dict]) -> dict:
    """Готовая геометрия столбчатого графика: считать её в шаблоне неудобно.

    Один ряд данных - один цвет у всех столбиков: высота уже говорит о
    величине, красить её вторично незачем. Подписаны не все дни, а самый
    высокий и последний: число у каждого столбика превращает график в кашу,
    а точные числа и так есть в таблице под ним.
    """
    count = len(series)
    top = nice_ceiling(max((point["views"] for point in series), default=0))
    bar_width = (CHART_WIDTH - CHART_GAP * (count - 1)) / count
    step = max(1, count // 6)

    bars = []
    for index, point in enumerate(series):
        height = point["views"] / top * CHART_PLOT
        number, month = day_parts(point["day"])
        bars.append({
            "x": round(index * (bar_width + CHART_GAP), 2),
            "width": round(bar_width, 2),
            "y": round(CHART_BASE - height, 2),
            "height": round(height, 2),
            "radius": round(min(3, bar_width / 2), 2),
            "views": point["views"],
            "middle": round(index * (bar_width + CHART_GAP) + bar_width / 2, 2),
            "label": f"{number} {MONTHS_SHORT[month]}",
            "show_label": index % step == 0 or index == count - 1,
            "title": (
                f"{number} {MONTHS_FULL[month]} - "
                f"{point['views']} {plural_views(point['views'])}"
            ),
        })

    # Подписываем самый высокий день и последний. Если это один и тот же
    # столбик, подпись остаётся одна.
    best = max(range(count), key=lambda i: series[i]["views"])
    marked = {best, count - 1}
    for index in marked:
        if bars[index]["views"]:
            bars[index]["value_label"] = True

    return {
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
        "base": CHART_BASE,
        "label_y": CHART_LABEL_Y,
        "gutter": CHART_GUTTER,
        "right": CHART_RIGHT,
        "top": top,
        "bars": bars,
        "lines": [
            {"y": round(CHART_BASE - part * CHART_PLOT, 2), "value": round(top * part)}
            for part in (0, 0.5, 1)
        ],
    }


@app.get("/admin/stats", response_class=HTMLResponse)
def admin_stats(request: Request, days: int = 30):
    """Числа по каталогу, заявкам, отзывам и обращениям.

    Страница закрытая: на ней видно, сколько обращений просрочено и сколько
    отзывов ждёт проверки, а это внутренняя кухня. Персональных данных здесь
    нет - только счётчики, ни одного имени и ни одного телефона.
    """
    if guard := require_admin(request):
        return guard
    if days not in VISIT_PERIODS:
        days = 30
    with db_session() as conn:
        visits = crud.visit_series(conn, days)
        by_type = crud.provider_counts_by(conn, "provider_type")
        by_city = crud.provider_counts_by(conn, "city")
        methods = crud.provider_counts_by_method(conn)
        applications = crud.counts_by_status(conn, "applications")
        reviews = crud.counts_by_status(conn, "reviews")
        requests = crud.counts_by_status(conn, "requests")
        ratings = crud.review_ratings(conn)
        context = {
            "providers_total": sum(row["n"] for row in by_type),
            "providers_test": crud.test_providers_count(conn),
            "providers_without_methods": crud.providers_without_methods(conn),
            "by_type": by_type,
            "by_city": by_city,
            "methods": methods,
            "applications": applications,
            "applications_total": sum(applications.values()),
            "applications_month": crud.created_since(conn, "applications", 30),
            "reviews": reviews,
            "reviews_total": sum(reviews.values()),
            "reviews_month": crud.created_since(conn, "reviews", 30),
            "rating_avg": crud.average_published_rating(conn),
            "ratings": ratings,
            "requests": requests,
            "requests_total": sum(requests.values()),
            "requests_overdue": crud.requests_waiting_longer_than(
                conn, REQUEST_ANSWER_DAYS
            ),
        }
    views = [point["views"] for point in visits]
    context["visits"] = list(reversed(visits))
    context["visits_days"] = days
    context["visits_periods"] = VISIT_PERIODS
    context["visits_total"] = sum(views)
    context["visits_per_day"] = round(sum(views) / days, 1)
    context["visits_chart"] = visits_chart(visits)
    # Длина полосок считается от самого большого значения в своей таблице:
    # иначе короткие ряды выглядят одинаково, а длинные упираются в край.
    context["max_type"] = max((row["n"] for row in by_type), default=0)
    context["max_city"] = max((row["n"] for row in by_city), default=0)
    context["max_method"] = max((row["n"] for row in methods), default=0)
    context["max_rating"] = max(ratings.values(), default=0)
    return render(request, "admin/stats.html", context)


# Сроки, за которые можно смотреть посетителей. Дольше журнала не бывает:
# записи старше VISIT_LOG_DAYS удаляются.
VISITOR_PERIODS = ((1, "Сегодня"), (7, "7 дней"), (30, "30 дней"))


@app.get("/admin/visitors", response_class=HTMLResponse)
def admin_visitors(request: Request, days: int = 7, ip: str = ""):
    """Уникальные посетители за период, по адресам.

    Здесь видны персональные данные, поэтому страница закрытая, как и вся
    админка. Записи старше срока хранения сюда не попадают - их уже нет.
    """
    if guard := require_admin(request):
        return guard
    if days not in {period for period, _ in VISITOR_PERIODS}:
        days = 7
    with db_session() as conn:
        context = {
            "days": days,
            "periods": VISITOR_PERIODS,
            "retention_days": crud.VISIT_LOG_DAYS,
            "gap_minutes": crud.VISIT_GAP_MINUTES,
            "ip": ip,
            "unique_count": crud.visitors_count(conn, days),
        }
        if ip:
            context["pages"] = crud.visitor_pages(conn, ip, days)
        else:
            rows = crud.visitors(conn, days)
            context["rows"] = rows
            context["views_total"] = sum(int(row["views"]) for row in rows)
            context["visits_total"] = sum(int(row["visits"]) for row in rows)
    return render(request, "admin/visitors.html", context)


def application_methods(conn, application) -> list:
    """Методы заявки: в базе они лежат списком кодов."""
    try:
        codes = json.loads(application["method_codes"] or "[]")
    except ValueError:
        codes = []
    by_code = {row["code"]: row for row in crud.list_methods(conn)}
    return [by_code[code] for code in codes if code in by_code]


def provider_prefill(conn, application) -> tuple[dict, set[int]]:
    """Заготовка карточки по заявке. Сама карточка создаётся только после
    того, как администратор нажмёт «Сохранить» в форме."""
    kind = application["applicant_kind"]
    data = {
        # Отдельного места занятий «врач» в справочнике нет - и не было:
        # код doctor когда-то убрали, а записи перенесли в specialist.
        # Врач из анкеты попадает туда же, а что он врач, видно по его
        # специальности и по самой заявке.
        "provider_type": application["provider_type"] or (
            "specialist" if kind in ("specialist", "doctor") else "center"
        ),
        "name": application["name"],
        "specialty": application["specialty"],
        "city": application["city"],
        "district": "",
        "address": application["address"],
        "phone": application["phone"],
        "whatsapp": application["whatsapp"],
        "website": application["link"],
        "instagram": "",
        "age_from": application["age_from"],
        "age_to": application["age_to"],
        "price_from": application["price_from"],
        "price_to": application["price_to"],
        "pricing": application["pricing"],
        "has_state_funding": 0,
        "description": application["comment"],
        "logo_path": application["logo_path"],
        "is_test": 0,
    }
    method_ids = {row["id"] for row in application_methods(conn, application)}
    return data, method_ids


def provider_form_data(
    form, method_codes: list[str], logo_path: str
) -> tuple[dict, list[int]]:
    data = {
        "provider_type": form["provider_type"],
        "name": form["name"].strip(),
        "specialty": form["specialty"].strip(),
        "city": city_from_form(form),
        "district": form["district"].strip(),
        "address": form["address"].strip(),
        "phone": normalize_phone_or_raw(form["phone"]),
        "whatsapp": normalize_phone_or_raw(form["whatsapp"]),
        "website": form["website"].strip(),
        "instagram": form["instagram"].strip(),
        "age_from": parse_int(form["age_from"]),
        "age_to": parse_int(form["age_to"]),
        "price_from": parse_int(form["price_from"]),
        "price_to": parse_int(form["price_to"]),
        "pricing": form["pricing"] if form["pricing"] in PRICING else "paid",
        "has_state_funding": 1 if form["has_state_funding"] else 0,
        "description": form["description"].strip(),
        "logo_path": logo_path,
        "is_test": 1 if form["is_test"] else 0,
    }
    method_ids = [int(code) for code in method_codes if code.isdigit()]
    return data, method_ids


@app.get("/admin/providers/new", response_class=HTMLResponse)
def admin_provider_new(request: Request, from_application: str = ""):
    if guard := require_admin(request):
        return guard
    application_id = parse_int(from_application)
    prefill: dict | None = None
    selected: set[int] = set()
    with db_session() as conn:
        methods = crud.list_methods(conn)
        if application_id is not None:
            application = crud.get_application(conn, application_id)
            if application is None:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            prefill, selected = provider_prefill(conn, application)
    return render(
        request,
        "admin/provider_form.html",
        {
            "provider": None,
            "prefill": prefill,
            "from_application": application_id,
            "methods": methods,
            "selected_methods": selected,
            "title": "Новое место занятий",
        },
    )


@app.post("/admin/providers/new")
async def admin_provider_create(request: Request):
    if guard := require_admin(request):
        return guard
    form = await request.form()
    application_id = parse_int(form.get("from_application", ""))

    # Карточка по заявке наследует присланное фото, пока администратор
    # не выберет в форме другой файл.
    base_logo = ""
    if application_id is not None:
        with db_session() as conn:
            application = crud.get_application(conn, application_id)
        base_logo = application["logo_path"] if application else ""

    logo_path = await save_logo(form.get("logo"), base_logo)
    data, method_ids = provider_form_data(
        _form_defaults(form), form.getlist("methods"), logo_path
    )
    if not data["name"] or not data["city"]:
        back = "/admin/providers/new?error=1"
        if application_id is not None:
            back += f"&from_application={application_id}"
        return RedirectResponse(back, status_code=REDIRECT)
    with db_session() as conn:
        provider_id = crud.create_provider(conn, data, method_ids)
        if application_id is not None and crud.get_application(conn, application_id):
            crud.link_application_to_provider(conn, application_id, provider_id)
            return RedirectResponse(
                f"/admin/applications/{application_id}?saved=1", status_code=REDIRECT
            )
    return RedirectResponse("/admin", status_code=REDIRECT)


@app.get("/admin/providers/{provider_id}/edit", response_class=HTMLResponse)
def admin_provider_edit(request: Request, provider_id: int):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        provider = crud.get_provider(conn, provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        context = {
            "provider": provider,
            "methods": crud.list_methods(conn),
            "prefill": None,
            "from_application": None,
            "selected_methods": crud.provider_method_ids(conn, provider_id),
            "title": "Редактирование места занятий",
        }
    return render(request, "admin/provider_form.html", context)


@app.post("/admin/providers/{provider_id}/edit")
async def admin_provider_update(request: Request, provider_id: int):
    if guard := require_admin(request):
        return guard
    form = await request.form()
    with db_session() as conn:
        existing = crud.get_provider(conn, provider_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    logo_path = (
        "" if form.get("remove_logo")
        else await save_logo(form.get("logo"), existing["logo_path"] or "")
    )
    data, method_ids = provider_form_data(
        _form_defaults(form), form.getlist("methods"), logo_path
    )
    if not data["name"] or not data["city"]:
        return RedirectResponse(
            f"/admin/providers/{provider_id}/edit?error=1", status_code=REDIRECT
        )
    with db_session() as conn:
        crud.update_provider(conn, provider_id, data, method_ids)
    return RedirectResponse("/admin", status_code=REDIRECT)


@app.post("/admin/providers/{provider_id}/delete")
def admin_provider_delete(request: Request, provider_id: int):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        crud.delete_provider(conn, provider_id)
    return RedirectResponse("/admin", status_code=REDIRECT)


@app.get("/admin/applications", response_class=HTMLResponse)
def admin_applications(request: Request):
    if guard := require_admin(request):
        return guard
    status = request.query_params.get("status", "")
    if status not in APPLICATION_STATUSES:
        status = ""
    with db_session() as conn:
        context = {
            "applications": crud.list_applications(conn, status),
            "status": status,
        }
    return render(request, "admin/applications.html", context)


@app.get("/admin/applications/{application_id}", response_class=HTMLResponse)
def admin_application_detail(request: Request, application_id: int):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        application = crud.get_application(conn, application_id)
        if application is None:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        context = {
            "application": application,
            "methods": application_methods(conn, application),
            "consent": crud.get_consent(conn, "application", application_id),
            "actions": crud.data_actions_for(conn, "application", application_id),
            "markers": health_markers(
                application["name"], application["comment"], application["address"]
            ),
        }
    return render(request, "admin/application.html", context)


@app.post("/admin/applications/{application_id}")
async def admin_application_update(request: Request, application_id: int):
    if guard := require_admin(request):
        return guard
    form = _form_defaults(await request.form())
    status = form["status"]
    if status not in APPLICATION_STATUSES:
        status = "new"
    with db_session() as conn:
        if crud.get_application(conn, application_id) is None:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        crud.update_application(
            conn, application_id, status, form["admin_note"].strip()[:2000]
        )
    return RedirectResponse(
        f"/admin/applications/{application_id}?saved=1", status_code=REDIRECT
    )


def unused_upload(conn, logo_path: str) -> bool:
    """Файл можно стирать, только если на него не ссылается карточка
    каталога: карточка по заявке наследует то же самое фото."""
    if not logo_path.startswith("/static/uploads/"):
        return False
    row = conn.execute(
        "SELECT 1 FROM providers WHERE logo_path = ? LIMIT 1", (logo_path,)
    ).fetchone()
    return row is None


def remove_upload(logo_path: str) -> None:
    name = logo_path.rsplit("/", 1)[-1]
    if name:
        (UPLOAD_DIR / name).unlink(missing_ok=True)


@app.post("/admin/data/{subject_type}/{record_id}/{action}")
async def admin_personal_data_action(
    request: Request, subject_type: str, record_id: int, action: str
):
    """Удаление и обезличивание - одним обработчиком для заявок и отзывов:
    правила у них общие, различия спрятаны внутри crud."""
    if guard := require_admin(request):
        return guard
    if subject_type not in SUBJECT_TYPES or action not in ("delete", "anonymize"):
        raise HTTPException(status_code=404, detail="Неизвестное действие")

    form = _form_defaults(await request.form())
    reason = form["reason"].strip()
    back = form["next"] if form["next"].startswith("/admin") else "/admin"

    with db_session() as conn:
        logo_path = ""
        if subject_type == "application":
            application = crud.get_application(conn, record_id)
            if application is None:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            logo_path = application["logo_path"] or ""
        elif crud.get_review(conn, record_id) is None:
            raise HTTPException(status_code=404, detail="Отзыв не найден")

        if action == "delete":
            crud.delete_personal_data(conn, subject_type, record_id, reason)
        else:
            crud.anonymize_personal_data(conn, subject_type, record_id, reason)
        # Присланное фото - тоже персональные данные, и в обоих случаях
        # запись на него больше не ссылается.
        drop_file = bool(logo_path) and unused_upload(conn, logo_path)

    if drop_file:
        remove_upload(logo_path)
    return RedirectResponse(back, status_code=REDIRECT)


@app.post("/admin/applications/{application_id}/delete")
def admin_application_delete(request: Request, application_id: int):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        crud.delete_application(conn, application_id)
    return RedirectResponse("/admin/applications", status_code=REDIRECT)


@app.get("/admin/reviews", response_class=HTMLResponse)
def admin_reviews(request: Request):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        context = {
            "pending": crud.reviews_by_status(conn, "pending"),
            "published": crud.reviews_by_status(conn, "published"),
            "rejected": crud.reviews_by_status(conn, "rejected"),
        }
    return render(request, "admin/reviews.html", context)


@app.get("/admin/reviews/{review_id}", response_class=HTMLResponse)
def admin_review_detail(request: Request, review_id: int):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        review = crud.get_review(conn, review_id)
        if review is None:
            raise HTTPException(status_code=404, detail="Отзыв не найден")
        context = {
            "review": review,
            "consent": crud.get_consent(conn, "review", review_id),
            "actions": crud.data_actions_for(conn, "review", review_id),
            "markers": health_markers(review["author_name"], review["text"]),
        }
    return render(request, "admin/review.html", context)


@app.post("/admin/reviews/{review_id}/{action}")
async def admin_review_action(request: Request, review_id: int, action: str):
    if guard := require_admin(request):
        return guard
    statuses = {"approve": "published", "reject": "rejected"}
    if action not in statuses:
        raise HTTPException(status_code=404, detail="Неизвестное действие")
    form = _form_defaults(await request.form())
    # Отзыв модерируется и со страницы отзывов, и из блока на главной админки.
    back = form["next"] if form["next"].startswith("/admin") else "/admin/reviews"
    with db_session() as conn:
        crud.set_review_status(conn, review_id, statuses[action])
    return RedirectResponse(back, status_code=REDIRECT)


@app.get("/admin/requests", response_class=HTMLResponse)
def admin_requests(request: Request):
    if guard := require_admin(request):
        return guard
    status = request.query_params.get("status", "")
    if status not in REQUEST_STATUSES:
        status = ""
    with db_session() as conn:
        context = {"requests": crud.list_requests(conn, status), "status": status}
    return render(request, "admin/requests.html", context)


@app.get("/admin/requests/{request_id}", response_class=HTMLResponse)
def admin_request_detail(request: Request, request_id: int):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        item = crud.get_request(conn, request_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Обращение не найдено")
        context = {"item": item}
    return render(request, "admin/request.html", context)


@app.post("/admin/requests/{request_id}")
async def admin_request_update(request: Request, request_id: int):
    if guard := require_admin(request):
        return guard
    form = _form_defaults(await request.form())
    status = form["status"] if form["status"] in REQUEST_STATUSES else "new"
    with db_session() as conn:
        if crud.get_request(conn, request_id) is None:
            raise HTTPException(status_code=404, detail="Обращение не найдено")
        crud.update_request(
            conn, request_id, status, form["admin_note"].strip()[:2000]
        )
    return RedirectResponse(
        f"/admin/requests/{request_id}?saved=1", status_code=REDIRECT
    )


@app.post("/admin/requests/{request_id}/delete")
def admin_request_delete(request: Request, request_id: int):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        crud.delete_request(conn, request_id)
    return RedirectResponse("/admin/requests", status_code=REDIRECT)


@app.get("/admin/methods", response_class=HTMLResponse)
def admin_methods(request: Request):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        context = {"methods": crud.list_methods(conn), "method": None}
    return render(request, "admin/methods.html", context)


@app.get("/admin/methods/{method_id}/edit", response_class=HTMLResponse)
def admin_method_edit(request: Request, method_id: int):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        method = crud.get_method(conn, method_id)
        if method is None:
            raise HTTPException(status_code=404, detail="Метод не найден")
        context = {"methods": crud.list_methods(conn), "method": method}
    return render(request, "admin/methods.html", context)


def method_form_data(form) -> dict:
    level = form["evidence_level"]
    return {
        "code": form["code"].strip(),
        "name": form["name"].strip(),
        "description": form["description"].strip(),
        "name_kk": form["name_kk"].strip(),
        "description_kk": form["description_kk"].strip(),
        "evidence_level": level if level in EVIDENCE_LEVELS else "limited",
        "sort_order": parse_int(form["sort_order"]) or 100,
    }


@app.post("/admin/methods/new")
async def admin_method_create(request: Request):
    if guard := require_admin(request):
        return guard
    data = method_form_data(_form_defaults(await request.form()))
    if not data["code"] or not data["name"]:
        return RedirectResponse("/admin/methods?error=1", status_code=REDIRECT)
    with db_session() as conn:
        crud.create_method(conn, data)
    return RedirectResponse("/admin/methods", status_code=REDIRECT)


@app.post("/admin/methods/{method_id}/edit")
async def admin_method_update(request: Request, method_id: int):
    if guard := require_admin(request):
        return guard
    data = method_form_data(_form_defaults(await request.form()))
    if not data["code"] or not data["name"]:
        return RedirectResponse(
            f"/admin/methods/{method_id}/edit?error=1", status_code=REDIRECT
        )
    with db_session() as conn:
        crud.update_method(conn, method_id, data)
    return RedirectResponse("/admin/methods", status_code=REDIRECT)


@app.post("/admin/methods/{method_id}/delete")
def admin_method_delete(request: Request, method_id: int):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        crud.delete_method(conn, method_id)
    return RedirectResponse("/admin/methods", status_code=REDIRECT)


class _FormDefaults(dict):
    def __missing__(self, key):
        return ""


def _form_defaults(form) -> _FormDefaults:
    return _FormDefaults({key: str(value) for key, value in form.items()})
