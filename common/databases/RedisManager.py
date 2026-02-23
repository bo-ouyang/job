import redis.asyncio as redis
import json
from typing import Optional, Any
from jobCollectionWebApi.config import settings

class RedisManager:
    """Redis 管理器 (Async)"""
    
    def __init__(self):
        # 使用 async connection pool
        self.pool = redis.ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            # max_connections=settings.REDIS_MAX_CONNECTIONS, # asyncio version manages this differently or same
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
            retry_on_timeout=settings.REDIS_RETRY_ON_TIMEOUT,
            decode_responses=True
        )
        self.redis_client = redis.Redis(connection_pool=self.pool)
    
    def make_key(self, key: str) -> str:
        """生成带前缀的键"""
        return f"{settings.REDIS_KEY_PREFIX}:{key}"
    
    async def set_cache(self, key: str, value: Any, expire: Optional[int] = None) -> bool:
        """设置缓存"""
        if expire is None:
            expire = settings.REDIS_CACHE_EXPIRE
        
        redis_key = self.make_key(key)
        serialized_value = json.dumps(value, ensure_ascii=False)
        return await self.redis_client.setex(redis_key, expire, serialized_value)
    
    async def get_cache(self, key: str) -> Optional[Any]:
        """获取缓存"""
        redis_key = self.make_key(key)
        value = await self.redis_client.get(redis_key)
        if value:
            return json.loads(value)
        return None
    
    async def delete_cache(self, key: str) -> bool:
        """删除缓存"""
        redis_key = self.make_key(key)
        return bool(await self.redis_client.delete(redis_key))
    
    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        redis_key = self.make_key(key)
        return bool(await self.redis_client.exists(redis_key))
    
    async def set_analysis_result(self, analysis_id: str, result: Any) -> bool:
        """存储分析结果"""
        key = self.make_key(f"analysis:{analysis_id}")
        return await self.set_cache(key, result, settings.REDIS_ANALYSIS_EXPIRE)
    
    async def get_analysis_result(self, analysis_id: str) -> Optional[Any]:
        """获取分析结果"""
        key = self.make_key(f"analysis:{analysis_id}")
        return await self.get_cache(key)
    
    async def increment_counter(self, key: str, amount: int = 1) -> int:
        """自增计数器"""
        redis_key = self.make_key(key)
        return await self.redis_client.incr(redis_key, amount)
    
    async def get_counter(self, key: str) -> int:
        """获取计数器值"""
        redis_key = self.make_key(key)
        value = await self.redis_client.get(redis_key)
        return int(value) if value else 0
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            return await self.redis_client.ping()
        except redis.ConnectionError:
            return False

# 创建全局 Redis 管理器实例
redis_manager = RedisManager()

# FastAPI 依赖项
async def get_redis() -> RedisManager:
    """获取 Redis 管理器依赖"""
    return redis_manager
