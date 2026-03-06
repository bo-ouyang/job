"""
Celery task for AI resume parsing.

【v3 更新】
- mark_completed/failed 回写 AiTask + 释放并发锁
- Prometheus 指标
- 统一 WS 通知 (ai_task_completed / ai_task_failed)
"""

import asyncio
import json
import time
import pdfplumber
import os

from core.logger import sys_logger as logger
from jobCollectionWebApi.core.celery_app import celery_app
from services.ai_service import ai_service
from api.v1.endpoints.ws_controller import manager


def _get_event_loop():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def _publish_ws(user_id: int, msg_type: str, data: dict):
    """Push via Redis Pub/Sub → WebSocket"""
    try:
        import redis as _redis
        from config import settings
        r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.publish("job_messages", json.dumps({
            "user_id": user_id,
            "message": {"type": msg_type, "data": data}
        }, ensure_ascii=False))
        r.close()
    except Exception as e:
        logger.error(f"WS publish failed: {e}")


async def _extract_text_from_pdf(file_path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() + "\n"
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
    return text


async def _parse_resume_logic(user_id: int, file_path: str) -> str:
    """
    1. Extract text from PDF
    2. Call AI to structure data
    3. Notify user via WS
    Returns: JSON string of parsed data (for AiTask result_data)
    """
    text = await _extract_text_from_pdf(file_path)
    if not text:
        error_msg = "无法读取简历内容，请上传标准的PDF文件"
        _publish_ws(user_id, "resume_parse_error", {"message": error_msg})
        raise ValueError(error_msg)

    # Call AI
    parsed_data = await ai_service.parse_resume_text(text)
    logger.debug(f"AI Parsed Data: {parsed_data}")

    # Publish feature-specific WS message (backward compatible)
    _publish_ws(user_id, "resume_parsed", parsed_data)

    return json.dumps(parsed_data, ensure_ascii=False)


def _mark_completed(user_id: int, celery_task_id: str, result_data: str, started_at: float):
    from crud import ai_task as crud_ai_task
    loop = _get_event_loop()
    execution_time = round(time.time() - started_at, 2) if started_at else None

    try:
        loop.run_until_complete(
            crud_ai_task.mark_completed(
                user_id=user_id,
                feature_key="resume_parse",
                celery_task_id=celery_task_id,
                result_data=result_data,
                started_at=started_at,
            )
        )
    except Exception as exc:
        logger.error(f"resume mark_completed failed: {exc}")

    # Prometheus
    try:
        from core.metrics import ai_task_completed, ai_task_duration
        ai_task_completed.labels(feature="resume_parse").inc()
        if execution_time is not None:
            ai_task_duration.labels(feature="resume_parse").observe(execution_time)
    except Exception:
        pass

    message_text = "您的简历解析已完成"
    message_id = None

    # 存入消息系统 (供消息中心展示)
    try:
        from crud.message import message as crud_message
        from schemas.message_schema import MessageCreate
        from common.databases.models.message import MessageType
        from common.databases.PostgresManager import db_manager

        async def _create_msg():
            async with db_manager.async_session() as db:
                import json
                action_param = json.dumps({"task_id": celery_task_id, "feature_key": "resume_parse"})
                new_msg = await crud_message.create(
                    db,
                    obj_in=MessageCreate(
                        title="✅ 简历智能解析完成",
                        content=f"{message_text}，耗时 {execution_time}秒。",
                        type=MessageType.SYSTEM,
                        receiver_id=user_id,
                        #action_param=action_param,
                    )
                )
                await db.commit()
                return new_msg.id
        message_id = loop.run_until_complete(_create_msg())
    except Exception as exc:
        logger.error(f"Save message failed: {exc}")

    # 统一 WS 通知
    _publish_ws(user_id, "ai_task_completed", {
        "task_id": celery_task_id,
        "feature_key": "resume_parse",
        "status": "completed",
        "execution_time": execution_time,
        "message": message_text,
        "message_id": message_id,
    })


def _mark_failed(user_id: int, celery_task_id: str, error_message: str, started_at: float):
    from crud import ai_task as crud_ai_task
    loop = _get_event_loop()
    execution_time = round(time.time() - started_at, 2) if started_at else None

    try:
        loop.run_until_complete(
            crud_ai_task.mark_failed(
                user_id=user_id,
                feature_key="resume_parse",
                celery_task_id=celery_task_id,
                error_message=error_message,
                started_at=started_at,
            )
        )
    except Exception as exc:
        logger.error(f"resume mark_failed failed: {exc}")

    # Prometheus
    try:
        from core.metrics import ai_task_failed, ai_task_duration
        ai_task_failed.labels(feature="resume_parse").inc()
        if execution_time is not None:
            ai_task_duration.labels(feature="resume_parse").observe(execution_time)
    except Exception:
        pass

    message_text = "您的简历解析失败"
    message_id = None

    # 存入消息系统
    try:
        from crud.message import message as crud_message
        from schemas.message_schema import MessageCreate
        from common.databases.models.message import MessageType
        from common.databases.PostgresManager import db_manager

        async def _create_msg():
            async with db_manager.async_session() as db:
                import json
                action_param = json.dumps({"task_id": celery_task_id, "feature_key": "resume_parse"})
                new_msg = await crud_message.create(
                    db,
                    obj_in=MessageCreate(
                        title="❌ 简历智能解析失败",
                        content=f"{message_text}。原因: {error_message}",
                        type=MessageType.SYSTEM,
                        receiver_id=user_id,
                        #action_param=action_param,
                    )
                )
                await db.commit()
                return new_msg.id
        message_id = loop.run_until_complete(_create_msg())
    except Exception as exc:
        logger.error(f"Save message failed: {exc}")

    # 统一 WS 通知
    _publish_ws(user_id, "ai_task_failed", {
        "task_id": celery_task_id,
        "feature_key": "resume_parse",
        "status": "failed",
        "error": error_message,
        "message": message_text,
        "message_id": message_id,
    })


@celery_app.task(
    bind=True,
    name="parse_resume_task",
    acks_late=True,
    time_limit=300,
    soft_time_limit=270,
)
def parse_resume_task(self, user_id: int, file_path: str):
    """Celery task wrapper for resume parsing."""
    loop = _get_event_loop()
    started_at = time.time()
    try:
        result = loop.run_until_complete(_parse_resume_logic(user_id, file_path))
        _mark_completed(user_id, self.request.id, result, started_at)
    except Exception as e:
        logger.error(f"Resume parsing failed: {e}")
        _mark_failed(user_id, self.request.id, str(e), started_at)
        _publish_ws(user_id, "resume_parse_error", {"message": "解析服务暂时不可用"})
