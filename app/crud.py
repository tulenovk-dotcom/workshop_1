import sqlite3
from datetime import datetime, timedelta, timezone

PROVIDER_FIELDS = (
    "provider_type",
    "name",
    "specialty",
    "city",
    "district",
    "address",
    "phone",
    "whatsapp",
    "website",
    "instagram",
    "age_from",
    "age_to",
    "price_from",
    "price_to",
    "pricing",
    "has_state_funding",
    "description",
    "logo_path",
    "is_test",
)

RATING_COLUMNS = """
    (SELECT ROUND(AVG(r.rating), 1) FROM reviews r
       WHERE r.provider_id = p.id AND r.status = 'published') AS rating_avg,
    (SELECT COUNT(*) FROM reviews r
       WHERE r.provider_id = p.id AND r.status = 'published') AS reviews_count
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Методы -----------------------------------------------------------------

def list_methods(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM methods ORDER BY sort_order, name"
    ).fetchall()


def get_method(conn: sqlite3.Connection, method_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM methods WHERE id = ?", (method_id,)).fetchone()


METHOD_FIELDS = (
    "code",
    "name",
    "description",
    "name_kk",
    "description_kk",
    "evidence_level",
    "sort_order",
)


def create_method(conn: sqlite3.Connection, data: dict) -> int:
    columns = ", ".join(METHOD_FIELDS)
    placeholders = ", ".join(f":{name}" for name in METHOD_FIELDS)
    cur = conn.execute(
        f"INSERT INTO methods ({columns}) VALUES ({placeholders})",
        {"name_kk": "", "description_kk": "", **data},
    )
    return int(cur.lastrowid)


def update_method(conn: sqlite3.Connection, method_id: int, data: dict) -> None:
    assignments = ", ".join(f"{name} = :{name}" for name in METHOD_FIELDS)
    conn.execute(
        f"UPDATE methods SET {assignments} WHERE id = :id",
        {"name_kk": "", "description_kk": "", **data, "id": method_id},
    )


def delete_method(conn: sqlite3.Connection, method_id: int) -> None:
    conn.execute("DELETE FROM methods WHERE id = ?", (method_id,))


def methods_for_providers(
    conn: sqlite3.Connection, provider_ids: list[int]
) -> dict[int, list[sqlite3.Row]]:
    if not provider_ids:
        return {}
    placeholders = ",".join("?" * len(provider_ids))
    rows = conn.execute(
        f"""SELECT pm.provider_id, m.* FROM provider_methods pm
            JOIN methods m ON m.id = pm.method_id
            WHERE pm.provider_id IN ({placeholders})
            ORDER BY m.sort_order, m.name""",
        provider_ids,
    ).fetchall()
    grouped: dict[int, list[sqlite3.Row]] = {pid: [] for pid in provider_ids}
    for row in rows:
        grouped[row["provider_id"]].append(row)
    return grouped


def provider_method_ids(conn: sqlite3.Connection, provider_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT method_id FROM provider_methods WHERE provider_id = ?", (provider_id,)
    ).fetchall()
    return {row["method_id"] for row in rows}


def set_provider_methods(
    conn: sqlite3.Connection, provider_id: int, method_ids: list[int]
) -> None:
    conn.execute("DELETE FROM provider_methods WHERE provider_id = ?", (provider_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO provider_methods (provider_id, method_id) VALUES (?, ?)",
        [(provider_id, mid) for mid in method_ids],
    )


# --- Провайдеры -------------------------------------------------------------

def cities(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT city FROM providers WHERE city <> '' ORDER BY city"
    ).fetchall()
    return [row["city"] for row in rows]


def specialties_in_use(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT specialty FROM providers"
        " WHERE specialty IS NOT NULL AND specialty <> '' ORDER BY specialty"
    ).fetchall()
    return [row["specialty"] for row in rows]


def search_providers(conn: sqlite3.Connection, f: dict) -> list[sqlite3.Row]:
    sql = [f"SELECT p.*, {RATING_COLUMNS} FROM providers p WHERE 1 = 1"]
    params: list = []

    if f.get("q"):
        sql.append("AND lower_ru(p.name) LIKE ?")
        params.append(f"%{f['q'].lower()}%")
    if f.get("city"):
        sql.append("AND p.city = ?")
        params.append(f["city"])
    if f.get("provider_type"):
        sql.append("AND p.provider_type = ?")
        params.append(f["provider_type"])
    if f.get("specialty"):
        sql.append("AND p.specialty = ?")
        params.append(f["specialty"])
    if f.get("method"):
        sql.append(
            "AND EXISTS (SELECT 1 FROM provider_methods pm JOIN methods m"
            " ON m.id = pm.method_id WHERE pm.provider_id = p.id AND m.code = ?)"
        )
        params.append(f["method"])
    if f.get("age_range"):
        # Провайдер подходит, если его диапазон возрастов пересекается
        # с выбранной возрастной группой.
        low, high = f["age_range"]
        sql.append(
            "AND (p.age_from IS NULL OR p.age_from <= ?)"
            " AND (p.age_to IS NULL OR p.age_to >= ?)"
        )
        params.extend([high, low])
    if f.get("proven_only"):
        # Провайдер работает доказательными методами и не предлагает методы
        # без подтверждённой эффективности.
        sql.append(
            "AND EXISTS (SELECT 1 FROM provider_methods pm JOIN methods m"
            " ON m.id = pm.method_id WHERE pm.provider_id = p.id"
            " AND m.evidence_level = 'proven')"
            " AND NOT EXISTS (SELECT 1 FROM provider_methods pm JOIN methods m"
            " ON m.id = pm.method_id WHERE pm.provider_id = p.id"
            " AND m.evidence_level = 'none')"
        )

    sql.append("ORDER BY rating_avg IS NULL, rating_avg DESC, p.name")
    return conn.execute(" ".join(sql), params).fetchall()


def get_provider(conn: sqlite3.Connection, provider_id: int) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT p.*, {RATING_COLUMNS} FROM providers p WHERE p.id = ?",
        (provider_id,),
    ).fetchone()


def list_providers_admin(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT p.*, {RATING_COLUMNS} FROM providers p ORDER BY p.city, p.name"
    ).fetchall()


def create_provider(conn: sqlite3.Connection, data: dict, method_ids: list[int]) -> int:
    columns = ", ".join(PROVIDER_FIELDS)
    placeholders = ", ".join(f":{name}" for name in PROVIDER_FIELDS)
    cur = conn.execute(
        f"INSERT INTO providers ({columns}, created_at)"
        f" VALUES ({placeholders}, :created_at)",
        {**data, "created_at": now_iso()},
    )
    provider_id = int(cur.lastrowid)
    set_provider_methods(conn, provider_id, method_ids)
    return provider_id


def update_provider(
    conn: sqlite3.Connection, provider_id: int, data: dict, method_ids: list[int]
) -> None:
    assignments = ", ".join(f"{name} = :{name}" for name in PROVIDER_FIELDS)
    conn.execute(
        f"UPDATE providers SET {assignments} WHERE id = :id",
        {**data, "id": provider_id},
    )
    set_provider_methods(conn, provider_id, method_ids)


def delete_provider(conn: sqlite3.Connection, provider_id: int) -> None:
    conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))


# --- Отзывы -----------------------------------------------------------------

def published_reviews(
    conn: sqlite3.Connection, provider_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM reviews WHERE provider_id = ? AND status = 'published'"
        " ORDER BY created_at DESC",
        (provider_id,),
    ).fetchall()


def reviews_by_status(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT r.*, p.name AS provider_name FROM reviews r"
        " JOIN providers p ON p.id = r.provider_id"
        " WHERE r.status = ? ORDER BY r.created_at DESC",
        (status,),
    ).fetchall()


def pending_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM reviews WHERE status = 'pending'"
    ).fetchone()
    return int(row["n"])


def create_review(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute(
        "INSERT INTO reviews (provider_id, author_name, rating, text, status,"
        " author_ip_hash, created_at)"
        " VALUES (:provider_id, :author_name, :rating, :text, 'pending',"
        " :author_ip_hash, :created_at)",
        {**data, "created_at": now_iso()},
    )
    return int(cur.lastrowid)


def set_review_status(conn: sqlite3.Connection, review_id: int, status: str) -> None:
    conn.execute("UPDATE reviews SET status = ? WHERE id = ?", (status, review_id))


def get_review(conn: sqlite3.Connection, review_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT r.*, p.name AS provider_name FROM reviews r"
        " LEFT JOIN providers p ON p.id = r.provider_id WHERE r.id = ?",
        (review_id,),
    ).fetchone()


def has_recent_review_from_ip(
    conn: sqlite3.Connection, provider_id: int, ip_hash: str
) -> bool:
    """Не больше одного отзыва с одного адреса на провайдера в сутки.

    Сам адрес нигде не хранится, сравниваются хеши.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(
        timespec="seconds"
    )
    row = conn.execute(
        "SELECT 1 FROM reviews WHERE provider_id = ? AND author_ip_hash = ?"
        " AND created_at > ? LIMIT 1",
        (provider_id, ip_hash, since),
    ).fetchone()
    return row is not None


