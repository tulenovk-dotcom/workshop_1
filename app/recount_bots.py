"""Разовый пересчёт журнала посещений: пометить роботов задним числом.

Обычная работа сайта эту команду не трогает: при посещении робот помечается
сразу. Команда нужна для записей, сделанных раньше, - когда отсев был другим
или когда в него добавили новое правило.

Как запускать на сервере, из папки сайта:

    python -m app.recount_bots            # показать, что изменится
    python -m app.recount_bots --apply    # пометить и поправить счётчик

**Сначала копия базы, потом `--apply`.** Команда меняет записи и счётчик по
дням; откатить изменение можно только из копии. Без `--apply` она ничего не
пишет - только считает и показывает.

Работает в обе стороны. Если правило отсева расширили, записи помечаются
роботами и уходят из счётчика. Если правило оказалось слишком широким и его
сузили, те же записи возвращаются людьми и в счётчик. Поэтому записи роботов
и не удаляются: удалённое не вернёшь, а помеченное - вернёшь.

Команду можно запускать сколько угодно раз: второй запуск подряд ничего не
меняет.
"""

import argparse
import sqlite3
import sys
from datetime import datetime

from .crud import visit_day
from .database import DB_PATH, db_session
from .useragent import looks_like_bot


def проверить_базу(путь):
    """Можно ли работать с этим файлом. Возвращает текст ошибки или None.

    Проверяем до подключения нарочно: `sqlite3.connect` создаёт пустой файл,
    если его нет, и команда молча заводила бы новую базу вместо работы с
    настоящей. Так уже и вышло при первом запуске на сервере.
    """
    if not путь.exists():
        return (
            f"Файла базы нет: {путь}\n\n"
            "Скорее всего, не задана переменная DB_PATH. Сайт берёт её из\n"
            "настроек службы (EnvironmentFile), а при запуске руками их нет,\n"
            "и путь получается другой - рядом с кодом.\n\n"
            "Запустите, подставив тот же путь, что у службы, например:\n"
            "    DB_PATH=/srv/erekshe/data/catalog.db .venv/bin/python -m app.recount_bots"
        )
    try:
        with sqlite3.connect(f"file:{путь}?mode=ro", uri=True) as conn:
            есть = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='visit_log'"
            ).fetchone()
    except sqlite3.Error as ошибка:
        return f"Не удалось открыть базу {путь}: {ошибка}"
    if not есть:
        return (
            f"В базе {путь} нет таблицы visit_log.\n\n"
            "Похоже, это не та база, с которой работает сайт: возможно, пустой\n"
            "файл, созданный предыдущим запуском без DB_PATH.\n"
            "Проверьте путь в настройках службы и подставьте его в DB_PATH."
        )
    return None


def разобрать(conn):
    """Что поменялось бы: списки записей на пометку и на возврат."""
    rows = conn.execute(
        "SELECT id, created_at, user_agent, is_bot FROM visit_log"
    ).fetchall()
    пометить = []
    вернуть = []
    for row in rows:
        робот = looks_like_bot(row["user_agent"])
        if робот and not row["is_bot"]:
            пометить.append(row)
        elif not робот and row["is_bot"]:
            вернуть.append(row)
    return rows, пометить, вернуть


def по_дням(rows) -> dict:
    счёт: dict = {}
    for row in rows:
        day = visit_day(datetime.fromisoformat(row["created_at"]))
        счёт[day] = счёт.get(day, 0) + 1
    return счёт


def подписи(rows) -> dict:
    счёт: dict = {}
    for row in rows:
        agent = (row["user_agent"] or "(подписи нет)")[:70]
        счёт[agent] = счёт.get(agent, 0) + 1
    return dict(sorted(счёт.items(), key=lambda pair: -pair[1]))


def показать(rows, пометить, вернуть) -> None:
    print(f"Записей в журнале: {len(rows)}")
    print(f"  из них уже помечены роботами: {sum(1 for r in rows if r['is_bot'])}")
    print()
    print(f"Пометить роботами: {len(пометить)}")
    for agent, count in list(подписи(пометить).items())[:15]:
        print(f"    {count:5}  {agent}")
    print()
    print(f"Вернуть людям: {len(вернуть)}")
    for agent, count in list(подписи(вернуть).items())[:15]:
        print(f"    {count:5}  {agent}")
    print()
    дни = по_дням(пометить)
    возврат = по_дням(вернуть)
    if дни or возврат:
        print("Счётчик по дням изменится так:")
        for day in sorted(set(дни) | set(возврат)):
            сдвиг = возврат.get(day, 0) - дни.get(day, 0)
            print(f"    {day}: {сдвиг:+d}")


def применить(conn, пометить, вернуть) -> None:
    if пометить:
        conn.executemany(
            "UPDATE visit_log SET is_bot = 1 WHERE id = ?",
            [(row["id"],) for row in пометить],
        )
        conn.executemany(
            # MAX(0, ...) на случай, если часть записей журнала уже ушла по
            # сроку хранения, а счётчик дня их ещё помнит.
            "UPDATE visit_days SET views = MAX(0, views - ?) WHERE day = ?",
            [(count, day) for day, count in по_дням(пометить).items()],
        )
    if вернуть:
        conn.executemany(
            "UPDATE visit_log SET is_bot = 0 WHERE id = ?",
            [(row["id"],) for row in вернуть],
        )
        conn.executemany(
            "UPDATE visit_days SET views = views + ? WHERE day = ?",
            [(count, day) for day, count in по_дням(вернуть).items()],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="записать изменения; без него команда ничего не меняет",
    )
    args = parser.parse_args()

    # Какой файл открыли - печатаем всегда, даже когда всё хорошо: половина
    # недоразумений с этой командой именно про «не та база».
    print(f"База: {DB_PATH}")
    беда = проверить_базу(DB_PATH)
    if беда:
        print(f"\n{беда}", file=sys.stderr)
        raise SystemExit(1)

    with db_session() as conn:
        rows, пометить, вернуть = разобрать(conn)
        показать(rows, пометить, вернуть)
        if not (пометить or вернуть):
            print("\nМенять нечего.")
            return
        if not args.apply:
            print(
                "\nНичего не записано. Сделайте копию базы и повторите"
                " с --apply, если всё верно."
            )
            return
        применить(conn, пометить, вернуть)
        print(f"\nГотово. Помечено роботами: {len(пометить)},"
              f" возвращено людям: {len(вернуть)}.")


if __name__ == "__main__":
    main()
