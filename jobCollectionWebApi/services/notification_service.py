"""Durable, structured notifications for the message center.

The database row is the source of truth. Redis/WebSocket is only a best-effort
realtime hint and is deliberately published *after* the message transaction
commits.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.logger import sys_logger as logger


TERMINAL_NOTIFICATION_STATUSES = frozenset({"completed", "failed", "cancelled"})
CAREER_AGENT_MESSAGE_TYPES = frozenset({"career_report_request", "career_question"})


class NotificationPersistenceError(RuntimeError):
    """The durable notification record was not committed and can be retried."""


@dataclass(frozen=True)
class NotificationInput:
    receiver_id: int
    title: str
    content: str
    category: str
    status: str
    source_type: str
    source_id: str
    dedupe_key: str
    action_type: Optional[str] = None
    action_data: Optional[Dict[str, Any]] = None

    def to_model_values(self) -> Dict[str, Any]:
        from common.databases.models.message import MessageType

        return {
            "title": self.title,
            "content": self.content,
            "type": MessageType.SYSTEM,
            "receiver_id": self.receiver_id,
            "category": self.category,
            "status": self.status,
            "action_type": self.action_type,
            "action_data": self.action_data,
            "source_type": self.source_type,
            "source_id": str(self.source_id),
            "dedupe_key": self.dedupe_key,
        }


@dataclass(frozen=True)
class NotificationResult:
    message_id: str
    created: bool
    ws_published: bool
    title: str
    content: str


def serialize_message(message) -> Dict[str, Any]:
    """Serialize notification IDs in a JavaScript-safe, camelCase WS shape."""
    message_type = getattr(message, "type", None)
    return {
        "id": str(message.id),
        "title": message.title,
        "content": message.content,
        "type": getattr(message_type, "value", message_type),
        "category": message.category,
        "status": message.status,
        "isRead": bool(message.is_read),
        "actionType": message.action_type,
        "actionData": message.action_data,
        "sourceType": message.source_type,
        "sourceId": str(message.source_id) if message.source_id is not None else None,
    }


class RedisWebSocketPublisher:
    async def publish_new_message(self, user_id: int, message: Dict[str, Any]) -> None:
        import redis.asyncio as redis
        from config import settings

        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            payload = json.dumps(
                {"user_id": user_id, "message": {"type": "new_message", "data": message}},
                ensure_ascii=False,
            )
            await client.publish("job_messages", payload)
        finally:
            await client.aclose()


class NotificationService:
    def __init__(self, *, session_factory=None, repository=None, publisher=None):
        if session_factory is None:
            from common.databases.PostgresManager import db_manager

            session_factory = db_manager.get_session
        if repository is None:
            from crud.message import message as repository

        self.session_factory = session_factory
        self.repository = repository
        self.publisher = publisher or RedisWebSocketPublisher()

    async def create_and_publish(self, payload: NotificationInput) -> NotificationResult:
        """Persist once, commit, then best-effort notify connected clients."""
        session_context = self.session_factory()
        if inspect.isawaitable(session_context):
            session_context = await session_context
        try:
            async with session_context as db:
                message, created = await self.repository.create_or_get(db, payload)
                await db.commit()
        except Exception as exc:
            try:
                await db.rollback()
            except Exception:
                pass
            raise NotificationPersistenceError(str(exc)) from exc

        ws_published = False
        if created:
            try:
                await self.publisher.publish_new_message(payload.receiver_id, serialize_message(message))
                ws_published = True
            except Exception as exc:
                logger.warning(
                    "notification_ws_publish_failed "
                    f"receiver_id={payload.receiver_id} dedupe_key={payload.dedupe_key} error={exc}"
                )
        return NotificationResult(
            message_id=str(message.id),
            created=created,
            ws_published=ws_published,
            title=message.title,
            content=message.content,
        )


def build_ai_task_notification(
    *, user_id: int, feature_key: str, celery_task_id: str, status: str,
    execution_time: Optional[float] = None, error_message: Optional[str] = None,
) -> NotificationInput:
    if status not in TERMINAL_NOTIFICATION_STATUSES:
        raise ValueError(f"notification status must be terminal, got {status!r}")
    names = {
        "career_advice": "AI 职业建议",
        "career_compass": "职业罗盘",
        "resume_parse": "简历解析",
    }
    name = names.get(feature_key, "AI 任务")
    category = "resume" if feature_key == "resume_parse" else "career"
    if status == "completed":
        title = f"{name}已完成"
        content = f"{name}已完成" + (f"，耗时 {execution_time} 秒。" if execution_time is not None else "。")
    elif status == "cancelled":
        title, content = f"{name}已取消", f"{name}已取消。"
    else:
        title, content = f"{name}失败", f"{name}失败：{error_message or '未知错误'}"
    # The client selects a destination from category/source_type; it must not
    # trust a route supplied by a notification.  The task ID is explicit so
    # historical rows that lack a result target do not show a dead action.
    action_data = {"taskId": str(celery_task_id)}
    return NotificationInput(
        receiver_id=user_id, title=title, content=content, category=category, status=status,
        source_type="ai_task", source_id=str(celery_task_id),
        dedupe_key=f"ai_task:{celery_task_id}:{status}", action_type="navigate", action_data=action_data,
    )


def build_agent_run_notification(
    *, user_id: int, run_id: int, input_message_type: Optional[str], status: str,
    error_message: Optional[str] = None,
) -> Optional[NotificationInput]:
    """Only career-oriented Agent runs belong in the message center."""
    if input_message_type not in CAREER_AGENT_MESSAGE_TYPES:
        return None
    if status not in TERMINAL_NOTIFICATION_STATUSES:
        raise ValueError(f"notification status must be terminal, got {status!r}")
    if status == "completed":
        title, content = "职业分析报告已完成", "你的职业分析报告已生成，可以查看详细建议。"
    elif status == "cancelled":
        title, content = "职业分析已取消", "你的职业分析任务已取消。"
    else:
        title, content = "职业分析失败", f"职业分析未能完成：{error_message or '请稍后重试'}"
    return NotificationInput(
        receiver_id=user_id, title=title, content=content, category="career", status=status,
        source_type="agent_run", source_id=str(run_id),
        dedupe_key=f"agent_run:{run_id}:{status}", action_type="navigate",
        action_data={"route": "/career-analysis", "runId": str(run_id)},
    )


notification_service = NotificationService()
