"""基于 Redis Stream 的 Agent 实时事件存储与发布器。"""

import json
import redis.asyncio as redis
from datetime import datetime
from typing import List, Optional

from common.databases.RedisManager import redis_manager
from config import settings
from core.logger import sys_logger as logger
from core.metrics import agent_event_publish_failures

from .events import AgentEvent, AgentEventType, sanitize_event_data


# 使用 Lua 把“递增序号、追加事件、设置过期时间”合并成一个原子操作，
# 避免多个 worker 同时发布事件时出现重复或乱序的 sequence。
_APPEND_EVENT_SCRIPT = """
local sequence = redis.call('INCR', KEYS[2])
local event_id = redis.call(
  'XADD', KEYS[1], 'MAXLEN', '~', ARGV[1], '*',
  'sequence', tostring(sequence),
  'event', ARGV[2],
  'run_id', ARGV[3],
  'conversation_id', ARGV[4],
  'data', ARGV[5],
  'created_at', ARGV[6]
)
redis.call('EXPIRE', KEYS[1], ARGV[7])
redis.call('EXPIRE', KEYS[2], ARGV[7])
return {event_id, sequence}
"""


class AgentEventStore:
    """读写某次 AgentRun 对应的 Redis Stream。

    普通 worker 使用共享 Redis 客户端写事件；SSE 层使用独立连接池读取，避免长轮询
    占满业务 Redis 连接。
    """

    def __init__(self, client=None, manager=redis_manager):
        """允许注入 Redis 客户端，便于 SSE 隔离连接池和单元测试。"""

        self.client = client or manager.redis_client
        self.manager = manager

    def stream_key(self, run_id: int) -> str:
        """返回保存某次运行事件的 Redis Stream 键。"""

        return self.manager.make_key(f"agent:run:{run_id}:events")

    def sequence_key(self, run_id: int) -> str:
        """返回某次运行单调递增事件序号所使用的 Redis 键。"""

        return self.manager.make_key(f"agent:run:{run_id}:event_sequence")

    async def append(
        self,
        *,
        run_id: int,
        conversation_id: int,
        event: AgentEventType,
        data: Optional[dict] = None,
    ) -> AgentEvent:
        """原子追加一个已脱敏事件，并返回包含 Redis event id 的事件对象。"""

        created_at = datetime.utcnow()
        result = await self.client.eval(
            _APPEND_EVENT_SCRIPT,
            2,
            self.stream_key(run_id),
            self.sequence_key(run_id),
            settings.AGENT_EVENT_MAXLEN,
            event.value,
            str(run_id),
            str(conversation_id),
            json.dumps(sanitize_event_data(data or {}), ensure_ascii=False, default=str),
            created_at.isoformat(),
            settings.AGENT_EVENT_TTL_SECONDS,
        )
        event_id, sequence = result
        return AgentEvent(
            event_id=str(event_id),
            sequence=int(sequence),
            event=event,
            run_id=str(run_id),
            conversation_id=str(conversation_id),
            data=sanitize_event_data(data or {}),
            created_at=created_at,
        )

    async def replay(
        self,
        run_id: int,
        *,
        after_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[AgentEvent]:
        """回放 ``after_id`` 之后的历史事件，用于 SSE 断线续传。"""

        minimum = f"({after_id}" if after_id else "-"
        rows = await self.client.xrange(
            self.stream_key(run_id),
            min=minimum,
            max="+",
            count=limit,
        )
        return [self._parse_row(event_id, fields) for event_id, fields in rows]

    async def read_new(
        self,
        run_id: int,
        *,
        after_id: str,
        block_ms: int = 3000,
        limit: int = 50,
    ) -> List[AgentEvent]:
        """阻塞读取 cursor 之后的新事件，最长阻塞时间被限制为 3 秒。"""

        rows = await self.client.xread(
            {self.stream_key(run_id): after_id},
            count=limit,
            block=min(block_ms, 3000),
        )
        if not rows:
            return []
        events = []
        for _stream_name, stream_rows in rows:
            events.extend(self._parse_row(event_id, fields) for event_id, fields in stream_rows)
        return events

    @staticmethod
    def _parse_row(event_id, fields) -> AgentEvent:
        """把 Redis Stream 的字段字典还原为强类型 AgentEvent。"""

        return AgentEvent(
            event_id=str(event_id),
            sequence=int(fields.get("sequence") or 0),
            event=AgentEventType(fields["event"]),
            run_id=str(fields["run_id"]),
            conversation_id=str(fields["conversation_id"]),
            data=json.loads(fields.get("data") or "{}"),
            created_at=datetime.fromisoformat(fields["created_at"]),
        )


class AgentEventPublisher:
    """对事件写入做容错包装，确保 Redis 故障不会中断 Agent 主流程。"""

    def __init__(self, store: Optional[AgentEventStore] = None):
        """使用指定事件存储；未指定时创建默认 Redis Stream 存储。"""

        self.store = store or AgentEventStore()

    async def publish(self, **kwargs) -> Optional[AgentEvent]:
        """发布事件；失败时记录指标和日志并返回 None，而不是抛出异常。"""

        try:
            return await self.store.append(**kwargs)
        except Exception as exc:
            event_name = kwargs.get("event")
            agent_event_publish_failures.labels(
                event=getattr(event_name, "value", str(event_name or "unknown")),
            ).inc()
            logger.warning(
                f"Agent event publish failed: run_id={kwargs.get('run_id')}, "
                f"event={kwargs.get('event')}, error={exc}"
            )
            return None


agent_event_store = AgentEventStore()
agent_event_publisher = AgentEventPublisher(agent_event_store)

# SSE 的 XREAD 会长时间占用连接，因此使用容量独立的连接池。
agent_sse_pool = redis.ConnectionPool(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
    password=settings.REDIS_PASSWORD,
    max_connections=settings.AGENT_SSE_REDIS_MAX_CONNECTIONS,
    socket_timeout=max(settings.REDIS_SOCKET_TIMEOUT, 5),
    socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
    retry_on_timeout=settings.REDIS_RETRY_ON_TIMEOUT,
    decode_responses=True,
)
agent_sse_client = redis.Redis(connection_pool=agent_sse_pool)
agent_sse_event_store = AgentEventStore(client=agent_sse_client)


async def close_agent_event_resources() -> None:
    """在应用关闭时释放 SSE 专用 Redis 客户端和连接池。"""

    close_method = getattr(agent_sse_client, "aclose", None) or getattr(agent_sse_client, "close", None)
    if close_method:
        result = close_method()
        if hasattr(result, "__await__"):
            await result
    await agent_sse_pool.disconnect()
