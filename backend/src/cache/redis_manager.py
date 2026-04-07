"""Redis cache manager with async connection pool and decorator."""
import asyncio
import functools
import hashlib
import json
import logging
from typing import Any, Callable, Optional

import redis.asyncio as aioredis
from redis.asyncio import ConnectionPool

from src.config import get_settings

logger = logging.getLogger(__name__)

NULL_SENTINEL = "__NULL__"


class RedisManager:
    """Async Redis manager with connection pool."""

    def __init__(self):
        self._settings = get_settings()
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        """Initialize async connection pool."""
        self._pool = ConnectionPool.from_url(
            self._settings.redis_url,
            max_connections=20,
            decode_responses=True,
        )
        self._client = aioredis.Redis(connection_pool=self._pool)
        await self._client.ping()
        logger.info(f"Redis connected: {self._settings.redis_host}:{self._settings.redis_port}")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
        if self._pool:
            await self._pool.aclose()

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("RedisManager not connected. Call connect() first.")
        return self._client

    # ── Core get/set helpers ─────────────────────────────────────────────────

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from Redis. Returns None on miss."""
        raw = await self.client.get(key)
        if raw is None:
            return None
        if raw == NULL_SENTINEL:
            return NULL_SENTINEL  # caller checks for this
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in Redis with optional TTL (seconds). ttl=-1 means no expiry."""
        if value is None:
            serialized = NULL_SENTINEL
        elif isinstance(value, str):
            serialized = value
        else:
            serialized = json.dumps(value, ensure_ascii=False, default=str)

        if ttl == -1 or ttl is None:
            await self.client.set(key, serialized)
        else:
            await self.client.setex(key, ttl, serialized)

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def flush_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern. Returns count deleted."""
        keys = await self.client.keys(pattern)
        if keys:
            return await self.client.delete(*keys)
        return 0

    async def flush_all(self) -> None:
        """Flush entire Redis DB (use with caution)."""
        await self.client.flushdb()

    # ── Key builders ─────────────────────────────────────────────────────────

    @staticmethod
    def arxiv_search_key(query: str, **params) -> str:
        h = hashlib.md5((query + str(sorted(params.items()))).encode()).hexdigest()
        return f"arxiv:query:{h}"

    @staticmethod
    def embedding_key(paper_id: str, chunk_idx: int) -> str:
        return f"embed:{paper_id}:{chunk_idx}"

    @staticmethod
    def llm_result_key(query: str, paper_ids: list[str]) -> str:
        combined = query + "|".join(sorted(paper_ids))
        h = hashlib.md5(combined.encode()).hexdigest()
        return f"llm:{h}"

    @staticmethod
    def session_history_key(session_id: str) -> str:
        return f"session:{session_id}:history"

    # ── Session helpers ───────────────────────────────────────────────────────

    async def get_session_history(self, session_id: str) -> list[dict]:
        key = self.session_history_key(session_id)
        raw = await self.get(key)
        if raw is None or raw == NULL_SENTINEL:
            return []
        return raw if isinstance(raw, list) else []

    async def append_session_message(
        self, session_id: str, role: str, content: str, ttl: int = 1800
    ) -> None:
        key = self.session_history_key(session_id)
        history = await self.get_session_history(session_id)
        history.append({"role": role, "content": content})
        await self.set(key, history, ttl=ttl)

    # ── Info ──────────────────────────────────────────────────────────────────

    async def info(self) -> dict:
        info = await self.client.info()
        return {
            "version": info.get("redis_version"),
            "used_memory_human": info.get("used_memory_human"),
            "connected_clients": info.get("connected_clients"),
            "total_commands_processed": info.get("total_commands_processed"),
            "keyspace_hits": info.get("keyspace_hits"),
            "keyspace_misses": info.get("keyspace_misses"),
        }


# ── Global singleton ─────────────────────────────────────────────────────────

_redis_manager: Optional[RedisManager] = None


def get_redis_manager() -> RedisManager:
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisManager()
    return _redis_manager


# ── Decorator ────────────────────────────────────────────────────────────────

def redis_cache(
    key_fn: Callable[..., str],
    ttl: Optional[int] = 3600,
    skip_null: bool = False,
):
    """Decorator for caching async function results in Redis.

    Usage:
        @redis_cache(key_fn=lambda q: f"mykey:{q}", ttl=600)
        async def expensive_fn(q: str) -> dict: ...
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            manager = get_redis_manager()
            cache_key = key_fn(*args, **kwargs)

            cached = await manager.get(cache_key)
            if cached is not None:
                if cached == NULL_SENTINEL and skip_null:
                    return None
                if cached != NULL_SENTINEL:
                    logger.debug(f"Cache HIT: {cache_key}")
                    return cached

            result = await func(*args, **kwargs)

            if result is None and not skip_null:
                await manager.set(cache_key, None, ttl=ttl)
            elif result is not None:
                await manager.set(cache_key, result, ttl=ttl)

            return result

        return wrapper

    return decorator
