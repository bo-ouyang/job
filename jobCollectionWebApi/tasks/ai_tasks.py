"""
Celery tasks for AI-powered endpoints.

These tasks run asynchronously in the 'realtime' queue so that the
FastAPI worker can return immediately after submitting the task.
Results are pushed to the user via Redis Pub/Sub → WebSocket,
and also stored in the Celery result backend for polling.
"""

import asyncio
import json
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


@shared_task(bind=True, name="tasks.ai_tasks.career_advice_task")
def career_advice_task(
    self,
    user_id: int,
    major: str,
    skills: list,
    engine: str = "auto",
    charge_amount: float = 0,
):
    """Celery task: generate career advice asynchronously."""
    loop = _get_event_loop()
    try:
        result = loop.run_until_complete(
            _career_advice_logic(user_id, major, skills, engine, charge_amount)
        )
        _publish_result(user_id, "career_advice_result", {
            "task_id": self.request.id,
            "advice": result,
        })
        return {"status": "success", "advice": result}
    except Exception as exc:
        logger.error(f"career_advice_task failed: {exc}")
        _publish_error(user_id, "career_advice_error", str(exc))
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


@shared_task(bind=True, name="tasks.ai_tasks.career_compass_task")
def career_compass_task(
    self,
    user_id: int,
    major_name: str,
    es_stats: dict,
    charge_amount: float = 0,
):
    """Celery task: generate career compass report asynchronously."""
    loop = _get_event_loop()
    try:
        result = loop.run_until_complete(
            _career_compass_logic(user_id, major_name, es_stats, charge_amount)
        )
        _publish_result(user_id, "career_compass_result", {
            "task_id": self.request.id,
            "report": result,
        })
        return {"status": "success", "report": result}
    except Exception as exc:
        logger.error(f"career_compass_task failed: {exc}")
        _publish_error(user_id, "career_compass_error", str(exc))
        return {"status": "error", "error": str(exc)}


# ═══════════════════════════════════════════════════
# Task 3: AI Search
# ═══════════════════════════════════════════════════

async def _ai_search_logic(
    user_id: int,
    query: str,
    skip: int,
    page_size: int,
    charge_amount: float,
):
    from services.ai_service import ai_service
    from services.ai_access_service import ai_access_service
    from services.search_service import search_service
    from common.databases.PostgresManager import db_manager

    # 1. Parse intent
    parsed_intent = await ai_service.parse_job_search_intent(query)

    # 2. Search by intent
    jobs, total = await search_service.search_jobs_by_ai_intent(
        intent=parsed_intent,
        skip=skip,
        limit=page_size,
    )

    # 3. Charge usage if successful
    if charge_amount > 0:
        session_obj = await db_manager.get_session()
        async with session_obj as db:
            await ai_access_service.charge_usage(
                db=db,
                user_id=user_id,
                feature_key="ai_search",
                amount=charge_amount,
            )

    # 4. Serialize job items for JSON transport
    serialized_jobs = []
    for job in jobs:
        if hasattr(job, "model_dump"):
            serialized_jobs.append(job.model_dump(mode="json"))
        elif hasattr(job, "__dict__"):
            serialized_jobs.append({
                k: v for k, v in job.__dict__.items()
                if not k.startswith("_")
            })
        else:
            serialized_jobs.append(job)

    return {
        "items": serialized_jobs,
        "total": total,
        "parsed_intent": parsed_intent,
    }


@shared_task(bind=True, name="tasks.ai_tasks.ai_search_task")
def ai_search_task(
    self,
    user_id: int,
    query: str,
    page: int,
    page_size: int,
    charge_amount: float = 0,
):
    """Celery task: AI-powered job search asynchronously."""
    loop = _get_event_loop()
    skip = (page - 1) * page_size
    try:
        result = loop.run_until_complete(
            _ai_search_logic(user_id, query, skip, page_size, charge_amount)
        )
        _publish_result(user_id, "ai_search_result", {
            "task_id": self.request.id,
            "items": result["items"],
            "total": result["total"],
            "page": page,
            "size": page_size,
            "pages": (result["total"] + page_size - 1) // page_size,
        })
        return {
            "status": "success",
            "items": result["items"],
            "total": result["total"],
            "page": page,
            "size": page_size,
            "pages": (result["total"] + page_size - 1) // page_size,
        }
    except Exception as exc:
        logger.error(f"ai_search_task failed: {exc}")
        _publish_error(user_id, "ai_search_error", str(exc))
        return {"status": "error", "error": str(exc)}