# --- Заявки на размещение ---------------------------------------------------

APPLICATION_FIELDS = (
    "applicant_kind",
    "name",
    "provider_type",
    "specialty",
    "city",
    "address",
    "method_codes",
    "age_from",
    "age_to",
    "price_from",
    "price_to",
    "pricing",
    "link",
    "contact_person",
    "phone",
    "whatsapp",
    "email",
    "comment",
    "logo_path",
    "author_ip_hash",
)


def create_application(conn: sqlite3.Connection, data: dict) -> int:
    columns = ", ".join(APPLICATION_FIELDS)
    placeholders = ", ".join(f":{name}" for name in APPLICATION_FIELDS)
    now = now_iso()
    cur = conn.execute(
        f"INSERT INTO applications ({columns}, consent_at, created_at, updated_at)"
        f" VALUES ({placeholders}, :consent_at, :created_at, :updated_at)",
        {**data, "consent_at": now, "created_at": now, "updated_at": now},
    )
    return int(cur.lastrowid)


def list_applications(
    conn: sqlite3.Connection, status: str = "", limit: int | None = None
) -> list[sqlite3.Row]:
    sql = [
        "SELECT a.*, p.name AS provider_name FROM applications a"
        " LEFT JOIN providers p ON p.id = a.provider_id"
    ]
    params: list = []
    if status:
        sql.append("WHERE a.status = ?")
        params.append(status)
    sql.append("ORDER BY a.created_at DESC, a.id DESC")
    if limit is not None:
        sql.append("LIMIT ?")
        params.append(limit)
    return conn.execute(" ".join(sql), params).fetchall()


