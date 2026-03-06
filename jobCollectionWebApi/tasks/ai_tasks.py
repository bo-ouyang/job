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


# ─── AiTask 回写辅助 ─────────────────────────────

def _mark_task_completed(
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    result_data: str,
    started_at: float,
    request_params: dict = None,
):
    """同步包装：在 Celery worker 中调用 async mark_completed + 去重缓存 + 指标"""
    from crud import ai_task as crud_ai_task
    loop = _get_event_loop()
    execution_time = round(time.time() - started_at, 2) if started_at else None

    try:
        loop.run_until_complete(
            crud_ai_task.mark_completed(
                user_id=user_id,
                feature_key=feature_key,
                celery_task_id=celery_task_id,
                result_data=result_data,
                started_at=started_at,
            )
        )
    except Exception as exc:
        logger.error(f"mark_completed callback failed: {exc}")

    # 去重缓存
    try:
        loop.run_until_complete(
            crud_ai_task.set_dedup_cache(feature_key, request_params, celery_task_id)
        )
    except Exception as exc:
        logger.warning(f"set_dedup_cache failed: {exc}")

    # Prometheus 指标
    try:
        from core.metrics import ai_task_completed, ai_task_duration
        ai_task_completed.labels(feature=feature_key).inc()
        if execution_time is not None:
            ai_task_duration.labels(feature=feature_key).observe(execution_time)
    except Exception:
        pass

    message_text = f"您的{_feature_display(feature_key)}已完成"
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
                # Build an action_param dictionary so that the frontend knows where to route when the message is clicked
                action_param = json.dumps({"task_id": celery_task_id, "feature_key": feature_key})
                new_msg = await crud_message.create(
                    db,
                    obj_in=MessageCreate(
                        title=f"✅ {_feature_display(feature_key)}完成",
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

    # 统一 WS 通知: ai_task_completed
    _publish_result(user_id, "ai_task_completed", {
        "task_id": celery_task_id,
        "feature_key": feature_key,
        "status": "completed",
        "execution_time": execution_time,
        "message": message_text,
        "message_id": message_id,
    })


def _mark_task_failed(
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    error_message: str,
    started_at: float,
):
    """同步包装：在 Celery worker 中调用 async mark_failed + 指标"""
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

    # Prometheus 指标
    try:
        from core.metrics import ai_task_failed, ai_task_duration
        ai_task_failed.labels(feature=feature_key).inc()
        if execution_time is not None:
            ai_task_duration.labels(feature=feature_key).observe(execution_time)
    except Exception:
        pass

    message_text = f"您的{_feature_display(feature_key)}处理失败"
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
                action_param = json.dumps({"task_id": celery_task_id, "feature_key": feature_key})
                new_msg = await crud_message.create(
                    db,
                    obj_in=MessageCreate(
                        title=f"❌ {_feature_display(feature_key)}失败",
                        content=f"{message_text}。原因: {error_message}",
                        type=MessageType.SYSTEM,
                        receiver_id=user_id,
                        action_param=action_param,
                    )
                )
                await db.commit()
                return new_msg.id
        message_id = loop.run_until_complete(_create_msg())
    except Exception as exc:
        logger.error(f"Save message failed: {exc}")

    # 统一 WS 通知: ai_task_failed
    _publish_result(user_id, "ai_task_failed", {
        "task_id": celery_task_id,
        "feature_key": feature_key,
        "status": "failed",
        "error": error_message,
        "message": message_text,
        "message_id": message_id,
    })


def _feature_display(feature_key: str) -> str:
    """功能名称中文映射"""
    return {
        "career_advice": "AI职业建议",
        "career_compass": "职业罗盘分析",
        "resume_parse": "简历解析",
    }.get(feature_key, "AI任务")


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
    from services.ai_access_service import ai_access_service
    from common.databases.PostgresManager import db_manager

    # Call AI
    advice = await ai_service.generate_career_advice(
        major, skills, engine=engine,
    )
    advice_text = advice if isinstance(advice, str) else str(advice)

    # Charge usage if successful
    if charge_amount > 0 and not advice_text.strip().startswith("❌"):
        session_obj = await db_manager.get_session()
        async with session_obj as db:
            await ai_access_service.charge_usage(
                db=db,
                user_id=user_id,
                feature_key="career_advice",
                amount=charge_amount,
            )

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
):
    """Celery task: generate career advice asynchronously."""
    loop = _get_event_loop()
    started_at = time.time()
    request_params = {"major_name": major, "skills": skills, "engine": engine}
    try:
        result = loop.run_until_complete(
            _career_advice_logic(user_id, major, skills, engine, charge_amount)
        )
        # 功能级 WS 通知 (保持向后兼容)
        _publish_result(user_id, "career_advice_result", {
            "task_id": self.request.id,
            "advice": result,
        })
        # 将建议与分析结果一起落库，便于前端历史恢复图表
        result_payload = json.dumps({
            "advice": result,
            "analysis_result": analysis_result,
        }, ensure_ascii=False)
        # 回写 AiTask + 去重 + 指标 + 统一通知
        _mark_task_completed(user_id, "career_advice", self.request.id, result_payload, started_at, request_params)
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
    from services.ai_access_service import ai_access_service
    from common.databases.PostgresManager import db_manager

    # Call AI with pre-aggregated ES data
    ai_report = await ai_service.get_career_navigation_report(
        major_name=major_name,
        es_stats=es_stats,
    )
    report_text = ai_report if isinstance(ai_report, str) else str(ai_report)

    # Charge usage if successful
    if charge_amount > 0 and not report_text.strip().startswith("❌"):
        session_obj = await db_manager.get_session()
        async with session_obj as db:
            await ai_access_service.charge_usage(
                db=db,
                user_id=user_id,
                feature_key="career_compass",
                amount=charge_amount,
            )

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
    es_stats: dict,
    charge_amount: float = 0,
    skill_cloud_data: list = None,
):
    """Celery task: generate career compass report asynchronously."""
    loop = _get_event_loop()
    started_at = time.time()
    request_params = {"major_name": major_name}
    try:
        result = loop.run_until_complete(
            _career_compass_logic(user_id, major_name, es_stats, charge_amount)
        )
        # 功能级 WS 通知 (保持向后兼容)
        _publish_result(user_id, "career_compass_result", {
            "task_id": self.request.id,
            "report": result,
        })
        # 将报告与统计一起落库，便于前端历史恢复图表
        result_payload = json.dumps({
            "report": result,
            "es_stats": es_stats,
            "skill_cloud_data": skill_cloud_data,
        }, ensure_ascii=False)
        # 回写 AiTask + 去重 + 指标 + 统一通知
        _mark_task_completed(user_id, "career_compass", self.request.id, result_payload, started_at, request_params)
        return {"status": "success", "report": result}
    except Exception as exc:
        logger.error(f"career_compass_task failed: {exc}")
        _publish_error(user_id, "career_compass_error", str(exc))
        _mark_task_failed(user_id, "career_compass", self.request.id, str(exc), started_at)
        return {"status": "error", "error": str(exc)}
