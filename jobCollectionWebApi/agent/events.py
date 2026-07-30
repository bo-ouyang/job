"""Agent 实时事件的数据结构与脱敏逻辑。"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AgentEventType(str, Enum):
    """前端可订阅的 Agent 生命周期事件类型。"""

    RUN_STARTED = "run_started"
    PLAN_CREATED = "plan_created"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_COMPLETED = "tool_completed"
    CLARIFICATION_REQUIRED = "clarification_required"
    MESSAGE_COMPLETED = "message_completed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


TERMINAL_EVENTS = {
    AgentEventType.RUN_COMPLETED.value,
    AgentEventType.RUN_FAILED.value,
    AgentEventType.RUN_CANCELLED.value,
}

# 终态事件和“等待用户澄清”都会结束当前 SSE 连接；用户补充信息后会开启新运行。
STREAM_CLOSING_EVENTS = TERMINAL_EVENTS | {AgentEventType.CLARIFICATION_REQUIRED.value}


class AgentEvent(BaseModel):
    """写入 Redis Stream 并通过 SSE 发送给前端的标准事件。"""

    event_id: Optional[str] = None
    sequence: int = Field(ge=1)
    event: AgentEventType
    run_id: str
    conversation_id: str
    data: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


def sanitize_event_data(value: Any, depth: int = 0) -> Any:
    """裁剪并过滤事件数据，避免敏感信息或超大对象进入 Redis/SSE。

    最多保留四层嵌套、有限数量的字典键和列表元素；prompt、token、SQL 等
    高风险字段会被直接删除。该函数只处理可观测事件，不修改数据库中的业务结果。
    """

    if depth >= 4:
        return "[truncated]"
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, dict):
        blocked = {"prompt", "sql", "dsl", "api_key", "token", "traceback", "state_snapshot"}
        return {
            str(key): sanitize_event_data(item, depth + 1)
            for key, item in list(value.items())[:40]
            if str(key).lower() not in blocked
        }
    if isinstance(value, list):
        return [sanitize_event_data(item, depth + 1) for item in value[:20]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:1000]