def get_application(
    conn: sqlite3.Connection, application_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT a.*, p.name AS provider_name FROM applications a"
        " LEFT JOIN providers p ON p.id = a.provider_id WHERE a.id = ?",
        (application_id,),
    ).fetchone()


def update_application(
    conn: sqlite3.Connection, application_id: int, status: str, admin_note: str
) -> None:
    conn.execute(
        "UPDATE applications SET status = ?, admin_note = ?, updated_at = ?"
        " WHERE id = ?",
        (status, admin_note, now_iso(), application_id),
    )


def link_application_to_provider(
    conn: sqlite3.Connection, application_id: int, provider_id: int
) -> None:
    """Заявка одобрена: запоминаем карточку, созданную по ней."""
    conn.execute(
        "UPDATE applications SET status = 'approved', provider_id = ?,"
        " updated_at = ? WHERE id = ?",
        (provider_id, now_iso(), application_id),
    )


def delete_application(conn: sqlite3.Connection, application_id: int) -> None:
    conn.execute("DELETE FROM applications WHERE id = ?", (application_id,))


def new_applications_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM applications WHERE status = 'new'"
    ).fetchone()
    return int(row["n"])


def applications_from_ip_last_hour(conn: sqlite3.Connection, ip_hash: str) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(
        timespec="seconds"
    )
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM applications"
        " WHERE author_ip_hash = ? AND created_at > ?",
        (ip_hash, since),
    ).fetchone()
    return int(row["n"])


