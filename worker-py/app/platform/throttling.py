"""Atomic shared sliding-window login limits; fail closed in production."""

import os
import secrets
import time
from collections import defaultdict, deque
from functools import lru_cache
from fastapi import HTTPException
from redis import Redis, RedisError
from .security import digest

_local_attempts = defaultdict(deque)
_WINDOW = 300
_LIMIT = 15
_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - tonumber(ARGV[1]))
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[1])
return 1
"""


@lru_cache(maxsize=4)
def _redis(url):
    return Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)


def throttle(request, email=None, *, namespace="login"):
    keys = ["ip:" + (request.client.host if request.client else "unknown")]
    if email:
        keys.append("account:" + email.lower().strip())
    url = os.getenv("REDIS_URL")
    if url:
        try:
            for key in keys:
                if not _redis(url).eval(
                    _SCRIPT,
                    1,
                    "pulsemux:" + namespace + ":" + digest(key),
                    _WINDOW,
                    _LIMIT,
                    secrets.token_hex(16),
                ):
                    raise HTTPException(
                        429,
                        "Too many sign-in attempts. Try again in five minutes.",
                        headers={"Retry-After": str(_WINDOW)},
                    )
            return
        except RedisError:
            if os.getenv("PLATFORM_ENV") == "production":
                raise HTTPException(
                    503, "Sign-in is temporarily unavailable. Try again shortly."
                )
    if os.getenv("PLATFORM_ENV") == "production":
        raise HTTPException(503, "Shared authentication rate limiting is unavailable")
    now = time.monotonic()
    for key in keys:
        attempts = _local_attempts[namespace + ":" + key]
        while attempts and attempts[0] <= now - _WINDOW:
            attempts.popleft()
        if len(attempts) >= _LIMIT:
            raise HTTPException(
                429, "Too many sign-in attempts. Try again in five minutes."
            )
        attempts.append(now)
    if len(_local_attempts) > 10000:
        for key in list(_local_attempts):
            if not _local_attempts[key] or _local_attempts[key][-1] < now - _WINDOW:
                del _local_attempts[key]
