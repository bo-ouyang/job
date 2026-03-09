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
    """递归将参数转换为可 JSON 序列化结构，用于生成稳定缓存键。"""
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
        # 仅保留公开属性，跳过私有/运行时字段，避免缓存键不稳定。
        return {
            k: _params_to_dict(v)
            for k, v in value.__dict__.items()
            if not k.startswith("_")
        }

    return str(value)


def _should_skip_cache_arg(name: str, value: Any) -> bool:
    # 这些参数属于请求上下文/运行时对象，不应参与缓存键计算。
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
    # 兜底跳过：避免把框架对象/会话对象哈希进缓存键。
    if any(token in class_name for token in ("Session", "Request", "Response", "BackgroundTasks")):
        return True

    return False


def cache(expire: int | None = None, key_prefix: str = ""):
    """
    通用异步缓存装饰器。

    执行流程：
    1) 根据函数参数构建确定性缓存键；
    2) 先读缓存；
    3) 未命中时使用分布式锁（single-flight）防击穿；
    4) 加锁后再次检查缓存；
    5) 执行函数并序列化结果，按带抖动的 TTL 回写缓存；
    6) 缓存链路异常时降级直执行业务逻辑。
    """
    def decorator(func: Callable):
        # 预先缓存函数签名，统一绑定位置参数和关键字参数。
        signature = inspect.signature(func)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                prefix = key_prefix or func.__name__

                # 绑定 args + kwargs，确保位置参数也参与缓存键哈希。
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

                # 第一次读缓存：热点键直接返回，成本最低。
                cached_data = await redis_manager.get_cache(cache_key)
                if cached_data is not None:
                    logger.debug(f"Cache hit: {cache_key}")
                    return cached_data

                # 按 key 加锁，防止缓存失效瞬间的并发击穿。
                lock_key = f"lock:{cache_key}"
                async with redis_manager.redis_client.lock(
                    redis_manager.make_key(lock_key),
                    timeout=20,
                    blocking_timeout=5,
                ):
                    # 双重检查：可能已有其他请求在等待期间完成了回填。
                    cached_data = await redis_manager.get_cache(cache_key)
                    if cached_data is not None:
                        logger.debug(f"Cache hit(after-lock): {cache_key}")
                        return cached_data

                    # 仅由拿到锁的请求执行一次真实业务。
                    result = await func(*args, **kwargs)

                    # 结果标准化为可序列化结构，再写入缓存。
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
                        # TTL 增加 ±10% 抖动，降低同秒过期引发的雪崩风险。
                        jitter = max(1, int(base_ttl * 0.1))
                        final_ttl = base_ttl + random.randint(-jitter, jitter)
                    else:
                        final_ttl = base_ttl

                    await redis_manager.set_cache(cache_key, cache_value, final_ttl)
                    logger.debug(f"Cache set: {cache_key}, ttl={final_ttl}")
                    return result
            except Exception as exc:
                # 失败开放：缓存异常不影响主业务返回。
                logger.error(f"Cache decorator error in {func.__name__}: {exc}")
                return await func(*args, **kwargs)

        return wrapper

    return decorator