def pending_reviews(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT r.*, p.name AS provider_name FROM reviews r"
        " JOIN providers p ON p.id = r.provider_id"
        " WHERE r.status = 'pending' ORDER BY r.created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()


# --- Согласия на обработку данных -------------------------------------------

def create_consent(conn: sqlite3.Connection, data: dict) -> int:
    """Отметка о согласии. Пишется в той же транзакции, что и сама запись:
    данных без согласия в базе быть не должно."""
    cur = conn.execute(
        "INSERT INTO consents (subject_type, record_id, purpose, policy_version,"
        " consent_text, given_at, ip_hash, user_agent)"
        " VALUES (:subject_type, :record_id, :purpose, :policy_version,"
        " :consent_text, :given_at, :ip_hash, :user_agent)",
        {**data, "given_at": now_iso()},
    )
    return int(cur.lastrowid)


def get_consent(
    conn: sqlite3.Connection, subject_type: str, record_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM consents WHERE subject_type = ? AND record_id = ?"
        " ORDER BY id DESC LIMIT 1",
        (subject_type, record_id),
    ).fetchone()


def revoke_consent(conn: sqlite3.Connection, subject_type: str, record_id: int) -> None:
    conn.execute(
        "UPDATE consents SET revoked_at = ? WHERE subject_type = ? AND record_id = ?"
        " AND revoked_at IS NULL",
        (now_iso(), subject_type, record_id),
    )


# --- Журнал действий с данными ----------------------------------------------

def log_data_action(
    conn: sqlite3.Connection,
    action: str,
    subject_type: str,
    record_id: int,
    reason: str = "",
) -> None:
    conn.execute(
        "INSERT INTO data_actions (action, subject_type, record_id, reason, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (action, subject_type, record_id, reason[:500], now_iso()),
    )


def data_actions_for(
    conn: sqlite3.Connection, subject_type: str, record_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM data_actions WHERE subject_type = ? AND record_id = ?"
        " ORDER BY id DESC",
        (subject_type, record_id),
    ).fetchall()


def list_data_actions(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM data_actions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


# --- Удаление и обезличивание -----------------------------------------------

# Что остаётся на месте затёртых контактов. Пустая строка не годится:
# по ней не видно, что запись обезличили, а не оставили незаполненной.
ANONYMIZED = "Данные удалены"


def delete_personal_data(
    conn: sqlite3.Connection, subject_type: str, record_id: int, reason: str = ""
) -> bool:
    """Необратимое удаление записи вместе с отметкой о согласии."""
    table = "applications" if subject_type == "application" else "reviews"
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE id = ?", (record_id,)
    ).fetchone()
    if row is None:
        return False
    conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
    conn.execute(
        "DELETE FROM consents WHERE subject_type = ? AND record_id = ?",
        (subject_type, record_id),
    )
    # Журнал переживает саму запись: в нём остаётся только её номер.
    log_data_action(conn, "delete", subject_type, record_id, reason)
    return True


def anonymize_personal_data(
    conn: sqlite3.Connection, subject_type: str, record_id: int, reason: str = ""
) -> bool:
    """Контакты затираются, обезличенная часть записи остаётся.

    У заявки это город, вид заявителя, место занятий и даты; у отзыва -
    оценка, место занятий и дата. Отзыв при этом снимается с публикации:
    его текст писал человек, и он тоже мог назвать себя.
    """
    now = now_iso()
    if subject_type == "application":
        changed = conn.execute(
            "UPDATE applications SET name = ?, contact_person = ?, phone = '',"
            " whatsapp = '', email = '', address = '', link = '', comment = '',"
            " logo_path = '', author_ip_hash = NULL, anonymized_at = ?,"
            " updated_at = ? WHERE id = ? AND anonymized_at IS NULL",
            (ANONYMIZED, ANONYMIZED, now, now, record_id),
        ).rowcount
    else:
        changed = conn.execute(
            "UPDATE reviews SET author_name = ?, text = ?, status = 'rejected',"
            " author_ip_hash = NULL, anonymized_at = ?"
            " WHERE id = ? AND anonymized_at IS NULL",
            (ANONYMIZED, "Отзыв обезличен по обращению автора.", now, record_id),
        ).rowcount
    if not changed:
        return False
    revoke_consent(conn, subject_type, record_id)
    log_data_action(conn, "anonymize", subject_type, record_id, reason)
    return True


def cleanup_personal_data(conn: sqlite3.Connection) -> int:
    """Сроки хранения: отклонённая заявка обезличивается через полгода,
    отклонённый отзыв - через три месяца. Вызывается при старте."""
    now = datetime.now(timezone.utc)
    applications_before = (now - timedelta(days=183)).isoformat(timespec="seconds")
    reviews_before = (now - timedelta(days=92)).isoformat(timespec="seconds")

    stale_applications = conn.execute(
        "SELECT id FROM applications WHERE status = 'rejected'"
        " AND anonymized_at IS NULL AND updated_at < ?",
        (applications_before,),
    ).fetchall()
    stale_reviews = conn.execute(
        "SELECT id FROM reviews WHERE status = 'rejected'"
        " AND anonymized_at IS NULL AND created_at < ?",
        (reviews_before,),
    ).fetchall()

    done = 0
    for row in stale_applications:
        if anonymize_personal_data(
            conn, "application", row["id"], "истёк срок хранения: 6 месяцев"
        ):
            done += 1
    for row in stale_reviews:
        if anonymize_personal_data(
            conn, "review", row["id"], "истёк срок хранения: 3 месяца"
        ):
            done += 1
    return done


# --- Обращения субъектов данных ---------------------------------------------

def create_request(conn: sqlite3.Connection, data: dict) -> int:
    now = now_iso()
    cur = conn.execute(
        "INSERT INTO requests (name, contact, message, author_ip_hash,"
        " created_at, updated_at)"
        " VALUES (:name, :contact, :message, :author_ip_hash,"
        " :created_at, :updated_at)",
        {**data, "created_at": now, "updated_at": now},
    )
    return int(cur.lastrowid)


def list_requests(
    conn: sqlite3.Connection, status: str = "", limit: int | None = None
) -> list[sqlite3.Row]:
    sql = ["SELECT * FROM requests"]
    params: list = []
    if status:
        sql.append("WHERE status = ?")
        params.append(status)
    sql.append("ORDER BY created_at DESC, id DESC")
    if limit is not None:
        sql.append("LIMIT ?")
        params.append(limit)
    return conn.execute(" ".join(sql), params).fetchall()


def get_request(conn: sqlite3.Connection, request_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM requests WHERE id = ?", (request_id,)
    ).fetchone()


def update_request(
    conn: sqlite3.Connection, request_id: int, status: str, admin_note: str
) -> None:
    conn.execute(
        "UPDATE requests SET status = ?, admin_note = ?, updated_at = ? WHERE id = ?",
        (status, admin_note, now_iso(), request_id),
    )


def delete_request(conn: sqlite3.Connection, request_id: int) -> None:
    conn.execute("DELETE FROM requests WHERE id = ?", (request_id,))


def new_requests_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM requests WHERE status = 'new'"
    ).fetchone()
    return int(row["n"])


