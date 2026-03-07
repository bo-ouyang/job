import hashlib
import inspect
import json
import random
from functools import wraps
from typing import Any, Callable

from common.databases.RedisManager import redis_manager
from jobCollectionWebApi.config import settings
from core.logger import sys_logger as logger


def _params_to_dict(value: Any) -> Any:
    """Recursively convert objects to JSON-serializable structures."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict") and callable(getattr(value, "dict")):
        return value.dict()

    if isinstance(value, dict):
        return {k: _params_to_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_params_to_dict(v) for v in value]
    if isinstance(value, (int, float, bool, str, type(None))):
        return value

    if hasattr(value, "__dict__"):
        # Keep public attrs only; avoid huge private/runtime objects.
        return {
            k: _params_to_dict(v)
            for k, v in value.__dict__.items()
            if not k.startswith("_")
        }

    return str(value)


def _should_skip_cache_arg(name: str, value: Any) -> bool:
    if name in {
        "self",
        "cls",
        "db",
        "request",
        "response",
        "background_tasks",
        "current_user",
        "redis",
    }:
        return True

    class_name = value.__class__.__name__
    if any(token in class_name for token in ("Session", "Request", "Response", "BackgroundTasks")):
        return True

    return False


def cache(expire: int | None = None, key_prefix: str = ""):
    def decorator(func: Callable):
        signature = inspect.signature(func)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                prefix = key_prefix or func.__name__

                # Bind args + kwargs, so positional params also affect cache key.
                bound = signature.bind_partial(*args, **kwargs)
                bound.apply_defaults()

                cache_params: dict[str, Any] = {}
                for name, value in bound.arguments.items():
                    if _should_skip_cache_arg(name, value):
                        continue
                    cache_params[name] = _params_to_dict(value)

                params_str = json.dumps(cache_params, sort_keys=True, default=str, ensure_ascii=False)
                params_hash = hashlib.md5(params_str.encode("utf-8")).hexdigest()
                cache_key = f"api_cache:{prefix}:{params_hash}"

                cached_data = await redis_manager.get_cache(cache_key)
                if cached_data is not None:
                    logger.debug(f"Cache hit: {cache_key}")
                    return cached_data

                lock_key = f"lock:{cache_key}"
                async with redis_manager.redis_client.lock(
                    redis_manager.make_key(lock_key),
                    timeout=20,
                    blocking_timeout=5,
                ):
                    # Double check after acquiring lock.
                    cached_data = await redis_manager.get_cache(cache_key)
                    if cached_data is not None:
                        logger.debug(f"Cache hit(after-lock): {cache_key}")
                        return cached_data

                    result = await func(*args, **kwargs)

                    cache_value = result
                    if hasattr(result, "model_dump"):
                        cache_value = result.model_dump(mode="json")
                    elif hasattr(result, "dict"):
                        cache_value = result.dict()
                    elif isinstance(result, list):
                        cache_value = [
                            item.model_dump(mode="json")
                            if hasattr(item, "model_dump")
                            else (item.dict() if hasattr(item, "dict") else item)
                            for item in result
                        ]

                    base_ttl = expire if expire is not None else settings.REDIS_CACHE_EXPIRE
                    if base_ttl > 0:
                        jitter = max(1, int(base_ttl * 0.1))
                        final_ttl = base_ttl + random.randint(-jitter, jitter)
                    else:
                        final_ttl = base_ttl

                    await redis_manager.set_cache(cache_key, cache_value, final_ttl)
                    logger.debug(f"Cache set: {cache_key}, ttl={final_ttl}")
                    return result
            except Exception as exc:
                # Cache errors should never break business flow.
                logger.error(f"Cache decorator error in {func.__name__}: {exc}")
                return await func(*args, **kwargs)

        return wrapper

    return decorator
