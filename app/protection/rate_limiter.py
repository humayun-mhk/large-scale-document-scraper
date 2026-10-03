import time
import redis

from app.config import settings


class RedisRateLimiter:
    """
    Simple global fixed-window limiter shared by every Celery worker.
    Example: max_requests=3, window_seconds=1 => max 3 requests/sec total.
    """

    def __init__(self, key="scraper:global_rate", max_requests=3, window_seconds=1):
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.key = key
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def wait(self):
        while True:
            pipe = self.client.pipeline()
            pipe.incr(self.key, 1)
            pipe.ttl(self.key)
            count, ttl = pipe.execute()

            if count == 1:
                self.client.expire(self.key, self.window_seconds)
                return

            if count <= self.max_requests:
                return

            sleep_for = max(ttl, 1)
            time.sleep(sleep_for)
