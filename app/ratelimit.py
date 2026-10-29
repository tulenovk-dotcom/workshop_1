"""Ограничение частоты для кнопок связи.

Зачем: номер телефона и ссылку в WhatsApp сайт отдаёт только по нажатию.
Человек нажимает несколько раз за визит, а программа-сборщик - сотни раз
подряд. Счётчик ниже пропускает первых и останавливает вторых.

Устройство простое и без зависимостей: в памяти процесса для каждого адреса
хранится время последних обращений за окно. Перезапуск сайта счётчик
обнуляет - это не страшно, сборщик просто упрётся в лимит заново.
Сами адреса нигде не сохраняются и в базу не попадают.
"""

import threading
import time

CONTACT_WINDOW_SECONDS = 60
# 30 нажатий в минуту с одного адреса. Человеку хватает с большим запасом,
# даже если за одним адресом сидят многие (мобильный оператор, офис).
CONTACT_MAX_HITS = 30


class RateLimiter:
    def __init__(self, max_hits: int, window_seconds: float, clock=time.monotonic):
        self.max_hits = max_hits
        self.window = window_seconds
        self._clock = clock
        self._hits = {}
        self._lock = threading.Lock()
        self._calls = 0

    def allow(self, key: str) -> bool:
        """Отметить обращение и ответить, укладывается ли оно в лимит."""
        now = self._clock()
        with self._lock:
            recent = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(recent) >= self.max_hits:
                self._hits[key] = recent
                return False
            recent.append(now)
            self._hits[key] = recent
            self._calls += 1
            if self._calls % 500 == 0:
                self._forget_old(now)
            return True

    def _forget_old(self, now: float) -> None:
        # Чтобы память не росла: адреса без свежих обращений выбрасываем.
        stale = [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]
        for key in stale:
            del self._hits[key]


contact_limiter = RateLimiter(CONTACT_MAX_HITS, CONTACT_WINDOW_SECONDS)
