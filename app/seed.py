"""Стартовое наполнение базы: справочник методов и тестовые провайдеры."""

from . import crud
from .database import db_session
from .reference import DEFAULT_METHODS

# Все записи ниже — выдуманные, нужны только для проверки интерфейса.
TEST_PROVIDERS = [
    {
        "provider_type": "center",
        "name": "Центр «Алма-Ата Плюс» (тестовая запись)",
        "specialty": "",
        "city": "Алматы",
        "district": "Бостандыкский район",
        "address": "ул. Примерная, 12, офис 3",
        "phone": "+7 700 000 00 01",
        "whatsapp": "+7 700 000 00 01",
        "website": "example.kz",
        "instagram": "@example_center",
        "age_from": 2,
        "age_to": 12,
        "price_from": 8000,
        "price_to": 15000,
        "pricing": "paid",
        "has_state_funding": 1,
        "description": "Коррекционный центр с программой на основе ABA. Занятия "
        "индивидуальные и в малых группах, есть сопровождение семьи и обучение "
        "родителей.",
        "methods": ["aba", "speech", "parent", "pecs"],
    },
    {
        "provider_type": "center",
        "name": "Центр «Шаг за шагом» (тестовая запись)",
        "specialty": "",
        "city": "Алматы",
        "district": "Алмалинский район",
        "address": "пр. Тестовый, 45",
        "phone": "+7 700 000 00 02",
        "whatsapp": "+7 700 000 00 02",
        "website": "",
        "instagram": "@example_steps",
        "age_from": 3,
        "age_to": 10,
        "price_from": 6000,
        "price_to": 10000,
        "pricing": "paid",
        "has_state_funding": 0,
        "description": "Занятия по развитию речи и бытовых навыков, сенсорный "
        "зал, адаптивная физкультура.",
        "methods": ["speech", "ergo", "si", "adaptive_pe"],
    },
    {
        "provider_type": "clinic",
        "name": "Клиника детского развития «Демо» (тестовая запись)",
        "specialty": "",
        "city": "Астана",
        "district": "район Есиль",
        "address": "ул. Образцовая, 7",
        "phone": "+7 700 000 00 03",
        "whatsapp": "+7 700 000 00 03",
        "website": "example-clinic.kz",
        "instagram": "",
        "age_from": 1,
        "age_to": 18,
        "price_from": 12000,
        "price_to": 25000,
        "pricing": "paid",
        "has_state_funding": 1,
        "description": "Приём детского невролога и психиатра, диагностика РАС, "
        "составление программы помощи, направление к специалистам центра.",
        "methods": ["speech", "defect", "parent"],
    },
    {
        "provider_type": "center",
        "name": "Кабинет коррекции «Болашак-Демо» (тестовая запись)",
        "specialty": "",
        "city": "Астана",
        "district": "район Алматы",
        "address": "ул. Пробная, 3",
        "phone": "+7 700 000 00 04",
        "whatsapp": "+7 700 000 00 04",
        "website": "",
        "instagram": "@example_bolashak",
        "age_from": 2,
        "age_to": 8,
        "price_from": None,
        "price_to": None,
        "pricing": "free",
        "has_state_funding": 1,
        "description": "Бесплатные занятия по государственному социальному "
        "заказу: дефектолог, логопед, работа с родителями. Нужна очередь и "
        "заключение ПМПК.",
        "methods": ["defect", "speech", "parent"],
    },
    {
        "provider_type": "doctor",
        "name": "Ахметова Айгуль (тестовая запись)",
        "specialty": "Невролог",
        "city": "Шымкент",
        "district": "Аль-Фарабийский район",
        "address": "ул. Демонстрационная, 18",
        "phone": "+7 700 000 00 05",
        "whatsapp": "+7 700 000 00 05",
        "website": "",
        "instagram": "",
        "age_from": 0,
        "age_to": 18,
        "price_from": 10000,
        "price_to": 10000,
        "pricing": "paid",
        "has_state_funding": 0,
        "description": "Детский невролог. Консультация, наблюдение, "
        "рекомендации по программе помощи и сопровождению ребёнка.",
        "methods": ["parent"],
    },
    {
        "provider_type": "doctor",
        "name": "Сериков Данияр (тестовая запись)",
        "specialty": "Психиатр",
        "city": "Алматы",
        "district": "Медеуский район",
        "address": "ул. Учебная, 90",
        "phone": "+7 700 000 00 06",
        "whatsapp": "",
        "website": "",
        "instagram": "",
        "age_from": 2,
        "age_to": 18,
        "price_from": 15000,
        "price_to": 20000,
        "pricing": "paid",
        "has_state_funding": 0,
        "description": "Детский психиатр. Диагностика РАС, консультации семьи, "
        "помощь в оформлении документов для ПМПК.",
        "methods": ["parent"],
    },
    {
        "provider_type": "specialist",
        "name": "Кошербаева Динара (тестовая запись)",
        "specialty": "ABA-терапист",
        "city": "Караганда",
        "district": "район имени Казыбек би",
        "address": "выезд на дом и онлайн",
        "phone": "+7 700 000 00 07",
        "whatsapp": "+7 700 000 00 07",
        "website": "",
        "instagram": "@example_aba",
        "age_from": 2,
        "age_to": 9,
        "price_from": 9000,
        "price_to": 12000,
        "pricing": "paid",
        "has_state_funding": 0,
        "description": "Индивидуальная программа ABA, супервизия занятий, "
        "обучение родителей работе дома.",
        "methods": ["aba", "parent", "pecs"],
    },
    {
        "provider_type": "specialist",
        "name": "Ибраева Жанна (тестовая запись)",
        "specialty": "Логопед",
        "city": "Актобе",
        "district": "",
        "address": "ул. Тестовая, 5, кабинет 2",
        "phone": "+7 700 000 00 08",
        "whatsapp": "+7 700 000 00 08",
        "website": "",
        "instagram": "",
        "age_from": 3,
        "age_to": 14,
        "price_from": 5000,
        "price_to": 8000,
        "pricing": "paid",
        "has_state_funding": 0,
        "description": "Логопед-дефектолог. Запуск речи, альтернативная "
        "коммуникация с карточками, домашние задания для семьи.",
        "methods": ["speech", "pecs", "defect"],
    },
    {
        "provider_type": "specialist",
        "name": "Нурланов Арман (тестовая запись)",
        "specialty": "Эрготерапевт",
        "city": "Павлодар",
        "district": "",
        "address": "ул. Показательная, 22",
        "phone": "+7 700 000 00 09",
        "whatsapp": "+7 700 000 00 09",
        "website": "",
        "instagram": "@example_ergo",
        "age_from": 2,
        "age_to": 12,
        "price_from": 7000,
        "price_to": 9000,
        "pricing": "paid",
        "has_state_funding": 0,
        "description": "Эрготерапия: бытовые навыки, мелкая моторика, "
        "подготовка руки к письму, работа в сенсорном зале.",
        "methods": ["ergo", "si", "adaptive_pe"],
    },
    {
        "provider_type": "specialist",
        "name": "Тулегенова Сауле (тестовая запись)",
        "specialty": "Остеопат",
        "city": "Алматы",
        "district": "Ауэзовский район",
        "address": "ул. Условная, 14",
        "phone": "+7 700 000 00 10",
        "whatsapp": "+7 700 000 00 10",
        "website": "",
        "instagram": "",
        "age_from": 0,
        "age_to": 16,
        "price_from": 15000,
        "price_to": 18000,
        "pricing": "paid",
        "has_state_funding": 0,
        "description": "Остеопатия и краниосакральные техники. Запись "
        "добавлена, чтобы показать метку уровня доказательности в карточке.",
        "methods": ["osteo", "cranio"],
    },
    {
        "provider_type": "center",
        "name": "Конно-спортивный клуб «Демо-Тулпар» (тестовая запись)",
        "specialty": "",
        "city": "Тараз",
        "district": "",
        "address": "загородная трасса, 4 км",
        "phone": "+7 700 000 00 11",
        "whatsapp": "+7 700 000 00 11",
        "website": "",
        "instagram": "@example_hippo",
        "age_from": 4,
        "age_to": 16,
        "price_from": 6000,
        "price_to": 6000,
        "pricing": "paid",
        "has_state_funding": 0,
        "description": "Занятия с лошадьми и адаптивная физкультура для детей "
        "с особенностями развития.",
        "methods": ["hippo", "adaptive_pe", "art"],
    },
    {
        "provider_type": "center",
        "name": "Ресурсный центр «Отбасы-Демо» (тестовая запись)",
        "specialty": "",
        "city": "Усть-Каменогорск",
        "district": "",
        "address": "ул. Семейная, 8",
        "phone": "+7 700 000 00 12",
        "whatsapp": "+7 700 000 00 12",
        "website": "example-family.kz",
        "instagram": "",
        "age_from": 1,
        "age_to": 7,
        "price_from": None,
        "price_to": None,
        "pricing": "free",
        "has_state_funding": 1,
        "description": "Бесплатные группы раннего вмешательства, занятия с "
        "дефектологом и логопедом, школа для родителей.",
        "methods": ["parent", "defect", "speech", "art"],
    },
]

