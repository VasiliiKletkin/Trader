import contextlib
from collections.abc import Callable
from functools import wraps

from django.core.cache import cache

_CACHE_MISS = object()


def cached_method(timeout: int | Callable = 300):
    """Декоратор для кэширования результатов методов модели в Redis.

    Корректно кэширует None-значения.
    timeout — секунды (int) или callable(self) -> int.
    При недоступности Redis вызывает метод напрямую.

    Пример::

        @cached_method(timeout=3600)
        def get_candles_count(self) -> int:
            return self.candles.count()

        @cached_method(timeout=lambda self: self.get_timeframe_seconds())
        def get_last_candle(self): ...
    """

    def decorator(method):
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            key = f"{self.__class__.__name__}_{self.pk}_{method.__name__}"
            try:
                result = cache.get(key, _CACHE_MISS)
                if result is not _CACHE_MISS:
                    return result
            except Exception:
                pass

            result = method(self, *args, **kwargs)
            try:
                ttl = timeout(self) if callable(timeout) else timeout
                cache.set(key, result, timeout=ttl)
            except Exception:
                pass
            return result

        wrapper._cached_method = True
        return wrapper

    return decorator


def invalidate_cached_methods(instance) -> None:
    """Инвалидирует все @cached_method для данного экземпляра модели."""
    keys = [
        f"{instance.__class__.__name__}_{instance.pk}_{name}"
        for name in dir(instance.__class__)
        if getattr(getattr(instance.__class__, name, None), "_cached_method", False)
    ]
    if keys:
        with contextlib.suppress(Exception):
            cache.delete_many(keys)
