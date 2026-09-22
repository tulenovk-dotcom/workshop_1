import json
import logging
import os
import re
import secrets
import time
import zlib
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import crud
from .database import DB_PATH, db_session, init_db, read_or_create_secret
from .notifications import notify_new_application
from .i18n import (
    DEFAULT_LANGUAGE,
    LANG_COOKIE,
    LANG_COOKIE_MAX_AGE,
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
    EVIDENCE_LEVELS,
    ORGANIZATION_TYPES,
    PRICING,
    PROVIDER_TYPES,
    REQUEST_ANSWER_DAYS,
    REQUEST_STATUSES,
    SPECIALTIES,
    TYPES_WITH_SPECIALTY,
)
from .seed import seed_if_empty

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
NOINDEX = os.environ.get("NOINDEX") == "1"

MAX_REQUESTS_PER_HOUR = 3


def detect_proxy() -> bool:
    """Стоит ли верить заголовку X-Forwarded-For.

    На хостинге запросы приходят не напрямую, а через балансировщик, и адрес
    подключения у всех посетителей один; настоящий адрес лежит в заголовке.
    Render задаёт переменную RENDER сам, поэтому там доверие включается без
    ручной настройки. Напрямую заголовку верить нельзя: его подделает кто
    угодно и обойдёт все счётчики, поэтому по умолчанию доверия нет.
    TRUST_PROXY_HEADERS перебивает определение в обе стороны.
    """
    manual = os.environ.get("TRUST_PROXY_HEADERS")
    if manual is not None:
        return manual == "1"
    return bool(os.environ.get("RENDER"))


TRUST_PROXY_HEADERS = detect_proxy()

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

