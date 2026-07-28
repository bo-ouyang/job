import uuid
import time
from typing import Optional

from common.databases.RedisManager import redis_manager
from config import settings
from core.logger import sys_logger as logger


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
    def __init__(self, client=None, manager=redis_manager):
        self.client = client or manager.redis_client
        self.manager = manager

    def key(self, run_id: int) -> str:
        return self.manager.make_key(f"agent:run:{run_id}:lock")

    async def acquire(self, run_id: int, ttl_seconds: Optional[int] = None) -> Optional[str]:
        token = uuid.uuid4().hex
        acquired = await self.client.set(
            self.key(run_id),
            token,
            nx=True,
            ex=ttl_seconds or settings.AGENT_LOCK_TTL_SECONDS,
        )
        return token if acquired else None

    async def renew(self, run_id: int, token: str, ttl_seconds: Optional[int] = None) -> bool:
        result = await self.client.eval(
            _RENEW_SCRIPT,
            1,
            self.key(run_id),
            token,
            ttl_seconds or settings.AGENT_LOCK_TTL_SECONDS,
        )
        return bool(result)

    async def release(self, run_id: int, token: str) -> bool:
        result = await self.client.eval(_RELEASE_SCRIPT, 1, self.key(run_id), token)
        return bool(result)


agent_run_lock = AgentRunLock()


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
    def __init__(self, client=None, manager=redis_manager):
        self.client = client or manager.redis_client
        self.manager = manager

    def key(self, user_id: int) -> str:
        return self.manager.make_key(f"agent:sse:user:{user_id}:connections")

    async def acquire(self, user_id: int) -> Optional[str]:
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
        await self.client.eval(_SSE_RELEASE_SCRIPT, 1, self.key(user_id), token)


agent_sse_connection_limiter = AgentSSEConnectionLimiter()
