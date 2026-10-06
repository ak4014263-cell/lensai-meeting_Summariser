"""Caching utilities for the AI Meeting Assistant.

Provides multi-level caching:
- In-memory cache for frequent lookups
- Optional Redis cache for distributed systems
- Smart cache invalidation
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import time
from typing import Any, Callable, Optional, Union
from datetime import datetime, timedelta

logger = logging.getLogger("lensai_bot.cache")


class InMemoryCache:
    """Simple in-memory LRU cache with TTL support."""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
        self.max_size = max_size
        self.default_ttl = default_ttl  # seconds
        self._cache: dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_time)
        self._access_times: dict[str, float] = {}  # key -> last_access_time
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache, returns None if not found or expired."""
        if key not in self._cache:
            return None
        
        value, expiry = self._cache[key]
        
        # Check expiry
        if time.time() > expiry:
            self._delete(key)
            return None
        
        # Update access time for LRU
        self._access_times[key] = time.time()
        logger.debug(f"Cache hit: {key}")
        return value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with optional TTL."""
        if ttl is None:
            ttl = self.default_ttl
        
        expiry = time.time() + ttl
        
        # Evict oldest if at capacity
        if len(self._cache) >= self.max_size and key not in self._cache:
            self._evict_lru()
        
        self._cache[key] = (value, expiry)
        self._access_times[key] = time.time()
        logger.debug(f"Cache set: {key} (TTL: {ttl}s)")
    
    def delete(self, key: str) -> None:
        """Remove key from cache."""
        self._delete(key)
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._access_times.clear()
        logger.info("Cache cleared")
    
    def _delete(self, key: str) -> None:
        """Internal delete helper."""
        self._cache.pop(key, None)
        self._access_times.pop(key, None)
    
    def _evict_lru(self) -> None:
        """Evict least recently used item."""
        if not self._access_times:
            return
        
        lru_key = min(self._access_times.items(), key=lambda x: x[1])[0]
        self._delete(lru_key)
        logger.debug(f"Evicted LRU key: {lru_key}")
    
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        # Clean expired entries
        now = time.time()
        expired = [k for k, (_, expiry) in self._cache.items() if now > expiry]
        for k in expired:
            self._delete(k)
        
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "utilization": f"{len(self._cache) / self.max_size * 100:.1f}%",
        }


class RedisCache:
    """Redis-backed cache for distributed deployments (optional)."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379", default_ttl: int = 3600):
        self.default_ttl = default_ttl
        self.redis_url = redis_url
        self._client = None
    
    def _get_client(self):
        """Lazy load Redis client."""
        if self._client is None:
            try:
                import redis
                self._client = redis.from_url(self.redis_url, decode_responses=True)
                logger.info(f"Connected to Redis at {self.redis_url}")
            except ImportError:
                logger.warning("redis package not installed, falling back to in-memory cache")
                return None
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}, using in-memory cache")
                return None
        return self._client
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from Redis cache."""
        client = self._get_client()
        if not client:
            return None
        
        try:
            value = client.get(key)
            if value:
                logger.debug(f"Redis cache hit: {key}")
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in Redis cache."""
        client = self._get_client()
        if not client:
            return
        
        if ttl is None:
            ttl = self.default_ttl
        
        try:
            serialized = json.dumps(value)
            client.setex(key, ttl, serialized)
            logger.debug(f"Redis cache set: {key} (TTL: {ttl}s)")
        except Exception as e:
            logger.error(f"Redis set error: {e}")
    
    def delete(self, key: str) -> None:
        """Delete key from Redis."""
        client = self._get_client()
        if not client:
            return
        
        try:
            client.delete(key)
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
    
    def clear(self) -> None:
        """Clear all keys (use with caution!)."""
        client = self._get_client()
        if not client:
            return
        
        try:
            client.flushdb()
            logger.info("Redis cache cleared")
        except Exception as e:
            logger.error(f"Redis clear error: {e}")


# Global cache instance
_cache: Optional[Union[InMemoryCache, RedisCache]] = None


def get_cache() -> Union[InMemoryCache, RedisCache]:
    """Get the global cache instance."""
    global _cache
    if _cache is None:
        # Try Redis first, fall back to in-memory
        import os
        redis_url = os.getenv("REDIS_URL")
        
        if redis_url:
            _cache = RedisCache(redis_url=redis_url)
        else:
            _cache = InMemoryCache()
            logger.info("Using in-memory cache (set REDIS_URL for distributed cache)")
    
    return _cache


def cache_key(*args, **kwargs) -> str:
    """Generate a cache key from arguments."""
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_str = ":".join(key_parts)
    
    # Hash if too long
    if len(key_str) > 200:
        return hashlib.md5(key_str.encode()).hexdigest()
    
    return key_str