# Отзывы для проверки расчёта оценки и модерации.
TEST_REVIEWS = [
    (1, "Айнур", 5, "Ходим полгода, ребёнок стал больше говорить. Специалисты "
        "подробно объясняют, что делать дома.", "published"),
    (1, "Марат", 4, "Хороший центр, но записаться на удобное время сложно.",
        "published"),
    (2, "Гульмира", 4, "Сыну нравятся занятия в сенсорном зале, логопед "
        "внимательный.", "published"),
    (3, "Асем", 5, "Помогли с диагностикой и составили понятный план помощи.",
        "published"),
    (4, "Динара", 5, "Бесплатные занятия, очередь ждали два месяца, но "
        "результат есть.", "published"),
    (7, "Ольга", 5, "Программа ABA расписана по шагам, каждую неделю видим "
        "прогресс.", "published"),
    (8, "Бекзат", 3, "Логопед хороший, но кабинет далеко от центра города.",
        "published"),
    (10, "Аноним", 2, "Ходили три месяца, изменений не заметили.", "pending"),
    (2, "Сергей", 5, "Отзыв на модерации для проверки админки.", "pending"),
]


def seed_if_empty() -> None:
    with db_session() as conn:
        if not crud.list_methods(conn):
            for order, (code, name, level, description) in enumerate(
                DEFAULT_METHODS, start=1
            ):
                crud.create_method(
                    conn,
                    {
                        "code": code,
                        "name": name,
                        "description": description,
                        "evidence_level": level,
                        "sort_order": order,
                    },
                )

        already_seeded = conn.execute(
            "SELECT COUNT(*) AS n FROM providers"
        ).fetchone()["n"]
        if already_seeded:
            return

        method_ids = {
            row["code"]: row["id"] for row in crud.list_methods(conn)
        }
        for item in TEST_PROVIDERS:
            data = {key: value for key, value in item.items() if key != "methods"}
            data["is_test"] = 1
            crud.create_provider(
                conn,
                data,
                [method_ids[code] for code in item["methods"] if code in method_ids],
            )

        for provider_id, author, rating, text, status in TEST_REVIEWS:
            review_id = crud.create_review(
                conn,
                {
                    "provider_id": provider_id,
                    "author_name": author,
                    "rating": rating,
                    "text": text,
                    "author_ip": "seed",
                },
            )
            if status != "pending":
                crud.set_review_status(conn, review_id, status)
