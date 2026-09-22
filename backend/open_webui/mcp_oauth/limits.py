"""Per-client-IP rate limits on the authorization server's unauthenticated routes.

Each limit is a fixed window: at most `limit` requests from one IP in each `window_seconds`. The
counter is in Redis when REDIS_URL is set, so replicas share it, and in this process otherwise. While
Redis cannot be reached, the process counter is used; one warning is logged when that starts and
one when Redis answers again.

The client IP is the address uvicorn reports for the connection. uvicorn runs with
--forwarded-allow-ips '*' (start.sh), so it takes that address from X-Forwarded-For when the header
is present, and a client that sends the header itself can change it.
"""

import asyncio
import logging
import threading
import time
from typing import Callable, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse

from open_webui.env import REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT, REDIS_URL

log = logging.getLogger(__name__)

KEY_PREFIX = "mcp-oauth:rate:"

# Requests per client IP per window.
REGISTER_LIMIT = 20
AUTHORIZE_LIMIT = 60
WINDOW_SECONDS = 60

# Largest number of counters the process keeps. Past it, counters of past windows are dropped,
# and then the oldest counters of the current window.
MAX_LOCAL_COUNTERS = 10_000

TOO_MANY_MESSAGE = "Too many requests from this address. Try again in a minute."


def redis_client_from_env():
    """A Redis client for REDIS_URL, or None when it is unset."""
    if not str(REDIS_URL or "").strip():
        return None
    from open_webui.utils.redis import get_redis_connection, get_sentinels_from_env

    return get_redis_connection(
        REDIS_URL, get_sentinels_from_env(REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT)
    )


class RateLimiter:
    def __init__(
        self,
        *,
        redis_client=None,
        window_seconds: int = WINDOW_SECONDS,
        clock: Callable[[], float] = time.time,
    ):
        self.redis = redis_client
        self.window_seconds = window_seconds
        self.clock = clock
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()
        # Whether the last Redis call failed, so an outage is logged when it starts and ends.
        self._redis_down = False

    def _window(self) -> int:
        return int(self.clock()) // self.window_seconds

    def seconds_left(self) -> int:
        """Whole seconds until the current window ends, at least 1."""
        return max(1, self.window_seconds - int(self.clock()) % self.window_seconds)

    def _count_locally(self, key: str, window: int) -> int:
        """Count in this process, keeping at most MAX_LOCAL_COUNTERS counters.

        When a new key would pass the cap, counters of past windows are dropped, then the oldest
        counters of the current window (a dict keeps insertion order). An evicted address starts
        again from zero.
        """
        with self._lock:
            if key not in self._counts and len(self._counts) >= MAX_LOCAL_COUNTERS:
                suffix = f":{window}"
                self._counts = {k: v for k, v in self._counts.items() if k.endswith(suffix)}
                while len(self._counts) >= MAX_LOCAL_COUNTERS:
                    del self._counts[next(iter(self._counts))]
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key]

    def _count_in_redis(self, key: str) -> int:
        """SET NX EX then INCR, in one MULTI/EXEC transaction, so a counter always has an expiry.

        SET NX creates the key at 0 with the window's expiry only when it does not exist, and INCR
        keeps an existing expiry, so later requests in the window do not extend it.
        """
        pipeline = self.redis.pipeline(transaction=True)
        pipeline.set(key, 0, ex=self.window_seconds, nx=True)
        pipeline.incr(key)
        _, count = pipeline.execute()
        return int(count)

    def hit(self, name: str, client_ip: str) -> int:
        """Count one request and return the count in the current window."""
        window = self._window()
        key = f"{KEY_PREFIX}{name}:{client_ip}:{window}"
        if self.redis is not None:
            try:
                count = self._count_in_redis(key)
            except Exception as error:
                if not self._redis_down:
                    self._redis_down = True
                    log.warning(
                        "Rate limit counter in Redis failed, counting in process until it "
                        "answers again: %s",
                        error,
                    )
            else:
                if self._redis_down:
                    self._redis_down = False
                    log.warning("Rate limit counter in Redis answers again")
                return count
        return self._count_locally(key, window)


class RateLimited:
    """ASGI wrapper that answers 429 when a client IP is over `limit` for `name`.

    OPTIONS requests (CORS preflights) are not counted.
    """

    def __init__(self, app, *, limiter: RateLimiter, name: str, limit: int):
        self.app = app
        self.limiter = limiter
        self.name = name
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        client_ip = _client_ip(Request(scope))
        count = await asyncio.to_thread(self.limiter.hit, self.name, client_ip)
        if count > self.limit:
            response = JSONResponse(
                {"error": "too_many_requests", "error_description": TOO_MANY_MESSAGE},
                status_code=429,
                headers={"Retry-After": str(self.limiter.seconds_left())},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _client_ip(request: Request) -> str:
    client: Optional[object] = request.client
    return getattr(client, "host", None) or "unknown"
