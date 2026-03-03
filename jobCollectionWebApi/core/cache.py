from functools import wraps
import json
import hashlib
from typing import Optional, Callable, Any
from fastapi import Request, Response
from common.databases.RedisManager import redis_manager
from jobCollectionWebApi.config import settings
import inspect
from core.logger import sys_logger as logger

import random
import asyncio
from redis.exceptions import LockError


def _params_to_dict(v: Any) -> Any:
    """递归将对象转换为可序列化的字典/列表"""
    # 1. Pydantic 模型
    if hasattr(v, 'model_dump'):
        return v.model_dump()
    if hasattr(v, 'dict') and callable(getattr(v, 'dict')):
        return v.dict()
    
    # 2. 字典
    if isinstance(v, dict):
        return {k: _params_to_dict(val) for k, val in v.items()}
    
    # 3. 列表/元组
    if isinstance(v, (list, tuple)):
        return [_params_to_dict(item) for item in v]
    
    # 4. 普通对象 (有 __dict__)，排除 FastAPI 特殊对象
    if hasattr(v, '__dict__'):
        d = {}
        for attr, val in v.__dict__.items():
            if not attr.startswith('_'): # 忽略私有属性
                 d[attr] = _params_to_dict(val)
        return d
        
    # 5. 基本类型直接返回，其他转字符串
    if isinstance(v, (int, float, bool, type(None))):
        return v
    
    return str(v)

def cache(expire: int = None, key_prefix: str = ""):
    """
    Redis 缓存装饰器
    :param expire: 过期时间 (秒)，默认使用配置的 REDIS_CACHE_EXPIRE
    :param key_prefix: 键前缀，如果不指定则使用函数名
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                # 1. 生成 Cache Key
                # 获取函数名作为默认前缀
                prefix = key_prefix or func.__name__
                
                # 提取查询参数
                # 我们假设这是 FastAPI 端点，kwargs 中包含依赖项和查询参数
                # 排除 Request, Response, BackgroundTasks, Session 等对象
                cache_kwargs = {}
                for k, v in kwargs.items():
                    # 简单过滤掉不可序列化的复杂对象 (大致判断)
                    if k in ['db', 'current_user', 'background_tasks', 'request', 'response', 'redis']:
                        continue
                    # 检查是否是 SQLAlchemy Session 或其他忽略对象
                    if hasattr(v, '__dict__') and not hasattr(v, 'model_dump') and not hasattr(v, 'dict'):
                        # 简单的启发式：如果看起来像服务类或数据库会话，则跳过
                        class_name = v.__class__.__name__
                        if 'Session' in class_name or 'Service' in class_name:
                            continue

                    # 使用递归辅助函数处理
                    cache_kwargs[k] = _params_to_dict(v)
                
                # 序列化参数生成 Hash
                params_str = json.dumps(cache_kwargs, sort_keys=True, default=str)
                params_hash = hashlib.md5(params_str.encode()).hexdigest()
                
                cache_key = f"api_cache:{prefix}:{params_hash}"
                
                # 2. 尝试获取缓存 (First Check)
                cached_data = await redis_manager.get_cache(cache_key)
                if cached_data:
                    return cached_data
                
                # 3. 缓存击穿保护：获取互斥锁
                # 锁的 key 应该以此 cache_key 为基础
                lock_key = f"lock:{cache_key}"
                
                # 使用 redis-py 的 Lock 对象
                # blocking_timeout: 等待锁的最大时间
                # timeout: 锁的持有时间（防止死锁）
                try:
                    # 注意：redis_manager.redis_client 是 redis.asyncio.Redis 实例
                    async with redis_manager.redis_client.lock(
                        redis_manager.make_key(lock_key), 
                        timeout=20, 
                        blocking_timeout=5
                    ):
                        # Double Check (双重检查)
                        # 在等待锁的过程中，可能别的线程已经把缓存写进去了
                        cached_data = await redis_manager.get_cache(cache_key)
                        if cached_data:
                            return cached_data

                        # 4. 执行原函数 (DB Query)
                        result = await func(*args, **kwargs)
                        
                        # 5. 存储缓存
                        cache_value = result
                        if hasattr(result, 'model_dump'):
                            cache_value = result.model_dump(mode='json')
                        elif hasattr(result, 'dict'):
                            cache_value = result.dict()
                        elif isinstance(result, list):
                             # 如果是 list[Model]
                             cache_value = [
                                 item.model_dump(mode='json') if hasattr(item, 'model_dump') else (item.dict() if hasattr(item, 'dict') else item)
                                 for item in result
                             ]
                        
                        # 计算 TTL Jitter (随机抖动)
                        # 在基础过期时间上增加 -10% 到 +10% 的随机值，防止雪崩
                        base_ttl = expire if expire is not None else settings.REDIS_CACHE_EXPIRE
                        jitter = int(base_ttl * 0.1)
                        final_ttl = base_ttl + random.randint(-jitter, jitter)
                        
                        await redis_manager.set_cache(cache_key, cache_value, final_ttl)
                        
                        return result
                        
                except LockError:
                    # 获取锁失败（比如 waiting timeout）
                    # 降级策略：直接查库（或者报错 429，这里选择查库但打印警告）
                    logger.warning(f"Failed to acquire lock for {cache_key}, skipping cache and executing directly.")
                    return await func(*args, **kwargs)
                
            except Exception as e:
                # 缓存出错不应影响主流程
                logger.error(f"Cache decorator error: {e}")
                return await func(*args, **kwargs)
                
        return wrapper
    return decorator
