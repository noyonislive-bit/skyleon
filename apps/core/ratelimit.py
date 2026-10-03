"""Tiny fixed-window rate limiter backed by Django's cache (database cache on shared hosting)."""

from django.core.cache import cache


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def hit(key: str, limit: int, window_seconds: int) -> bool:
    """Register one hit. Returns True when the caller is now over the limit."""
    cache_key = f"rl:{key}"
    added = cache.add(cache_key, 1, timeout=window_seconds)
    if added:
        return False
    try:
        count = cache.incr(cache_key)
    except ValueError:  # expired between add and incr
        cache.set(cache_key, 1, timeout=window_seconds)
        return False
    return count > limit


def is_limited(key: str, limit: int) -> bool:
    return (cache.get(f"rl:{key}") or 0) >= limit


def reset(key: str) -> None:
    cache.delete(f"rl:{key}")
