"""
Celery tasks for AI-powered endpoints.

These tasks run asynchronously in the 'realtime' queue so that the
FastAPI worker can return immediately after submitting the task.
Results are pushed to the user via Redis Pub/Sub → WebSocket,
and also stored in the Celery result backend for polling.

【v3 更新】
- mark_completed/failed 回写 AiTask + 释放并发锁
- Prometheus 指标 (ai_task_completed/failed/duration)
- 去重缓存写入 (set_dedup_cache)
- 统一 WS 通知：任务完成/失败时推 ai_task_completed / ai_task_failed
"""

import asyncio
import json
import time
import redis
from celery import shared_task

from config import settings
from core.logger import sys_logger as logger


def _get_event_loop():
    """Get or create an event loop for running async code in Celery workers."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def _publish_result(user_id: int, task_type: str, data: dict):
    """Push result to the user via Redis Pub/Sub → WebSocket."""
    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        msg = {
            "user_id": user_id,
            "message": {
                "type": task_type,
                "data": data,
            }
        }
        r.publish("job_messages", json.dumps(msg, ensure_ascii=False))
        r.close()
    except Exception as e:
        logger.error(f"Failed to publish result via Redis Pub/Sub: {e}")


def _publish_error(user_id: int, task_type: str, error_msg: str):
    """Push error to the user via Redis Pub/Sub → WebSocket."""
    _publish_result(user_id, task_type, {"error": error_msg})


def _enqueue_ai_task_message(
    *,
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    status: str,
    execution_time: float = None,
    error_message: str = None,
):
    """Persist message-center records asynchronously in batch queue."""
    try:
        try:
            from jobCollectionWebApi.tasks.notification_tasks import persist_ai_task_message
        except Exception:
            from tasks.notification_tasks import persist_ai_task_message

        persist_ai_task_message.apply_async(
            kwargs={
                "user_id": user_id,
                "feature_key": feature_key,
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
            f"enqueue ai message failed: user_id={user_id}, feature={feature_key}, task_id={celery_task_id}, status={status}, err={exc}"
        )


def _save_ai_task_message(
    *,
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    status: str,
    execution_time: float = None,
    error_message: str = None,
):
    """Persist message synchronously in the current worker for reliability."""
    loop = _get_event_loop()
    try:
        try:
            from jobCollectionWebApi.tasks.notification_tasks import save_ai_task_message
        except Exception:
            from tasks.notification_tasks import save_ai_task_message

        return loop.run_until_complete(
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
            "save ai message failed: "
            f"user_id={user_id}, feature={feature_key}, task_id={celery_task_id}, "
            f"status={status}, err={exc}"
        )
        return None


def _load_task_payload(celery_task_id: str) -> dict:
    """Load optional large payload from Redis pointer."""
    from crud import ai_task as crud_ai_task

    loop = _get_event_loop()
    payload = loop.run_until_complete(crud_ai_task.get_task_payload(celery_task_id))
    if isinstance(payload, dict):
        return payload
    return {}


# ─── AiTask 回写辅助 ─────────────────────────────

def _mark_task_completed(
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    result_data: str,
    started_at: float,
    request_params: dict = None,
    charge_amount: float = 0.0,
):
    """Persist final task state, cache dedup and notify the user."""
    from crud import ai_task as crud_ai_task

    loop = _get_event_loop()
    execution_time = round(time.time() - started_at, 2) if started_at else None

    try:
        persisted = loop.run_until_complete(
            crud_ai_task.mark_completed(
                user_id=user_id,
                feature_key=feature_key,
                celery_task_id=celery_task_id,
                result_data=result_data,
                started_at=started_at,
                charge_amount=charge_amount,
            )
        )
        if not persisted:
            raise RuntimeError(
                f"AI task result was not persisted: task_id={celery_task_id}"
            )
    except Exception as exc:
        logger.error(f"mark_completed callback failed: {exc}")
        raise

    try:
        loop.run_until_complete(
            crud_ai_task.set_dedup_cache(feature_key, request_params, celery_task_id)
        )
    except Exception as exc:
        logger.warning(f"set_dedup_cache failed: {exc}")

    try:
        from core.metrics import ai_task_completed, ai_task_duration

        ai_task_completed.labels(feature=feature_key).inc()
        if execution_time is not None:
            ai_task_duration.labels(feature=feature_key).observe(execution_time)
    except Exception:
        pass

    message_record = _save_ai_task_message(
        user_id=user_id,
        feature_key=feature_key,
        celery_task_id=celery_task_id,
        status="completed",
        execution_time=execution_time,
    )
    if not message_record:
        _enqueue_ai_task_message(
            user_id=user_id,
            feature_key=feature_key,
            celery_task_id=celery_task_id,
            status="completed",
            execution_time=execution_time,
        )
        message_text = f"Your {_feature_display(feature_key)} task has completed"
        message_id = None
    else:
        message_text = message_record["content"]
        message_id = message_record["message_id"]

    _publish_result(
        user_id,
        "ai_task_completed",
        {
            "task_id": celery_task_id,
            "feature_key": feature_key,
            "status": "completed",
            "execution_time": execution_time,
            "message": message_text,
            "message_id": message_id,
        },
    )

def _mark_task_failed(
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    error_message: str,
    started_at: float,
):
    """Persist failed task state and notify the user."""
    from crud import ai_task as crud_ai_task

    loop = _get_event_loop()
    execution_time = round(time.time() - started_at, 2) if started_at else None

    try:
        loop.run_until_complete(
            crud_ai_task.mark_failed(
                user_id=user_id,
                feature_key=feature_key,
                celery_task_id=celery_task_id,
                error_message=error_message,
                started_at=started_at,
            )
        )
    except Exception as exc:
        logger.error(f"mark_failed callback failed: {exc}")

    try:
        from core.metrics import ai_task_failed, ai_task_duration

        ai_task_failed.labels(feature=feature_key).inc()
        if execution_time is not None:
            ai_task_duration.labels(feature=feature_key).observe(execution_time)
    except Exception:
        pass

    message_record = _save_ai_task_message(
        user_id=user_id,
        feature_key=feature_key,
        celery_task_id=celery_task_id,
        status="failed",
        execution_time=execution_time,
        error_message=error_message,
    )
    if not message_record:
        _enqueue_ai_task_message(
            user_id=user_id,
            feature_key=feature_key,
            celery_task_id=celery_task_id,
            status="failed",
            execution_time=execution_time,
            error_message=error_message,
        )
        message_text = f"Your {_feature_display(feature_key)} task has failed"
        message_id = None
    else:
        message_text = message_record["content"]
        message_id = message_record["message_id"]

    _publish_result(
        user_id,
        "ai_task_failed",
        {
            "task_id": celery_task_id,
            "feature_key": feature_key,
            "status": "failed",
            "error": error_message,
            "message": message_text,
            "message_id": message_id,
        },
    )

def _feature_display(feature_key: str) -> str:
    """Feature display name."""
    return {
        "career_advice": "AI career advice",
        "career_compass": "career compass",
        "resume_parse": "resume parsing",
    }.get(feature_key, "AI task")

# ═══════════════════════════════════════════════════
# Task 1: Career Advice
# ═══════════════════════════════════════════════════

async def _career_advice_logic(
    user_id: int,
    major: str,
    skills: list,
    engine: str,
    charge_amount: float,
):
    from services.ai_service import ai_service
    logger.info(f"stat_career_advice started")
    # Call AI
    advice = await ai_service.generate_career_advice(
        major, skills, engine=engine,
    )
    logger.info(f"generate_career_advice done")
    advice_text = advice if isinstance(advice, str) else str(advice)

    return advice_text


@shared_task(
    bind=True,
    name="tasks.ai_tasks.career_advice_task",
    acks_late=True,
    time_limit=300,
    soft_time_limit=270,
)
def career_advice_task(
    self,
    user_id: int,
    major: str,
    skills: list,
    engine: str = "auto",
    charge_amount: float = 0,
    analysis_result: dict = None,
    payload_task_id: str = None,
):
    """Celery task: generate career advice asynchronously."""
    loop = _get_event_loop()
    started_at = time.time()
    request_params = {"major_name": major, "skills": skills, "engine": engine}
    logger.info(f"ai_task_stage task_id={self.request.id} feature=career_advice stage=worker_started")
    try:
        result = loop.run_until_complete(
            _career_advice_logic(user_id, major, skills, engine, charge_amount)
        )
        logger.info(f"ai_task_stage task_id={self.request.id} feature=career_advice stage=ai_done")
        if analysis_result is None and payload_task_id:
            payload = _load_task_payload(payload_task_id)
            analysis_result = payload.get("analysis_result")

        # 将建议与分析结果一起落库，便于前端历史恢复图表
        result_payload = json.dumps({
            "advice": result,
            "analysis_result": analysis_result,
        }, ensure_ascii=False)
        # 回写 AiTask + 去重 + 指标 + 统一通知
        billable_amount = charge_amount if not result.strip().startswith("❌") else 0.0
        _mark_task_completed(
            user_id,
            "career_advice",
            self.request.id,
            result_payload,
            started_at,
            request_params,
            billable_amount,
        )
        # Only notify clients after the result and wallet charge commit together.
        _publish_result(user_id, "career_advice_result", {
            "task_id": self.request.id,
            "advice": result,
        })
        logger.info(f"ai_task_stage task_id={self.request.id} feature=career_advice stage=finalized")
        return {"status": "success", "advice": result}
    except Exception as exc:
        logger.error(f"career_advice_task failed: {exc}")
        _publish_error(user_id, "career_advice_error", str(exc))
        _mark_task_failed(user_id, "career_advice", self.request.id, str(exc), started_at)
        return {"status": "error", "error": str(exc)}


# ═══════════════════════════════════════════════════
# Task 2: Career Compass
# ═══════════════════════════════════════════════════

async def _career_compass_logic(
    user_id: int,
    major_name: str,
    es_stats: dict,
    charge_amount: float,
):
    from services.ai_service import ai_service
    logger.info("stat_career_compass started")
    ai_started_at = time.time()
    # Call AI with pre-aggregated ES data
    ai_report = await ai_service.get_career_navigation_report(
        major_name=major_name,
        es_stats=es_stats,
    )
    logger.info(
        f"get_career_navigation_report done elapsed={time.time() - ai_started_at:.2f}s"
    )
    report_text = ai_report if isinstance(ai_report, str) else str(ai_report)

    return report_text


@shared_task(
    bind=True,
    name="tasks.ai_tasks.career_compass_task",
    acks_late=True,
    time_limit=300,
    soft_time_limit=270,
)
def career_compass_task(
    self,
    user_id: int,
    major_name: str,
    es_stats: dict = None,
    charge_amount: float = 0,
    skill_cloud_data: list = None,
    payload_task_id: str = None,
):
    """Celery task: generate career compass report asynchronously."""
    loop = _get_event_loop()
    started_at = time.time()
    request_params = {"major_name": major_name}
    logger.info(f"ai_task_stage task_id={self.request.id} feature=career_compass stage=worker_started")
    try:
        if payload_task_id and (es_stats is None or skill_cloud_data is None):
            payload = _load_task_payload(payload_task_id)
            if es_stats is None:
                es_stats = payload.get("es_stats")
            if skill_cloud_data is None:
                skill_cloud_data = payload.get("skill_cloud_data")

        if not isinstance(es_stats, dict):
            raise ValueError("Missing es_stats payload for career_compass task")

        result = loop.run_until_complete(
            _career_compass_logic(user_id, major_name, es_stats, charge_amount)
        )
        logger.info(f"ai_task_stage task_id={self.request.id} feature=career_compass stage=ai_done")
        # 将报告与统计一起落库，便于前端历史恢复图表
        result_payload = json.dumps({
            "report": result,
            "es_stats": es_stats,
            "skill_cloud_data": skill_cloud_data,
        }, ensure_ascii=False)
        # 回写 AiTask + 去重 + 指标 + 统一通知
        billable_amount = charge_amount if not result.strip().startswith("❌") else 0.0
        _mark_task_completed(
            user_id,
            "career_compass",
            self.request.id,
            result_payload,
            started_at,
            request_params,
            billable_amount,
        )
        # Only notify clients after the result and wallet charge commit together.
        _publish_result(user_id, "career_compass_result", {
            "task_id": self.request.id,
            "report": result,
        })
        logger.info(f"ai_task_stage task_id={self.request.id} feature=career_compass stage=finalized")
        return {"status": "success", "report": result}
    except Exception as exc:
        logger.error(f"career_compass_task failed: {exc}")
        _publish_error(user_id, "career_compass_error", str(exc))
        _mark_task_failed(user_id, "career_compass", self.request.id, str(exc), started_at)
        return {"status": "error", "error": str(exc)}
