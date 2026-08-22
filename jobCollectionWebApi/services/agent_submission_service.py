from __future__ import annotations

import hashlib
from typing import Any

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.event_store import agent_event_publisher
from agent.events import AgentEventType
from common.databases.models.user import User
from config import settings
from core.exceptions import AppException
from core.logger import sys_logger as logger
from core.metrics import agent_runs_created, agent_runs_failed, celery_tasks_submitted
from core.status_code import StatusCode
from crud import agent as crud_agent
from common.databases.RedisManager import redis_manager
from schemas.agent_schema import AgentConversationCreate, AgentMessageCreate
from services.ai_access_service import ai_access_service
from jobCollectionWebApi.tasks.agent_tasks import execute_agent_run


def _enqueue_terminal_notification(
    *, user_id: int, run_id: int, status: str, error_message: str | None = None
) -> None:
    try:
        from tasks.notification_tasks import enqueue_agent_run_message

        enqueue_agent_run_message(
            user_id=user_id,
            run_id=run_id,
            status=status,
            error_message=error_message,
        )
    except Exception as exc:
        logger.warning(
            "enqueue AgentRun terminal notification failed; reconciliation will retry: "
            f"run_id={run_id}, status={status}, error={exc}"
        )


async def _enforce_agent_user_rate_limit(user_id: int) -> None:
    key = redis_manager.make_key(f"agent:rate:user:{user_id}")
    script = """
    local current = redis.call('INCR', KEYS[1])
    if current == 1 then redis.call('EXPIRE', KEYS[1], 60) end
    return current
    """
    try:
        current = await redis_manager.redis_client.eval(script, 1, key)
    except Exception as exc:
        raise AppException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=StatusCode.EXTERNAL_SERVICE_ERROR,
            message="Agent 限流服务暂时不可用",
        ) from exc
    if int(current) > settings.AGENT_RATE_LIMIT_PER_MINUTE:
        raise AppException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code=StatusCode.TOO_MANY_REQUESTS,
            message="Agent 请求过于频繁，请稍后再试",
        )


def _ensure_agent_enabled(user_id: int) -> None:
    allowlist = {
        item.strip()
        for item in settings.AGENT_ROLLOUT_USER_IDS.split(",")
        if item.strip()
    }
    enabled = (
        settings.AGENT_ENABLED
        and (
            str(user_id) in allowlist
            or settings.AGENT_ROLLOUT_PERCENT >= 100
            or (
                settings.AGENT_ROLLOUT_PERCENT > 0
                and int(
                    hashlib.sha256(f"career-agent:{user_id}".encode()).hexdigest()[:8],
                    16,
                )
                % 100
                < settings.AGENT_ROLLOUT_PERCENT
            )
        )
    )
    if not enabled:
        raise AppException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=StatusCode.BUSINESS_ERROR,
            message="职业规划 Agent 当前未开放",
        )