def cached(
    ttl: int = 3600,
    key_prefix: Optional[str] = None,
    use_kwargs: bool = True,
):
    """
    Decorator to cache function results.
    
    Args:
        ttl: Time to live in seconds
        key_prefix: Optional prefix for cache keys
        use_kwargs: Whether to include kwargs in cache key
    
    Usage:
        @cached(ttl=3600, key_prefix="meeting")
        def get_meeting_summary(meeting_id: int):
            # ... expensive operation ...
            return summary
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            key_parts = [key_prefix] if key_prefix else []
            key_parts.append(func.__name__)
            
            # Add args to key
            key_parts.extend(str(arg) for arg in args)
            
            # Add kwargs to key if enabled
            if use_kwargs:
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            
            key = cache_key(*key_parts)
            
            # Try to get from cache
            cache = get_cache()
            cached_value = cache.get(key)
            
            if cached_value is not None:
                return cached_value
            
            # Cache miss - execute function
            logger.debug(f"Cache miss: {key}")
            result = func(*args, **kwargs)
            
            # Store in cache
            cache.set(key, result, ttl=ttl)
            
            return result
        
        return wrapper
    return decorator


def invalidate_cache(pattern: str) -> None:
    """
    Invalidate cache entries matching a pattern.
    
    For in-memory cache, this is a simple clear.
    For Redis, this supports pattern matching.
    
    Args:
        pattern: Cache key pattern (e.g., "meeting:123:*")
    """
    cache = get_cache()
    
    if isinstance(cache, RedisCache):
        client = cache._get_client()
        if client:
            try:
                keys = client.keys(pattern)
                if keys:
                    client.delete(*keys)
                    logger.info(f"Invalidated {len(keys)} cache keys matching: {pattern}")
            except Exception as e:
                logger.error(f"Cache invalidation error: {e}")
    else:
        # In-memory cache - clear all (no pattern matching)
        logger.info(f"Clearing in-memory cache (pattern: {pattern})")
        cache.clear()


class CacheManager:
    """High-level cache management with domain-specific helpers."""
    
    @staticmethod
    def cache_meeting_summary(meeting_id: int, summary: dict) -> None:
        """Cache a meeting summary."""
        key = f"meeting:{meeting_id}:summary"
        get_cache().set(key, summary, ttl=7200)  # 2 hours
    
    @staticmethod
    def get_meeting_summary(meeting_id: int) -> Optional[dict]:
        """Get cached meeting summary."""
        key = f"meeting:{meeting_id}:summary"
        return get_cache().get(key)
    
    @staticmethod
    def cache_transcript(meeting_id: int, transcript: str) -> None:
        """Cache a meeting transcript."""
        key = f"meeting:{meeting_id}:transcript"
        get_cache().set(key, transcript, ttl=7200)  # 2 hours
    
    @staticmethod
    def get_transcript(meeting_id: int) -> Optional[str]:
        """Get cached transcript."""
        key = f"meeting:{meeting_id}:transcript"
        return get_cache().get(key)
    
    @staticmethod
    def cache_user_meetings(user_id: int, meetings: list) -> None:
        """Cache user's meeting list."""
        key = f"user:{user_id}:meetings"
        get_cache().set(key, meetings, ttl=300)  # 5 minutes
    
    @staticmethod
    def get_user_meetings(user_id: int) -> Optional[list]:
        """Get cached user meetings."""
        key = f"user:{user_id}:meetings"
        return get_cache().get(key)
    
    @staticmethod
    def invalidate_meeting(meeting_id: int) -> None:
        """Invalidate all cache entries for a meeting."""
        patterns = [
            f"meeting:{meeting_id}:*",
        ]
        for pattern in patterns:
            invalidate_cache(pattern)
    
    @staticmethod
    def invalidate_user(user_id: int) -> None:
        """Invalidate all cache entries for a user."""
        invalidate_cache(f"user:{user_id}:*")


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    # Test in-memory cache
    cache = InMemoryCache()
    
    cache.set("test:key", {"data": "value"}, ttl=60)
    print(cache.get("test:key"))  # {'data': 'value'}
    
    print(cache.stats())  # {'size': 1, 'max_size': 1000, 'utilization': '0.1%'}
    
    # Test decorator
    @cached(ttl=10, key_prefix="example")
    def expensive_function(x: int, y: int):
        print("Computing...")
        time.sleep(0.1)
        return x + y
    
    print(expensive_function(1, 2))  # Computing... 3
    print(expensive_function(1, 2))  # 3 (from cache, no "Computing...")
