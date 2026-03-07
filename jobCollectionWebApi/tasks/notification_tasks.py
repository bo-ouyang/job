"""
Background notification tasks.

These tasks run in the batch queue and persist system messages without
blocking realtime AI task completion.
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
        "career_advice": "AI职业建议",
        "career_compass": "职业罗盘分析",
        "resume_parse": "简历解析",
    }.get(feature_key, "AI任务")


async def _persist_ai_task_message(
    *,
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    status: str,
    execution_time: float | None = None,
    error_message: str | None = None,
):
    from crud.message import message as crud_message
    from schemas.message_schema import MessageCreate
    from common.databases.models.message import MessageType
    from common.databases.PostgresManager import db_manager

    feature_name = _feature_display(feature_key)
    if status == "completed":
        title = f"✅ {feature_name}完成"
        content = f"您的{feature_name}已完成，耗时 {execution_time}秒。"
    else:
        title = f"❌ {feature_name}失败"
        content = f"您的{feature_name}处理失败。原因: {error_message or '未知错误'}"

    session_obj = await db_manager.get_session()
    async with session_obj as db:
        await crud_message.create(
            db,
            obj_in=MessageCreate(
                title=title,
                content=content,
                type=MessageType.SYSTEM,
                receiver_id=user_id,
            ),
        )
        await db.commit()

    logger.info(
        f"ai_task_message_saved user_id={user_id} feature={feature_key} task_id={celery_task_id} status={status}"
    )


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
            _persist_ai_task_message(
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
            f"persist_ai_task_message failed: user_id={user_id}, feature={feature_key}, task_id={celery_task_id}, status={status}, err={exc}"
        )