class AgentSubmissionService:
    async def _get_owned_conversation(
        self,
        db: AsyncSession,
        conversation_id: int,
        user_id: int,
    ):
        conversation = await crud_agent.get_conversation(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        if conversation is None:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                code=StatusCode.BUSINESS_ERROR,
                message="会话不存在",
            )
        return conversation

    async def _dispatch_or_fail(
        self,
        *,
        db: AsyncSession,
        run,
        user_id: int,
        failure_message: str,
    ) -> None:
        try:
            execute_agent_run.apply_async(
                kwargs={"run_id": run.id, "user_id": user_id},
                queue="realtime",
                routing_key="realtime",
            )
            celery_tasks_submitted.labels(
                task_name="execute_agent_run",
                queue="realtime",
            ).inc()
        except Exception as exc:
            failed_run = await crud_agent.transition_run(
                db,
                run_id=run.id,
                user_id=user_id,
                from_statuses=("queued",),
                to_status="failed",
                values={
                    "current_node": "dispatch_failed",
                    "error_code": "AGENT_DISPATCH_FAILED",
                    "error_message": str(exc)[:1000],
                },
            )
            await db.commit()
            terminal_run = failed_run or run
            agent_runs_failed.labels(failure_kind="AGENT_DISPATCH_FAILED").inc()
            await agent_event_publisher.publish(
                run_id=terminal_run.id,
                conversation_id=terminal_run.conversation_id,
                event=AgentEventType.RUN_FAILED,
                data={"status": "failed", "error_code": "AGENT_DISPATCH_FAILED"},
            )
            _enqueue_terminal_notification(
                user_id=user_id,
                run_id=terminal_run.id,
                status="failed",
                error_message=str(exc)[:1000],
            )
            raise AppException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code=StatusCode.EXTERNAL_SERVICE_ERROR,
                message=failure_message,
                data={"run_id": str(terminal_run.id)},
            ) from exc

    async def submit_message(
        self,
        *,
        conversation_id: int,
        obj_in: AgentMessageCreate,
        idempotency_key: str,
        db: AsyncSession,
        current_user: User,
    ) -> dict[str, Any]:
        conversation = await self._get_owned_conversation(
            db, conversation_id, current_user.id
        )
        if conversation.status != "active":
            raise AppException(
                status_code=status.HTTP_409_CONFLICT,
                code=StatusCode.BUSINESS_ERROR,
                message="归档会话不能继续发送消息",
            )

        existing_run = await crud_agent.get_run_by_idempotency_key(
            db,
            conversation_id=conversation_id,
            user_id=current_user.id,
            idempotency_key=idempotency_key,
        )
        if existing_run is not None:
            existing_message = await crud_agent.get_message(
                db, message_id=existing_run.input_message_id, user_id=current_user.id
            )
            if existing_message is None:
                raise AppException(
                    status_code=status.HTTP_409_CONFLICT,
                    code=StatusCode.BUSINESS_ERROR,
                    message="幂等运行缺少原始消息",
                )
            return {"message": existing_message, "run": existing_run}

        existing_message = await crud_agent.get_message_by_idempotency_key(
            db,
            conversation_id=conversation_id,
            user_id=current_user.id,
            idempotency_key=idempotency_key,
        )
        if existing_message is not None:
            latest_run = await crud_agent.get_latest_run(
                db, conversation_id=conversation_id, user_id=current_user.id
            )
            if latest_run is None:
                raise AppException(
                    status_code=status.HTTP_409_CONFLICT,
                    code=StatusCode.BUSINESS_ERROR,
                    message="幂等消息缺少关联运行",
                )
            return {"message": existing_message, "run": latest_run}

        _ensure_agent_enabled(current_user.id)
        waiting_run = await crud_agent.get_latest_run(
            db, conversation_id=conversation_id, user_id=current_user.id
        )
        if waiting_run is not None and waiting_run.status == "waiting_user":
            await _enforce_agent_user_rate_limit(current_user.id)
            try:
                message = await crud_agent.create_message(
                    db,
                    conversation=conversation,
                    user_id=current_user.id,
                    obj_in=obj_in,
                    role="user",
                    idempotency_key=idempotency_key,
                )
                resumed_run = await crud_agent.transition_run(
                    db,
                    run_id=waiting_run.id,
                    user_id=current_user.id,
                    from_statuses=("waiting_user",),
                    to_status="queued",
                    values={"current_node": "resume_queued", "completed_at": None},
                )
                if resumed_run is None:
                    await db.rollback()
                    raise AppException(
                        status_code=status.HTTP_409_CONFLICT,
                        code=StatusCode.BUSINESS_ERROR,
                        message="等待中的运行已被其他请求恢复",
                    )
                await db.commit()
            except IntegrityError:
                await db.rollback()
                message = await crud_agent.get_message_by_idempotency_key(
                    db,
                    conversation_id=conversation_id,
                    user_id=current_user.id,
                    idempotency_key=idempotency_key,
                )
                resumed_run = await crud_agent.get_run(
                    db, run_id=waiting_run.id, user_id=current_user.id
                )
                if message is None or resumed_run is None:
                    raise
            await self._dispatch_or_fail(
                db=db,
                run=resumed_run,
                user_id=current_user.id,
                failure_message="Agent 运行恢复失败，请稍后重试",
            )
            return {"message": message, "run": resumed_run}

        await _enforce_agent_user_rate_limit(current_user.id)
        await crud_agent.acquire_user_admission_lock(db, user_id=current_user.id)
        existing_run = await crud_agent.get_run_by_idempotency_key(
            db,
            conversation_id=conversation_id,
            user_id=current_user.id,
            idempotency_key=idempotency_key,
        )
        if existing_run is not None:
            existing_message = await crud_agent.get_message(
                db, message_id=existing_run.input_message_id, user_id=current_user.id
            )
            if existing_message is not None:
                return {"message": existing_message, "run": existing_run}

        active_runs = await crud_agent.count_active_runs(db, user_id=current_user.id)
        if active_runs >= settings.AGENT_MAX_CONCURRENT_RUNS_PER_USER:
            raise AppException(
                status_code=status.HTTP_409_CONFLICT,
                code=StatusCode.BUSINESS_ERROR,
                message="已有职业规划正在分析，请等待完成或先取消当前运行",
            )

        billing_feature_key = (
            "career_compass"
            if obj_in.message_type == "career_report_request"
            else "career_advice"
        )
        charge_amount = await ai_access_service.ensure_access(
            db=db, user_id=current_user.id, feature_key=billing_feature_key
        )

        created_run = False
        try:
            message = await crud_agent.create_message(
                db,
                conversation=conversation,
                user_id=current_user.id,
                obj_in=obj_in,
                role="user",
                idempotency_key=idempotency_key,
            )
            run = await crud_agent.create_run(
                db,
                conversation=conversation,
                user_id=current_user.id,
                goal=obj_in.content,
                input_message_id=message.id,
                idempotency_key=idempotency_key,
                billing_feature_key=billing_feature_key,
                charge_amount=charge_amount,
            )
            await db.commit()
            created_run = True
        except IntegrityError:
            await db.rollback()
            run = await crud_agent.get_run_by_idempotency_key(
                db,
                conversation_id=conversation_id,
                user_id=current_user.id,
                idempotency_key=idempotency_key,
            )
            if run is None:
                raise
            message = await crud_agent.get_message(
                db, message_id=run.input_message_id, user_id=current_user.id
            )

        await self._dispatch_or_fail(
            db=db,
            run=run,
            user_id=current_user.id,
            failure_message="Agent 运行派发失败，请稍后重试",
        )
        if created_run:
            agent_runs_created.labels(source="message").inc()
        return {"message": message, "run": run}

    async def submit_new_conversation(
        self,
        *,
        db: AsyncSession,
        user: User,
        content: str,
        filters: dict[str, Any],
        idempotency_key: str,
        title: str,
        message_type: str,
    ) -> dict[str, Any]:
        await crud_agent.acquire_user_admission_lock(db, user_id=user.id)
        existing_run = await crud_agent.get_run_by_user_idempotency_key(
            db,
            user_id=user.id,
            idempotency_key=idempotency_key,
            message_type=message_type,
        )
        if existing_run is not None:
            return {"message": None, "run": existing_run}

        matching_active = await crud_agent.get_latest_active_run(
            db, user_id=user.id, message_type=message_type
        )
        if matching_active is not None:
            active_run, active_message_type = matching_active
            raise AppException(
                status_code=status.HTTP_409_CONFLICT,
                code="AGENT_ACTIVE_RUN_EXISTS",
                message="任务已经创建，正在恢复进度。",
                data={
                    "runId": str(active_run.id),
                    "conversationId": str(active_run.conversation_id),
                    "status": active_run.status,
                    "messageType": active_message_type,
                },
            )

        other_active = await crud_agent.get_latest_active_run(
            db, user_id=user.id, exclude_message_type=message_type
        )
        if other_active is not None:
            active_run, active_message_type = other_active
            raise AppException(
                status_code=status.HTTP_409_CONFLICT,
                code="AGENT_OTHER_RUN_ACTIVE",
                message="其他 AI 任务正在处理中，请等待完成或先取消该任务。",
                data={
                    "runId": str(active_run.id),
                    "conversationId": str(active_run.conversation_id),
                    "status": active_run.status,
                    "messageType": active_message_type,
                },
            )

        conversation = await crud_agent.create_conversation(
            db,
            user_id=user.id,
            obj_in=AgentConversationCreate(title=title, context={"filters": filters}),
        )
        return await self.submit_message(
            conversation_id=conversation.id,
            obj_in=AgentMessageCreate(
                content=content,
                message_type=message_type,
                context={"filters": filters, "source": "api_v2"},
            ),
            idempotency_key=idempotency_key,
            db=db,
            current_user=user,
        )


agent_submission_service = AgentSubmissionService()