def requests_from_ip_last_hour(conn: sqlite3.Connection, ip_hash: str) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(
        timespec="seconds"
    )
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM requests WHERE author_ip_hash = ? AND created_at > ?",
        (ip_hash, since),
    ).fetchone()
    return int(row["n"])


# --- Статистика -------------------------------------------------------------

# Названия столбцов и таблиц в SQL подставляются текстом, поэтому берутся
# только из этих перечней. Значение, пришедшее со стороны, сюда не попадёт.
_COUNTABLE_PROVIDER_COLUMNS = ("city", "provider_type")
_COUNTABLE_STATUS_TABLES = ("applications", "requests", "reviews")


def provider_counts_by(conn: sqlite3.Connection, column: str) -> list[sqlite3.Row]:
    """Сколько мест занятий приходится на каждое значение столбца.

    Пустое значение не теряется, а попадает в строку «не указан»: иначе
    сумма по таблице не сходится с общим числом, и это каждый раз
    приходится объяснять.
    """
    if column not in _COUNTABLE_PROVIDER_COLUMNS:
        raise ValueError(f"нельзя считать по столбцу {column!r}")
    return conn.execute(
        f"SELECT COALESCE(NULLIF(TRIM({column}), ''), '') AS value,"
        "       COUNT(*) AS n"
        "  FROM providers"
        " GROUP BY value"
        " ORDER BY n DESC, value"
    ).fetchall()


