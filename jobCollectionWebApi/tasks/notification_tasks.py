"""
Background notification tasks.

These tasks persist AI completion and failure messages for the message center.
They can run directly inside a worker or be dispatched to the batch queue.
"""

import asyncio

from celery import shared_task

from core.logger import sys_logger as logger


def _get_event_loop():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def _feature_display(feature_key: str) -> str:
    return {
        "career_advice": "AI career advice",
        "career_compass": "career compass",
        "resume_parse": "resume parsing",
    }.get(feature_key, "AI task")


def build_ai_task_message_content(
    *,
    feature_key: str,
    status: str,
    execution_time: float | None = None,
    error_message: str | None = None,
) -> tuple[str, str]:
    feature_name = _feature_display(feature_key)
    if status == "completed":
        title = f"{feature_name} completed"
        if execution_time is not None:
            content = f"Your {feature_name} task has completed in {execution_time} seconds."
        else:
            content = f"Your {feature_name} task has completed."
    else:
        title = f"{feature_name} failed"
        content = f"Your {feature_name} task failed. Reason: {error_message or 'unknown error'}"
    return title, content


async def save_ai_task_message(
    *,
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    status: str,
    execution_time: float | None = None,
    error_message: str | None = None,
):
    from common.databases.PostgresManager import db_manager
    from common.databases.models.message import MessageType
    from jobCollectionWebApi.crud.message import message as crud_message
    from jobCollectionWebApi.schemas.message_schema import MessageCreate

    title, content = build_ai_task_message_content(
        feature_key=feature_key,
        status=status,
        execution_time=execution_time,
        error_message=error_message,
    )

    session_obj = await db_manager.get_session()
    async with session_obj as db:
        msg = await crud_message.create(
            db,
            obj_in=MessageCreate(
                title=title,
                content=content,
                type=MessageType.SYSTEM,
                receiver_id=user_id,
            ),
        )
        await db.commit()

    message_id = getattr(msg, "id", None)
    logger.info(
        "ai_task_message_saved "
        f"user_id={user_id} feature={feature_key} task_id={celery_task_id} "
        f"status={status} message_id={message_id}"
    )
    return {
        "message_id": str(message_id) if message_id is not None else None,
        "title": title,
        "content": content,
    }


@shared_task(
    bind=True,
    name="tasks.notification_tasks.persist_ai_task_message",
    acks_late=True,
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
    loop = _get_event_loop()
    try:
        loop.run_until_complete(
            save_ai_task_message(
                user_id=user_id,
                feature_key=feature_key,
                celery_task_id=celery_task_id,
                status=status,
                execution_time=execution_time,
                error_message=error_message,
            )
        )
    except Exception as exc:
        logger.error(
            "persist_ai_task_message failed: "
            f"user_id={user_id}, feature={feature_key}, task_id={celery_task_id}, "
            f"status={status}, err={exc}"
        )
