"""Agent 任务互斥锁和 SSE 连接数限制器。"""

import uuid
import time
from typing import Optional

from common.databases.RedisManager import redis_manager
from config import settings
from core.logger import sys_logger as logger


# 释放和续租时必须核对持有者 token，避免旧 worker 删除新 worker 的锁。
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


class AgentRunLock:
    """保证同一个 AgentRun 同一时间只被一个 worker 执行的 Redis 租约锁。"""

    def __init__(self, client=None, manager=redis_manager):
        """允许注入 Redis 客户端，默认使用应用共享连接。"""

        self.client = client or manager.redis_client
        self.manager = manager

    def key(self, run_id: int) -> str:
        """返回某次运行的互斥锁键。"""

        return self.manager.make_key(f"agent:run:{run_id}:lock")

    async def acquire(self, run_id: int, ttl_seconds: Optional[int] = None) -> Optional[str]:
        """尝试以 NX 方式加锁；成功返回所有权 token，失败返回 None。"""

        token = uuid.uuid4().hex
        acquired = await self.client.set(
            self.key(run_id),
            token,
            nx=True,
            ex=ttl_seconds or settings.AGENT_LOCK_TTL_SECONDS,
        )
        return token if acquired else None

    async def renew(self, run_id: int, token: str, ttl_seconds: Optional[int] = None) -> bool:
        """仅当 token 仍属于当前执行者时延长锁有效期。"""

        result = await self.client.eval(
            _RENEW_SCRIPT,
            1,
            self.key(run_id),
            token,
            ttl_seconds or settings.AGENT_LOCK_TTL_SECONDS,
        )
        return bool(result)

    async def release(self, run_id: int, token: str) -> bool:
        """仅由锁持有者释放租约，返回是否实际删除了锁。"""

        result = await self.client.eval(_RELEASE_SCRIPT, 1, self.key(run_id), token)
        return bool(result)


agent_run_lock = AgentRunLock()


# 每个用户的活跃 SSE 连接以“token -> 过期时间”存入有序集合。
# 获取名额时先清理过期成员，再原子检查连接上限并插入新 token。
_SSE_ACQUIRE_SCRIPT = """
redis.call('zremrangebyscore', KEYS[1], '-inf', ARGV[3])
local current = redis.call('zcard', KEYS[1])
if current >= tonumber(ARGV[1]) then
  return 0
end
redis.call('zadd', KEYS[1], ARGV[4], ARGV[5])
redis.call('expire', KEYS[1], ARGV[2] * 2)
return 1
"""

_SSE_RELEASE_SCRIPT = """
return redis.call('zrem', KEYS[1], ARGV[1])
"""

_SSE_RENEW_SCRIPT = """
if redis.call('zscore', KEYS[1], ARGV[1]) then
  redis.call('zadd', KEYS[1], ARGV[2], ARGV[1])
  redis.call('expire', KEYS[1], ARGV[3] * 2)
  return 1
end
return 0
"""


class AgentSSEConnectionLimiter:
    """限制单个用户同时建立的 Agent SSE 长连接数量。"""

    def __init__(self, client=None, manager=redis_manager):
        """允许注入 Redis 客户端，默认使用应用共享连接。"""

        self.client = client or manager.redis_client
        self.manager = manager

    def key(self, user_id: int) -> str:
        """返回保存用户活跃 SSE token 的有序集合键。"""

        return self.manager.make_key(f"agent:sse:user:{user_id}:connections")

    async def acquire(self, user_id: int) -> Optional[str]:
        """申请一个 SSE 连接名额；达到上限时返回 None。"""

        token = uuid.uuid4().hex
        ttl = max(settings.AGENT_RUN_TIMEOUT_SECONDS * 3, 180)
        now = int(time.time())
        result = await self.client.eval(
            _SSE_ACQUIRE_SCRIPT,
            1,
            self.key(user_id),
            settings.AGENT_MAX_SSE_CONNECTIONS_PER_USER,
            ttl,
            now,
            now + ttl,
            token,
        )
        return token if result else None

    async def renew(self, user_id: int, token: str) -> bool:
        """刷新仍然有效的连接 token，防止正常长连接被误清理。"""

        ttl = max(settings.AGENT_RUN_TIMEOUT_SECONDS * 3, 180)
        result = await self.client.eval(
            _SSE_RENEW_SCRIPT,
            1,
            self.key(user_id),
            token,
            int(time.time()) + ttl,
            ttl,
        )
        return bool(result)

    async def release(self, user_id: int, token: str) -> None:
        """连接关闭时从用户的活跃连接集合中移除 token。"""

        await self.client.eval(_SSE_RELEASE_SCRIPT, 1, self.key(user_id), token)


agent_sse_connection_limiter = AgentSSEConnectionLimiter()