def provider_counts_by_method(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Сколько мест предлагает каждый метод. Порядок - как в справочнике,
    чтобы страница статистики и фильтр на главной читались одинаково."""
    return conn.execute(
        "SELECT m.id, m.name, m.evidence_level,"
        "       COUNT(pm.provider_id) AS n"
        "  FROM methods m"
        "  LEFT JOIN provider_methods pm ON pm.method_id = m.id"
        " GROUP BY m.id"
        " ORDER BY m.sort_order, m.name"
    ).fetchall()


def providers_without_methods(conn: sqlite3.Connection) -> int:
    """Карточки, у которых не отмечен ни один метод: в фильтре по методу
    они не находятся, поэтому их полезно видеть отдельно."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM providers p"
        " WHERE NOT EXISTS (SELECT 1 FROM provider_methods pm"
        "                    WHERE pm.provider_id = p.id)"
    ).fetchone()
    return int(row["n"])


def test_providers_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM providers WHERE is_test = 1"
    ).fetchone()
    return int(row["n"])


def counts_by_status(conn: sqlite3.Connection, table: str) -> dict:
    if table not in _COUNTABLE_STATUS_TABLES:
        raise ValueError(f"нельзя считать статусы таблицы {table!r}")
    rows = conn.execute(
        f"SELECT status, COUNT(*) AS n FROM {table} GROUP BY status"
    ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


def created_since(conn: sqlite3.Connection, table: str, days: int) -> int:
    """Сколько записей появилось за последние сутки * days."""
    if table not in _COUNTABLE_STATUS_TABLES:
        raise ValueError(f"нельзя считать таблицу {table!r}")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE created_at > ?", (since,)
    ).fetchone()
    return int(row["n"])


def working_days_ago(days: int) -> datetime:
    """Момент, отстоящий на `days` рабочих дней назад.

    Суббота и воскресенье не считаются. Праздники не учитываются: их
    календарь в проекте не заведён, и ради одной строки статистики заводить
    его незачем. Значит, счёт получается чуть строже обещанного срока,
    а не мягче - в пользу человека, который ждёт ответа.
    """
    moment = datetime.now(timezone.utc)
    left = days
    while left:
        moment -= timedelta(days=1)
        if moment.weekday() < 5:
            left -= 1
    return moment


def requests_waiting_longer_than(conn: sqlite3.Connection, days: int) -> int:
    """Обращения, на которые не ответили дольше обещанного срока.

    Срок обещан человеку на странице «Отозвать согласие или удалить мои
    данные», и обещан в рабочих днях - поэтому и считаем в рабочих.
    Просрочка здесь - не статистика ради статистики, а невыполненное
    обещание конкретному человеку.
    """
    deadline = working_days_ago(days).isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM requests"
        " WHERE status != 'done' AND created_at < ?",
        (deadline,),
    ).fetchone()
    return int(row["n"])


def review_ratings(conn: sqlite3.Connection) -> dict:
    """Распределение оценок по опубликованным отзывам: оценка -> сколько."""
    rows = conn.execute(
        "SELECT rating, COUNT(*) AS n FROM reviews"
        " WHERE status = 'published' GROUP BY rating"
    ).fetchall()
    return {int(row["rating"]): int(row["n"]) for row in rows}


def average_published_rating(conn: sqlite3.Connection) -> float | None:
    row = conn.execute(
        "SELECT ROUND(AVG(rating), 1) AS avg FROM reviews"
        " WHERE status = 'published'"
    ).fetchone()
    return row["avg"]


# --- Посещения --------------------------------------------------------------

# В Казахстане одно время, UTC+5. Сутки для статистики нарезаются по нему,
# а не по UTC: иначе «вчерашние» вечерние посещения попадали бы в сегодня.
KZ_TIME = timezone(timedelta(hours=5))


def visit_day(moment: datetime | None = None) -> str:
    return (moment or datetime.now(KZ_TIME)).astimezone(KZ_TIME).strftime("%Y-%m-%d")


def record_visit(conn: sqlite3.Connection, day: str) -> None:
    """Прибавить одно открытие страницы к счётчику дня.

    Посетитель не помечается никак: повторное открытие с того же устройства
    считается наравне с первым. Так и задумано - страница отвечает на вопрос
    «сколько раз сайт открывали», а не «сколько разных людей приходило».
    """
    conn.execute(
        "INSERT INTO visit_days (day, views) VALUES (?, 1)"
        " ON CONFLICT(day) DO UPDATE SET views = views + 1",
        (day,),
    )


