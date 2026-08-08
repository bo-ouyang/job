"""Celery entrypoint for bounded career Agent runs."""

import asyncio
import uuid
import time

from celery import shared_task

from agent.errors import AgentCancelledError
from agent.event_store import agent_event_publisher
from agent.events import AgentEventType
from agent.locks import agent_run_lock
from agent.runtime import AgentRuntime
from common.databases.PostgresManager import db_manager
from crud import agent as crud_agent
from core.logger import sys_logger as logger
from core.metrics import agent_lock_contention, agent_run_duration, agent_runs_failed
from services.notification_service import NotificationPersistenceError


class AgentRunLockContention(Exception):
    pass


def _get_event_loop():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed event loop")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


async def _execute_agent_run(run_id: int, user_id: int, execution_token: str) -> dict:
    lock_token = None
    lock_available = True
    try:
        lock_token = await agent_run_lock.acquire(run_id)
    except Exception as exc:
        lock_available = False
        logger.warning(f"Agent Redis run lock unavailable, relying on DB claim: run_id={run_id}, error={exc}")
    if lock_available and lock_token is None:
        agent_lock_contention.inc()
        raise AgentRunLockContention(f"run {run_id} is locked")
    try:
        async with await db_manager.get_session() as db:
            runtime = AgentRuntime(db)
            result = await runtime.execute(run_id, user_id, execution_token=execution_token)
            # AgentRuntime has already committed the answer/run/billing state.
            # Notification persistence deliberately happens in its own follow-up
            # transaction, so a retry cannot duplicate the completed answer.
            await _notify_terminal_run(db, run_id=run_id, user_id=user_id)
            return result
    finally:
        if lock_token:
            try:
                await agent_run_lock.release(run_id, lock_token)
            except Exception as exc:
                logger.warning(f"Agent run lock release failed: run_id={run_id}, error={exc}")


async def _mark_failed(
    run_id: int,
    user_id: int,
    error: Exception,
    execution_token: str,
) -> None:
    async with await db_manager.get_session() as db:
        run = await crud_agent.transition_run(
            db,
            run_id=run_id,
            user_id=user_id,
            from_statuses=("queued", "running"),
            to_status="failed",
            values={
                "current_node": "failed",
                "error_code": getattr(error, "code", "AGENT_RUNTIME_FAILED"),
                "error_message": str(error)[:1000] or "Agent Runtime 执行失败",
            },
            execution_token=execution_token,
        )
        await db.commit()
        if run is not None:
            agent_runs_failed.labels(
                failure_kind=getattr(error, "code", "AGENT_RUNTIME_FAILED")
            ).inc()
            await _notify_terminal_run(db, run_id=run_id, user_id=user_id)
            # The failure state is committed and its durable notification is
            # scheduled/persisted before publishing a best-effort SSE hint.
            # A custom publisher must never make the worker skip this path.
            try:
                await agent_event_publisher.publish(
                    run_id=run.id,
                    conversation_id=run.conversation_id,
                    event=AgentEventType.RUN_FAILED,
                    data={
                        "status": "failed",
                        "error_code": getattr(error, "code", "AGENT_RUNTIME_FAILED"),
                        "message": "Agent 分析失败，请稍后重试",
                    },
                )
            except Exception as exc:
                logger.warning(
                    f"Agent failure SSE publish failed: run_id={run.id}, error={exc}"
                )


async def _notify_terminal_run(db, *, run_id: int, user_id: int) -> None:
    """Persist a retry-safe message after a terminal AgentRun has committed."""
    run = await crud_agent.get_run(db, run_id=run_id, user_id=user_id)
    if run is None or run.status not in {"completed", "failed", "cancelled"}:
        return
    try:
        from tasks.notification_tasks import save_agent_run_message
    except ImportError:
        from jobCollectionWebApi.tasks.notification_tasks import save_agent_run_message
    await save_agent_run_message(
        run_id=run_id,
        user_id=user_id,
        status=run.status,
        error_message=run.error_message,
    )


@shared_task(
    bind=True,
    name="tasks.agent_tasks.execute_agent_run",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=270,
    time_limit=300,
)
def execute_agent_run(self, run_id: int, user_id: int) -> dict:
    loop = _get_event_loop()
    execution_token = uuid.uuid4().hex
    started = time.monotonic()
    try:
        return loop.run_until_complete(_execute_agent_run(run_id, user_id, execution_token))
    except AgentRunLockContention as exc:
        raise self.retry(exc=exc, countdown=5, max_retries=20)
    except AgentCancelledError:
        return {"run_id": str(run_id), "status": "cancelled"}
    except NotificationPersistenceError as exc:
        # The business result is already committed. Re-entering this task will
        # see an ignored terminal run and retry only the deduplicated message.
        raise self.retry(exc=exc, countdown=5, max_retries=8)
    except Exception as exc:
        logger.exception(f"Agent run failed: run_id={run_id}, error={exc}")
        try:
            loop.run_until_complete(_mark_failed(run_id, user_id, exc, execution_token))
            agent_run_duration.observe(time.monotonic() - started)
        except NotificationPersistenceError as notify_exc:
            raise self.retry(exc=notify_exc, countdown=5, max_retries=8)
        except Exception as mark_exc:
            logger.error(f"Failed to mark Agent run as failed: run_id={run_id}, error={mark_exc}")
        raise


# Compatibility alias for Batch 2 imports that may still exist in running API workers.
initialize_agent_run = execute_agent_run
