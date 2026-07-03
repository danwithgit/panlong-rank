from __future__ import annotations

import json
import time
from typing import Any, Optional

from app.config import Settings


class CacheBackend:
    def get_json(self, key: str) -> Optional[Any]:
        raise NotImplementedError

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class MemoryTTLCache(CacheBackend):
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, Any]] = {}

    def get_json(self, key: str) -> Optional[Any]:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._items.pop(key, None)
            return None
        return value

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._items[key] = (time.time() + ttl_seconds, value)

    def delete(self, key: str) -> None:
        self._items.pop(key, None)


class RedisCache(CacheBackend):
    def __init__(self, redis_url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def get_json(self, key: str) -> Optional[Any]:
        value = self._client.get(key)
        if value is None:
            return None
        return json.loads(value)

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False, default=str))

    def delete(self, key: str) -> None:
        self._client.delete(key)


_memory_cache = MemoryTTLCache()


def get_cache(settings: Settings) -> CacheBackend:
    if settings.redis_url:
        try:
            return RedisCache(settings.redis_url)
        except Exception:
            return _memory_cache
    return _memory_cache
