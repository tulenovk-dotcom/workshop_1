import os
import re
import secrets
import zlib
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import crud
from .database import db_session, init_db
from .reference import (
    EVIDENCE_LEVELS,
    PRICING,
    PROVIDER_TYPES,
    SPECIALTIES,
    TYPES_WITH_SPECIALTY,
)
from .seed import seed_if_empty

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
MAX_LOGO_BYTES = 2 * 1024 * 1024
ADMIN_LOGIN = os.environ.get("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
REDIRECT = 303


def load_secret_key() -> str:
    """Ключ хранится между запусками, иначе uvicorn --reload на каждой
    перезагрузке обнуляет сессию администратора."""
    if key := os.environ.get("SECRET_KEY"):
        return key
    key_file = BASE_DIR.parent / ".secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


SECRET_KEY = load_secret_key()

app = FastAPI(title="Каталог помощи детям с РАС в Казахстане")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
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


async def save_logo(upload, current: str) -> str:
    if upload is None or not getattr(upload, "filename", ""):
        return current
    data = await upload.read(MAX_LOGO_BYTES + 1)
    extension = image_extension(data)
    if extension is None or len(data) > MAX_LOGO_BYTES:
        return current
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(8)}{extension}"
    (UPLOAD_DIR / name).write_bytes(data)
    return f"/static/uploads/{name}"


templates.env.filters["price"] = format_price
templates.env.filters["initials"] = initials
templates.env.filters["hue"] = name_hue
templates.env.filters["wa_link"] = wa_link
templates.env.filters["site_link"] = site_link
templates.env.filters["instagram_link"] = instagram_link
templates.env.globals.update(
    PROVIDER_TYPES=PROVIDER_TYPES,
    EVIDENCE_LEVELS=EVIDENCE_LEVELS,
    PRICING=PRICING,
    SPECIALTIES=SPECIALTIES,
    TYPES_WITH_SPECIALTY=TYPES_WITH_SPECIALTY,
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    seed_if_empty()


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


def render(request: Request, template: str, context: dict) -> HTMLResponse:
    return templates.TemplateResponse(request, template, context)


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
    pricing: str = "",
    proven_only: str = "",
):
    filters = {
        "q": q.strip(),
        "city": city,
        "provider_type": provider_type,
        "method": method,
        "specialty": specialty,
        "age": parse_int(age),
        "pricing": pricing if pricing in PRICING else "",
        "proven_only": bool(proven_only),
    }
    with db_session() as conn:
        providers = crud.search_providers(conn, filters)
        methods_map = crud.methods_for_providers(conn, [p["id"] for p in providers])
        context = {
            "providers": providers,
            "methods_map": methods_map,
            "all_methods": crud.list_methods(conn),
            "cities": crud.cities(conn),
            "specialties": crud.specialties_in_use(conn),
            "filters": filters,
            "raw": {
                "q": q,
                "city": city,
                "provider_type": provider_type,
                "method": method,
                "specialty": specialty,
                "age": age,
                "pricing": pricing,
                "proven_only": bool(proven_only),
            },
        }
    return render(request, "index.html", context)


@app.get("/providers/{provider_id}", response_class=HTMLResponse)
def provider_detail(request: Request, provider_id: int, review: str = ""):
    with db_session() as conn:
        provider = crud.get_provider(conn, provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="Провайдер не найден")
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
):
    author_name = author_name.strip()
    text = text.strip()
    rating_value = parse_int(rating)
    client_ip = request.client.host if request.client else "unknown"

    if not author_name or not text or rating_value not in (1, 2, 3, 4, 5):
        return RedirectResponse(
            f"/providers/{provider_id}?review=invalid#reviews", status_code=REDIRECT
        )

    with db_session() as conn:
        if crud.get_provider(conn, provider_id) is None:
            raise HTTPException(status_code=404, detail="Провайдер не найден")
        if crud.has_recent_review_from_ip(conn, provider_id, client_ip):
            return RedirectResponse(
                f"/providers/{provider_id}?review=limit#reviews", status_code=REDIRECT
            )
        crud.create_review(
            conn,
            {
                "provider_id": provider_id,
                "author_name": author_name[:80],
                "rating": rating_value,
                "text": text[:2000],
                "author_ip": client_ip,
            },
        )
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


# --- Админка ----------------------------------------------------------------

def require_admin(request: Request) -> RedirectResponse | None:
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=REDIRECT)
    return None


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_form(request: Request, error: str = ""):
    return render(request, "admin/login.html", {"error": error})


@app.post("/admin/login")
def admin_login(request: Request, login: str = Form(""), password: str = Form("")):
    login_ok = secrets.compare_digest(login.strip(), ADMIN_LOGIN)
    password_ok = secrets.compare_digest(password, ADMIN_PASSWORD)
    if login_ok and password_ok:
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=REDIRECT)
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
            "pending_count": crud.pending_count(conn),
            "methods_count": len(crud.list_methods(conn)),
        }
    return render(request, "admin/providers.html", context)


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
def admin_provider_new(request: Request):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        methods = crud.list_methods(conn)
    return render(
        request,
        "admin/provider_form.html",
        {
            "provider": None,
            "methods": methods,
            "selected_methods": set(),
            "title": "Новый провайдер",
        },
    )


@app.post("/admin/providers/new")
async def admin_provider_create(request: Request):
    if guard := require_admin(request):
        return guard
    form = await request.form()
    logo_path = await save_logo(form.get("logo"), "")
    data, method_ids = provider_form_data(
        _form_defaults(form), form.getlist("methods"), logo_path
    )
    if not data["name"] or not data["city"]:
        return RedirectResponse("/admin/providers/new?error=1", status_code=REDIRECT)
    with db_session() as conn:
        crud.create_provider(conn, data, method_ids)
    return RedirectResponse("/admin", status_code=REDIRECT)


@app.get("/admin/providers/{provider_id}/edit", response_class=HTMLResponse)
def admin_provider_edit(request: Request, provider_id: int):
    if guard := require_admin(request):
        return guard
    with db_session() as conn:
        provider = crud.get_provider(conn, provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="Провайдер не найден")
        context = {
            "provider": provider,
            "methods": crud.list_methods(conn),
            "selected_methods": crud.provider_method_ids(conn, provider_id),
            "title": "Редактирование провайдера",
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
        raise HTTPException(status_code=404, detail="Провайдер не найден")

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


@app.post("/admin/reviews/{review_id}/{action}")
def admin_review_action(request: Request, review_id: int, action: str):
    if guard := require_admin(request):
        return guard
    statuses = {"approve": "published", "reject": "rejected"}
    if action not in statuses:
        raise HTTPException(status_code=404, detail="Неизвестное действие")
    with db_session() as conn:
        crud.set_review_status(conn, review_id, statuses[action])
    return RedirectResponse("/admin/reviews", status_code=REDIRECT)


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
