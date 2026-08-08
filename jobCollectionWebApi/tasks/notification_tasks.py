"""Retryable persistence tasks for message-center notifications.

Business tasks first commit their own result/billing transaction.  These tasks
then create the durable user notification in a separate transaction.  The
database unique ``dedupe_key`` makes a Celery retry safe.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from celery import shared_task

from services.notification_service import (
    CAREER_AGENT_MESSAGE_TYPES,
    NotificationPersistenceError,
    TERMINAL_NOTIFICATION_STATUSES,
    build_agent_run_notification,
    build_ai_task_notification,
    notification_service,
)


def _get_event_loop():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def build_ai_task_message_content(
    *,
    feature_key: str,
    status: str,
    execution_time: Optional[float] = None,
    error_message: Optional[str] = None,
) -> tuple[str, str]:
    """Compatibility helper retained for callers that display task text."""
    notification = build_ai_task_notification(
        user_id=0,
        feature_key=feature_key,
        celery_task_id="preview",
        status=status,
        execution_time=execution_time,
        error_message=error_message,
    )
    return notification.title, notification.content


async def save_ai_task_message(
    *,
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    status: str,
    execution_time: Optional[float] = None,
    error_message: Optional[str] = None,
):
    notification = build_ai_task_notification(
        user_id=user_id,
        feature_key=feature_key,
        celery_task_id=celery_task_id,
        status=status,
        execution_time=execution_time,
        error_message=error_message,
    )
    result = await notification_service.create_and_publish(notification)
    return {
        "message_id": result.message_id,
        "title": result.title,
        "content": result.content,
        "created": result.created,
    }


async def _resolve_agent_message_type(run_id: int, user_id: int) -> Optional[str]:
    from common.databases.PostgresManager import db_manager
    from crud import agent as crud_agent

    async with await db_manager.get_session() as db:
        return await crud_agent.get_run_input_message_type(
            db, run_id=run_id, user_id=user_id
        )


async def save_agent_run_message(
    *,
    user_id: int,
    run_id: int,
    status: str,
    input_message_type: Optional[str] = None,
    error_message: Optional[str] = None,
):
    """Create the terminal AgentRun notification, if it is career-related."""
    if input_message_type is None:
        input_message_type = await _resolve_agent_message_type(run_id, user_id)
    notification = build_agent_run_notification(
        user_id=user_id,
        run_id=run_id,
        input_message_type=input_message_type,
        status=status,
        error_message=error_message,
    )
    if notification is None:
        return None
    return await notification_service.create_and_publish(notification)


def enqueue_agent_run_message(
    *, user_id: int, run_id: int, status: str, error_message: Optional[str] = None
) -> None:
    """Queue terminal notifications from request handlers such as cancellation."""
    persist_agent_run_message.apply_async(
        kwargs={
            "user_id": user_id,
            "run_id": run_id,
            "status": status,
            "error_message": error_message,
        },
        queue="batch",
        routing_key="batch",
    )


async def _list_unnotified_terminal_agent_runs() -> list[dict]:
    """Find terminal career runs whose durable notification is absent.

    This query only reduces reconciliation work.  It is *not* the idempotency
    mechanism: concurrent reconciliation and worker callbacks still converge
    through ``Message.dedupe_key`` and the repository's PostgreSQL UPSERT.
    """
    from sqlalchemy import String, and_, cast, func, select

    from common.databases.PostgresManager import db_manager
    from common.databases.models.agent_message import AgentMessage
    from common.databases.models.agent_run import AgentRun
    from common.databases.models.message import Message

    dedupe_key = func.concat(
        "agent_run:", cast(AgentRun.id, String), ":", AgentRun.status
    )
    statement = (
        select(
            AgentRun.id.label("run_id"),
            AgentRun.user_id.label("user_id"),
            AgentRun.status.label("status"),
            AgentRun.error_message.label("error_message"),
            AgentMessage.message_type.label("message_type"),
        )
        .join(AgentMessage, AgentMessage.id == AgentRun.input_message_id)
        .outerjoin(Message, Message.dedupe_key == dedupe_key)
        .where(
            AgentRun.status.in_(TERMINAL_NOTIFICATION_STATUSES),
            AgentMessage.message_type.in_(CAREER_AGENT_MESSAGE_TYPES),
            Message.id.is_(None),
        )
        .order_by(AgentRun.status_updated_at.asc(), AgentRun.id.asc())
        .limit(200)
    )
    async with await db_manager.get_session() as db:
        rows = await db.execute(statement)
        return [dict(row._mapping) for row in rows]


async def reconcile_agent_run_notifications_async() -> dict[str, int]:
    """Backfill missed terminal AgentRun notifications after broker outages."""
    rows = await _list_unnotified_terminal_agent_runs()
    repaired = 0
    skipped = 0
    for row in rows:
        if row["message_type"] not in CAREER_AGENT_MESSAGE_TYPES:
            skipped += 1
            continue
        result = await save_agent_run_message(
            run_id=row["run_id"],
            user_id=row["user_id"],
            status=row["status"],
            input_message_type=row["message_type"],
            error_message=row["error_message"],
        )
        # A concurrent callback may insert the same key after the scan.  The
        # database UPSERT remains authoritative and lets us report accurately.
        if result is not None and getattr(result, "created", True):
            repaired += 1
    return {"scanned": len(rows), "repaired": repaired, "skipped": skipped}


@shared_task(
    bind=True,
    name="tasks.notification_tasks.persist_ai_task_message",
    acks_late=True,
    autoretry_for=(NotificationPersistenceError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=8,
    time_limit=60,
    soft_time_limit=50,
)
def persist_ai_task_message(
    self,
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    status: str,
    execution_time: float = None,
    error_message: str = None,
):
    return _get_event_loop().run_until_complete(
        save_ai_task_message(
            user_id=user_id,
            feature_key=feature_key,
            celery_task_id=celery_task_id,
            status=status,
            execution_time=execution_time,
            error_message=error_message,
        )
    )


@shared_task(
    bind=True,
    name="tasks.notification_tasks.persist_agent_run_message",
    acks_late=True,
    autoretry_for=(NotificationPersistenceError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=8,
    time_limit=60,
    soft_time_limit=50,
)
def persist_agent_run_message(
    self,
    user_id: int,
    run_id: int,
    status: str,
    input_message_type: str = None,
    error_message: str = None,
):
    return _get_event_loop().run_until_complete(
        save_agent_run_message(
            user_id=user_id,
            run_id=run_id,
            status=status,
            input_message_type=input_message_type,
            error_message=error_message,
        )
    )


@shared_task(
    bind=True,
    name="tasks.notification_tasks.reconcile_agent_run_notifications",
    acks_late=True,
    autoretry_for=(NotificationPersistenceError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=8,
    time_limit=120,
    soft_time_limit=100,
)
def reconcile_agent_run_notifications(self):
    return _get_event_loop().run_until_complete(reconcile_agent_run_notifications_async())