app = FastAPI(title="Каталог помощи детям с РАС в Казахстане")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
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
    """Казахстанский номер к виду «+7 707 123 45 67».

    Принимаются записи с +7, 8 и без кода страны. Все номера Казахстана
    после кода страны начинаются с 6 или 7, этим и отсекаются чужие.
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10 and digits[0] in "67":
        digits = "7" + digits
    elif len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) != 11 or digits[0] != "7" or digits[1] not in "67":
        return None
    return f"+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:]}"


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


templates.env.filters["price"] = format_price
templates.env.filters["initials"] = initials
templates.env.filters["hue"] = name_hue
templates.env.filters["wa_link"] = wa_link
templates.env.filters["site_link"] = site_link
templates.env.filters["instagram_link"] = instagram_link
# Контакты в списках показываются замаскированными, поэтому маскирование -
# такой же фильтр шаблона, как и остальное форматирование.
templates.env.filters["mask_phone"] = mask_phone
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
    EVIDENCE_LEVELS=EVIDENCE_LEVELS,
    PRICING=PRICING,
    SPECIALTIES=SPECIALTIES,
    TYPES_WITH_SPECIALTY=TYPES_WITH_SPECIALTY,
    SHOW_TEST_BANNER=SHOW_TEST_BANNER,
    NOINDEX=NOINDEX,
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
    seed_if_empty()
    # Сроки хранения проверяются при запуске: отдельного планировщика в
    # проекте нет, а сервис на хостинге и так перезапускается регулярно.
    with db_session() as conn:
        cleaned = crud.cleanup_personal_data(conn)
    if cleaned:
        log.info("Обезличено записей по истечении срока хранения: %s", cleaned)


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


def request_lang(request: Request) -> str:
    """Язык страницы: из cookie, а если её нет - русский."""
    code = request.cookies.get(LANG_COOKIE, "")
    return code if is_supported(code) else DEFAULT_LANGUAGE


def current_path(request: Request) -> str:
    """Текущий адрес с параметрами - чтобы вернуться на ту же страницу
    после переключения языка."""
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


def render(request: Request, template: str, context: dict) -> HTMLResponse:
    lang = request_lang(request)
    context = {
        **context,
        "lang": lang,
        # Функция перевода привязана к языку запроса и поэтому не может
        # быть глобальной: у каждого посетителя свой язык.
        "t": lambda text: translate(text, lang),
        # Название и описание метода лежат в базе двумя парами колонок,
        # поэтому берутся не из словаря переводов, а из самой записи.
        "method_text": lambda row, field="name": localized_field(row, field, lang),
        "LANGUAGES": LANGUAGES,
        "current_path": current_path(request),
    }
    return templates.TemplateResponse(request, template, context)


@app.get("/lang/{code}")
def set_language(request: Request, code: str, next: str = "/"):
    """Переключение языка: запоминаем выбор и возвращаем на ту же страницу.

    Адрес возврата принимаем только свой: «//чужой-сайт» - это тоже
    относительный на вид адрес, но уводит он наружу.
    """
    if not is_supported(code):
        raise HTTPException(status_code=404, detail="Неизвестный язык")
    back = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(back, status_code=REDIRECT)
    response.set_cookie(
        LANG_COOKIE,
        code,
        max_age=LANG_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


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
        methods_map = crud.methods_for_providers(conn, [p["id"] for p in providers])
        context = {
            "providers": providers,
            "methods_map": methods_map,
            # В фильтре весь справочник, в порядке справочника: раньше список
            # был урезан до семи методов, и остальные было нечем искать.
            "filter_methods": crud.list_methods(conn),
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
            "methods": crud.methods_for_providers(conn, [provider_id])[provider_id],
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
    return RedirectResponse(
        f"/providers/{provider_id}?review=ok#reviews", status_code=REDIRECT
    )


@app.get("/methods", response_class=HTMLResponse)
def methods_page(request: Request):
    with db_session() as conn:
        methods = crud.list_methods(conn)
    grouped = {
        level: [m for m in methods if m["evidence_level"] == level]
        for level in EVIDENCE_LEVELS
    }
    return render(request, "methods.html", {"grouped": grouped})


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
        return RedirectResponse("/privacy/request/sent", status_code=REDIRECT)

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
    return RedirectResponse("/privacy/request/sent", status_code=REDIRECT)


@app.get("/privacy/request/sent", response_class=HTMLResponse)
def privacy_request_sent(request: Request):
    return render(request, "privacy_request_sent.html", {})


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    """Тестовый стенд закрыт от поисковиков той же переменной, что и
    мета-тег noindex: включили NOINDEX=1 - закрыт и файл, и страницы."""
    if NOINDEX:
        return "User-agent: *\nDisallow: /\n"
    return "User-agent: *\nDisallow:\n"


# --- Заявки на размещение ---------------------------------------------------

def application_form_context(conn, form: dict, errors: list[str]) -> dict:
    return {
        "methods": crud.list_methods(conn),
        "form": form,
        "errors": errors,
        "selected_methods": set(form.get("methods", [])),
    }


def clean_application(form: dict, known_codes: set[str]) -> tuple[dict, list[str]]:
    """Разбор и проверка формы заявки. Возвращает данные и список ошибок."""
    errors: list[str] = []
    kind = form.get("applicant_kind", "")
    if kind not in APPLICANT_KINDS:
        errors.append("Выберите, кто вы: организация или частный специалист.")
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

    city = form.get("city", "").strip()
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
        errors.append(
            "Телефон должен быть казахстанским номером, например +7 701 234 56 78."
        )

    whatsapp_raw = form.get("whatsapp", "").strip()
    whatsapp = normalize_phone(whatsapp_raw) if whatsapp_raw else ""
    if whatsapp_raw and whatsapp is None:
        errors.append("WhatsApp должен быть казахстанским номером или остаться пустым.")
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

    codes = [code for code in form.get("methods", []) if code in known_codes]

    data = {
        "applicant_kind": kind,
        "name": name[:160],
        "provider_type": (
            form.get("provider_type", "") if kind == "organization" else ""
        ),
        "specialty": form.get("specialty", "") if kind == "specialist" else "",
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
        return RedirectResponse("/dlya-specialistov/sent", status_code=REDIRECT)

    upload = raw.get("logo")
    sent_file = upload is not None and getattr(upload, "filename", "")
    # Картинку проверяем сразу, а записываем на диск только если заявку
    # приняли: иначе каждая неудачная отправка оставляла бы мусорный файл.
    image = await read_image(upload)

    with db_session() as conn:
        known_codes = {row["code"] for row in crud.list_methods(conn)}
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

    return RedirectResponse("/dlya-specialistov/sent", status_code=REDIRECT)


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
        "provider_type": application["provider_type"] or (
            "specialist" if kind == "specialist" else "center"
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
        "city": form["city"].strip(),
        "district": form["district"].strip(),
        "address": form["address"].strip(),
        "phone": form["phone"].strip(),
        "whatsapp": form["whatsapp"].strip(),
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
