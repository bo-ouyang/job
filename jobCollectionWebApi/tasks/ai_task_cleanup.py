"""
Celery Beat 定时清理僵死 AI 任务。

每 5 分钟执行：
1. 查找 status=pending/processing 且 created_at > 5分钟前 的 AiTask 记录
2. 检查 Celery result backend 确认真实状态
3. 若 Celery 也无记录 → 标记 failed + 释放 Redis 锁
"""

import asyncio
from datetime import datetime, timedelta

from celery import shared_task

from core.logger import sys_logger as logger


STALE_THRESHOLD_MINUTES = 5


def _get_event_loop():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


async def _cleanup_logic():
    from common.databases.PostgresManager import db_manager
    from common.databases.models.ai_task import AiTask
    from sqlalchemy import select, update
    from common.databases.RedisManager import redis_manager
    from core.celery_app import celery_app

    cutoff = datetime.utcnow() - timedelta(minutes=STALE_THRESHOLD_MINUTES)
    cleaned = 0

    session = await db_manager.get_session()
    async with session as db:
        stmt = (
            select(AiTask)
            .where(
                AiTask.status.in_(["pending", "processing"]),
                AiTask.created_at < cutoff,
            )
            .limit(50)
        )
        result = await db.execute(stmt)
        stale_tasks = result.scalars().all()

        for task in stale_tasks:
            # Check Celery result backend
            celery_result = celery_app.AsyncResult(task.celery_task_id)
            
            if celery_result.state in ("SUCCESS", "FAILURE"):
                # Celery finished but callback didn't fire — fix PG
                new_status = "completed" if celery_result.state == "SUCCESS" else "failed"
                task.status = new_status
                task.completed_at = datetime.utcnow()
                if celery_result.state == "FAILURE":
                    task.error_message = f"Recovered by cleanup: {celery_result.result}"
                logger.info(f"Recovered stale task {task.celery_task_id} → {new_status}")
            else:
                # Celery also has no record — mark as failed
                task.status = "failed"
                task.error_message = "任务超时，已被系统自动清理"
                task.completed_at = datetime.utcnow()
                logger.warning(f"Cleaned stale task {task.celery_task_id} (no Celery result)")

            # Release Redis lock
            try:
                lock_key = redis_manager.make_key(f"ai_task:active:{task.feature_key}:{task.user_id}")
                await redis_manager.redis_client.delete(lock_key)
            except Exception as exc:
                logger.warning(f"Failed to release Redis lock for stale task: {exc}")

            cleaned += 1

        if cleaned > 0:
            await db.commit()
            logger.info(f"AI task cleanup: recovered/cleaned {cleaned} stale tasks")


@shared_task(name="tasks.ai_task_cleanup.cleanup_stale_ai_tasks")
def cleanup_stale_ai_tasks():
    """Celery Beat 定时任务：清理僵死 AI 任务"""
    loop = _get_event_loop()
    try:
        loop.run_until_complete(_cleanup_logic())
    except Exception as exc:
        logger.error(f"AI task cleanup failed: {exc}")