def visit_series(conn: sqlite3.Connection, days: int) -> list[dict]:
    """Посещения по дням за последние `days` суток, включая сегодня.

    Дни без посещений не пропускаются, а возвращаются с нулями: на графике
    провал должен быть виден как провал, а не как отсутствие столбика.
    """
    today = datetime.now(KZ_TIME)
    rows = {
        row["day"]: int(row["views"])
        for row in conn.execute(
            "SELECT day, views FROM visit_days WHERE day >= ?",
            (visit_day(today - timedelta(days=days - 1)),),
        )
    }
    series = []
    for back in range(days - 1, -1, -1):
        day = visit_day(today - timedelta(days=back))
        series.append({"day": day, "views": rows.get(day, 0)})
    return series


# --- Журнал посещений -------------------------------------------------------

# Сколько держим записи журнала. Срок обещан человеку на странице /privacy,
# поэтому менять его здесь и там нужно вместе.
VISIT_LOG_DAYS = 30

# Перерыв, после которого считаем, что человек пришёл заново. Полчаса -
# обычная мера: короткая пауза на чтение страницы визитом не считается.
VISIT_GAP_MINUTES = 30


def record_page_view(
    conn: sqlite3.Connection, ip: str, path: str, agent: str, device: str
) -> None:
    """Запись в журнал посещений: адрес, время, страница, браузер.

    В отличие от счётчика по дням, здесь лежат персональные данные. Записи
    удаляются через VISIT_LOG_DAYS дней - см. cleanup_visit_log.
    """
    conn.execute(
        "INSERT INTO visit_log (ip, created_at, path, user_agent, device)"
        " VALUES (?, ?, ?, ?, ?)",
        (ip[:64], now_iso(), path[:300], agent[:300], device[:20]),
    )


def cleanup_visit_log(conn: sqlite3.Connection) -> int:
    """Удалить записи старше срока хранения. Возвращает сколько удалено."""
    limit = (
        datetime.now(timezone.utc) - timedelta(days=VISIT_LOG_DAYS)
    ).isoformat(timespec="seconds")
    cursor = conn.execute("DELETE FROM visit_log WHERE created_at < ?", (limit,))
    return cursor.rowcount or 0


def visit_log_since(days: int) -> str:
    """Начало периода: «сегодня» - это с полуночи по времени Казахстана,
    «7 дней» и «30 дней» - столько полных суток назад."""
    now = datetime.now(KZ_TIME)
    if days <= 1:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = (now - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    return start.astimezone(timezone.utc).isoformat(timespec="seconds")


def visitors(conn: sqlite3.Connection, days: int) -> list[sqlite3.Row]:
    """Уникальные посетители за период: по строке на адрес.

    Визит и просмотр - разные вещи. Просмотр - одно открытие страницы.
    Визит - непрерывный заход: если между открытиями прошло больше
    VISIT_GAP_MINUTES, считаем, что человек пришёл заново.
    """
    return conn.execute(
        """
        WITH steps AS (
          SELECT ip, created_at, device,
                 LAG(created_at) OVER (PARTITION BY ip ORDER BY created_at) AS prev
            FROM visit_log WHERE created_at >= ?
        )
        SELECT ip,
               COUNT(*) AS views,
               MIN(created_at) AS first_seen,
               MAX(created_at) AS last_seen,
               SUM(CASE WHEN prev IS NULL
                          OR (julianday(created_at) - julianday(prev)) * 1440 > ?
                        THEN 1 ELSE 0 END) AS visits,
               GROUP_CONCAT(DISTINCT device) AS devices
          FROM steps
         GROUP BY ip
         ORDER BY last_seen DESC
        """,
        (visit_log_since(days), VISIT_GAP_MINUTES),
    ).fetchall()


def visitors_count(conn: sqlite3.Connection, days: int) -> int:
    row = conn.execute(
        "SELECT COUNT(DISTINCT ip) AS n FROM visit_log WHERE created_at >= ?",
        (visit_log_since(days),),
    ).fetchone()
    return int(row["n"])


def visitor_pages(
    conn: sqlite3.Connection, ip: str, days: int, limit: int = 300
) -> list[sqlite3.Row]:
    """Что смотрел один посетитель: страницы по времени, новые сверху."""
    return conn.execute(
        "SELECT created_at, path, device, user_agent FROM visit_log"
        " WHERE ip = ? AND created_at >= ?"
        " ORDER BY created_at DESC LIMIT ?",
        (ip, visit_log_since(days), limit),
    ).fetchall()
