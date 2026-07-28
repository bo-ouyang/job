from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AgentEventType(str, Enum):
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

STREAM_CLOSING_EVENTS = TERMINAL_EVENTS | {AgentEventType.CLARIFICATION_REQUIRED.value}


class AgentEvent(BaseModel):
    event_id: Optional[str] = None
    sequence: int = Field(ge=1)
    event: AgentEventType
    run_id: str
    conversation_id: str
    data: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


def sanitize_event_data(value: Any, depth: int = 0) -> Any:
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
