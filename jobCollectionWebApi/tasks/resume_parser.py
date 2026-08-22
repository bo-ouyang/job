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
from services.ai_task_lifecycle_service import AiTaskLifecycle


def _has_usable_resume_candidates(parsed_data) -> bool:
    if not isinstance(parsed_data, dict) or parsed_data.get("error") or parsed_data.get("message"):
        return False
    if any(parsed_data.get(field) for field in (
        "name", "phone", "email", "gender", "age", "desired_position", "summary"
    )):
        return True
    if any(item and item.get("school") for item in parsed_data.get("educations") or [] if isinstance(item, dict)):
        return True
    if any(
        item and item.get("company") and item.get("position")
        for item in parsed_data.get("work_experiences") or []
        if isinstance(item, dict)
    ):
        return True
    for field in ("skills", "courses"):
        if any(
            (isinstance(item, str) and item.strip())
            or (isinstance(item, dict) and str(item.get("name") or "").strip())
            for item in parsed_data.get(field) or []
        ):
            return True
    return False


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


def _enqueue_ai_task_message(
    *,
    user_id: int,
    celery_task_id: str,
    status: str,
    execution_time: float = None,
    error_message: str = None,
):
    try:
        try:
            from jobCollectionWebApi.tasks.notification_tasks import persist_ai_task_message
        except Exception:
            from tasks.notification_tasks import persist_ai_task_message

        persist_ai_task_message.apply_async(
            kwargs={
                "user_id": user_id,
                "feature_key": "resume_parse",
                "celery_task_id": celery_task_id,
                "status": status,
                "execution_time": execution_time,
                "error_message": error_message,
            },
            queue="batch",
            routing_key="batch",
        )
    except Exception as exc:
        logger.error(
            f"enqueue resume message failed: user_id={user_id}, task_id={celery_task_id}, status={status}, err={exc}"
        )


def _save_resume_message(
    *,
    user_id: int,
    celery_task_id: str,
    status: str,
    execution_time: float = None,
    error_message: str = None,
):
    loop = _get_event_loop()
    try:
        try:
            from jobCollectionWebApi.tasks.notification_tasks import save_ai_task_message
        except Exception:
            from tasks.notification_tasks import save_ai_task_message

        return loop.run_until_complete(
            save_ai_task_message(
                user_id=user_id,
                feature_key="resume_parse",
                celery_task_id=celery_task_id,
                status=status,
                execution_time=execution_time,
                error_message=error_message,
            )
        )
    except Exception as exc:
        logger.error(
            f"save resume message failed: user_id={user_id}, task_id={celery_task_id}, status={status}, err={exc}"
        )
        return None


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
        raise ValueError(error_msg)

    # Call AI
    parsed_data = await ai_service.parse_resume_text(text)
    logger.debug(f"AI Parsed Data: {parsed_data}")

    if not _has_usable_resume_candidates(parsed_data):
        raise RuntimeError("AI resume parsing returned no structured data")

    return json.dumps(parsed_data, ensure_ascii=False)


def _lifecycle() -> AiTaskLifecycle:
    """Adapt the existing Resume dependencies to the shared terminal lifecycle."""
    from crud import ai_task as crud_ai_task

    loop = _get_event_loop()

    def persist_completed(**kwargs):
        return loop.run_until_complete(
            crud_ai_task.mark_completed(
                user_id=kwargs["user_id"],
                feature_key=kwargs["feature_key"],
                celery_task_id=kwargs["celery_task_id"],
                result_data=kwargs["result_data"],
                started_at=kwargs["started_at"],
            )
        )

    def persist_failed(**kwargs):
        return loop.run_until_complete(crud_ai_task.mark_failed(**kwargs))

    def record_metrics(*, status, feature_key, execution_time):
        from core.metrics import ai_task_completed, ai_task_duration, ai_task_failed

        metric = ai_task_completed if status == "completed" else ai_task_failed
        metric.labels(feature=feature_key).inc()
        if execution_time is not None:
            ai_task_duration.labels(feature=feature_key).observe(execution_time)

    return AiTaskLifecycle(
        persist_completed=persist_completed,
        persist_failed=persist_failed,
        save_notification=lambda **kwargs: _save_resume_message(
            user_id=kwargs["user_id"],
            celery_task_id=kwargs["celery_task_id"],
            status=kwargs["status"],
            execution_time=kwargs["execution_time"],
            error_message=kwargs.get("error_message"),
        ),
        enqueue_notification=lambda **kwargs: _enqueue_ai_task_message(
            user_id=kwargs["user_id"],
            celery_task_id=kwargs["celery_task_id"],
            status=kwargs["status"],
            execution_time=kwargs["execution_time"],
            error_message=kwargs.get("error_message"),
        ),
        publish_event=_publish_ws,
        feature_display=lambda _feature_key: "resume parsing",
        record_metrics=record_metrics,
    )

def _mark_completed(user_id: int, celery_task_id: str, result_data: str, started_at: float):
    return _lifecycle().complete(
        user_id=user_id,
        feature_key="resume_parse",
        celery_task_id=celery_task_id,
        result_data=result_data,
        started_at=started_at,
    )


def _mark_failed(user_id: int, celery_task_id: str, error_message: str, started_at: float) -> bool:
    return _lifecycle().fail(
        user_id=user_id,
        feature_key="resume_parse",
        celery_task_id=celery_task_id,
        error_message=error_message,
        started_at=started_at,
    )

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
    logger.info(f"ai_task_stage task_id={self.request.id} feature=resume_parse stage=worker_started")
    try:
        result = loop.run_until_complete(_parse_resume_logic(user_id, file_path))
        logger.info(f"ai_task_stage task_id={self.request.id} feature=resume_parse stage=ai_done")
        _mark_completed(user_id, self.request.id, result, started_at)
        _publish_ws(user_id, "resume_parsed", json.loads(result))
        logger.info(f"ai_task_stage task_id={self.request.id} feature=resume_parse stage=finalized")
    except Exception as e:
        logger.error(f"Resume parsing failed: {e}")
        if _mark_failed(user_id, self.request.id, str(e), started_at):
            _publish_ws(
                user_id,
                "resume_parse_error",
                {"message": "解析服务暂时不可用", "task_id": self.request.id},
            )
