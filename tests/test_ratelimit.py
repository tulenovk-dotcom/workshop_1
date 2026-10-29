import unittest

from app.ratelimit import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class RateLimiterTest(unittest.TestCase):
    def test_blocks_after_limit_and_recovers(self):
        clock = FakeClock()
        limiter = RateLimiter(3, 60, clock=clock)
        self.assertTrue(all(limiter.allow("a") for _ in range(3)))
        self.assertFalse(limiter.allow("a"))
        # Другой адрес не страдает.
        self.assertTrue(limiter.allow("b"))
        # Через минуту снова можно.
        clock.now = 61
        self.assertTrue(limiter.allow("a"))


if __name__ == "__main__":
    unittest.main()
