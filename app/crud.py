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


def create_method(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute(
        "INSERT INTO methods (code, name, description, evidence_level, sort_order)"
        " VALUES (:code, :name, :description, :evidence_level, :sort_order)",
        data,
    )
    return int(cur.lastrowid)


def update_method(conn: sqlite3.Connection, method_id: int, data: dict) -> None:
    conn.execute(
        "UPDATE methods SET code = :code, name = :name, description = :description,"
        " evidence_level = :evidence_level, sort_order = :sort_order WHERE id = :id",
        {**data, "id": method_id},
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
    if f.get("age") is not None:
        sql.append(
            "AND (p.age_from IS NULL OR p.age_from <= ?)"
            " AND (p.age_to IS NULL OR p.age_to >= ?)"
        )
        params.extend([f["age"], f["age"]])
    if f.get("pricing"):
        sql.append("AND p.pricing = ?")
        params.append(f["pricing"])
    if f.get("max_price") is not None:
        sql.append(
            "AND (p.pricing = 'free' OR p.price_from IS NULL OR p.price_from <= ?)"
        )
        params.append(f["max_price"])
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
        " author_ip, created_at)"
        " VALUES (:provider_id, :author_name, :rating, :text, 'pending',"
        " :author_ip, :created_at)",
        {**data, "created_at": now_iso()},
    )
    return int(cur.lastrowid)


def set_review_status(conn: sqlite3.Connection, review_id: int, status: str) -> None:
    conn.execute("UPDATE reviews SET status = ? WHERE id = ?", (status, review_id))


def has_recent_review_from_ip(
    conn: sqlite3.Connection, provider_id: int, ip: str
) -> bool:
    """Не больше одного отзыва с одного IP на провайдера в сутки."""
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(
        timespec="seconds"
    )
    row = conn.execute(
        "SELECT 1 FROM reviews WHERE provider_id = ? AND author_ip = ?"
        " AND created_at > ? LIMIT 1",
        (provider_id, ip, since),
    ).fetchone()
    return row is not None
