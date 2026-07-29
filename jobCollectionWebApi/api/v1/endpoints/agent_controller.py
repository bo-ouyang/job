import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.models.user import User
from config import settings
from core.exceptions import AppException
from core.status_code import StatusCode
from crud import agent as crud_agent
from dependencies import get_current_user, get_current_user_id_short_lived, get_db
from agent.event_store import agent_event_publisher, agent_sse_event_store
from agent.events import AgentEventType
from agent.locks import agent_sse_connection_limiter
from agent.sse import normalize_last_event_id, stream_agent_events
from common.databases.PostgresManager import db_manager
from common.databases.RedisManager import redis_manager
from core.metrics import (
    agent_runs_cancelled,
    agent_runs_created,
    agent_runs_failed,
    agent_sse_connections_active,
    agent_sse_reconnects,
    celery_tasks_submitted,
)
from schemas.agent_schema import (
    AgentConversationCreate,
    AgentConversationDetailResponse,
    AgentConversationListResponse,
    AgentConversationResponse,
    AgentConversationUpdate,
    AgentMessageCreate,
    AgentMessageResponse,
    AgentMessageSubmissionResponse,
    AgentRunResponse,
    CareerProfileResponse,
    CareerProfileUpdate,
)
from services.ai_access_service import ai_access_service
from jobCollectionWebApi.tasks.agent_tasks import execute_agent_run


router = APIRouter()


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


def _agent_enabled_for_user(user_id: int) -> bool:
    if not settings.AGENT_ENABLED:
        return False
    allowlist = {
        item.strip()
        for item in settings.AGENT_ROLLOUT_USER_IDS.split(",")
        if item.strip()
    }
    if str(user_id) in allowlist:
        return True
    if settings.AGENT_ROLLOUT_PERCENT >= 100:
        return True
    if settings.AGENT_ROLLOUT_PERCENT <= 0:
        return False
    bucket = int(hashlib.sha256(f"career-agent:{user_id}".encode()).hexdigest()[:8], 16) % 100
    return bucket < settings.AGENT_ROLLOUT_PERCENT


def _ensure_agent_enabled(user_id: int) -> None:
    if not _agent_enabled_for_user(user_id):
        raise AppException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=StatusCode.BUSINESS_ERROR,
            message="职业规划 Agent 当前未开放",
        )


@router.get("/capabilities")
async def get_agent_capabilities(
    current_user: User = Depends(get_current_user),
):
    return {
        "enabled": _agent_enabled_for_user(current_user.id),
        "supports_sse": True,
        "supports_message_delta": False,
        "dashboard_mode": "hybrid",
    }


async def _get_owned_conversation(
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


@router.post(
    "/conversations",
    response_model=AgentConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    obj_in: AgentConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_agent_enabled(current_user.id)
    return await crud_agent.create_conversation(db, user_id=current_user.id, obj_in=obj_in)


@router.get("/conversations", response_model=AgentConversationListResponse)
async def list_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = await crud_agent.list_conversations(
        db,
        user_id=current_user.id,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get(
    "/conversations/{conversation_id}",
    response_model=AgentConversationDetailResponse,
)
async def get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)
    messages = await crud_agent.list_messages(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        limit=200,
    )
    latest_run = await crud_agent.get_latest_run(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    return {"conversation": conversation, "messages": messages, "latest_run": latest_run}


@router.patch(
    "/conversations/{conversation_id}",
    response_model=AgentConversationResponse,
)
async def update_conversation(
    conversation_id: int,
    obj_in: AgentConversationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)
    return await crud_agent.update_conversation(db, conversation=conversation, obj_in=obj_in)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[AgentMessageResponse],
)
async def list_messages(
    conversation_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_conversation(db, conversation_id, current_user.id)
    return await crud_agent.list_messages(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=AgentMessageSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_message(
    conversation_id: int,
    obj_in: AgentMessageCreate,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=8,
        max_length=100,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)
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
            db,
            message_id=existing_run.input_message_id,
            user_id=current_user.id,
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
            db,
            conversation_id=conversation_id,
            user_id=current_user.id,
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
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
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
                db,
                run_id=waiting_run.id,
                user_id=current_user.id,
            )
            if message is None or resumed_run is None:
                raise
        try:
            execute_agent_run.apply_async(
                kwargs={"run_id": resumed_run.id, "user_id": current_user.id},
                queue="realtime",
                routing_key="realtime",
            )
            celery_tasks_submitted.labels(
                task_name="execute_agent_run",
                queue="realtime",
            ).inc()
        except Exception as exc:
            await crud_agent.transition_run(
                db,
                run_id=resumed_run.id,
                user_id=current_user.id,
                from_statuses=("queued",),
                to_status="failed",
                values={
                    "current_node": "dispatch_failed",
                    "error_code": "AGENT_DISPATCH_FAILED",
                    "error_message": str(exc)[:1000],
                },
            )
            await db.commit()
            agent_runs_failed.labels(failure_kind="AGENT_DISPATCH_FAILED").inc()
            await agent_event_publisher.publish(
                run_id=resumed_run.id,
                conversation_id=resumed_run.conversation_id,
                event=AgentEventType.RUN_FAILED,
                data={"status": "failed", "error_code": "AGENT_DISPATCH_FAILED"},
            )
            raise AppException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code=StatusCode.EXTERNAL_SERVICE_ERROR,
                message="Agent 运行恢复失败，请稍后重试",
                data={"run_id": str(resumed_run.id)},
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
            db,
            message_id=existing_run.input_message_id,
            user_id=current_user.id,
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
        db=db,
        user_id=current_user.id,
        feature_key=billing_feature_key,
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
        # The worker must never observe a run before its transaction is committed.
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
            db,
            message_id=run.input_message_id,
            user_id=current_user.id,
        )

    try:
        execute_agent_run.apply_async(
            kwargs={"run_id": run.id, "user_id": current_user.id},
            queue="realtime",
            routing_key="realtime",
        )
        celery_tasks_submitted.labels(
            task_name="execute_agent_run",
            queue="realtime",
        ).inc()
        if created_run:
            agent_runs_created.labels(source="message").inc()
    except Exception as exc:
        failed_run = await crud_agent.transition_run(
            db,
            run_id=run.id,
            user_id=current_user.id,
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
        raise AppException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=StatusCode.EXTERNAL_SERVICE_ERROR,
            message="Agent 运行派发失败，请稍后重试",
            data={"run_id": str((failed_run or run).id)},
        )

    return {"message": message, "run": run}


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await crud_agent.get_run(db, run_id=run_id, user_id=current_user.id)
    if run is None:
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            code=StatusCode.BUSINESS_ERROR,
            message="运行不存在",
        )
    return run


@router.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: int,
    request: Request,
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    current_user_id: int = Depends(get_current_user_id_short_lived),
):
    async with db_manager.async_session() as db:
        run = await crud_agent.get_run(db, run_id=run_id, user_id=current_user_id)
        if run is None:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                code=StatusCode.BUSINESS_ERROR,
                message="运行不存在",
            )
        initial_status = run.status
        conversation_id = run.conversation_id

    try:
        connection_token = await agent_sse_connection_limiter.acquire(current_user_id)
    except Exception as exc:
        raise AppException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=StatusCode.EXTERNAL_SERVICE_ERROR,
            message="实时事件服务暂时不可用",
        ) from exc
    if not connection_token:
        raise AppException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code=StatusCode.TOO_MANY_REQUESTS,
            message="实时连接数量已达到上限",
        )
    if normalize_last_event_id(last_event_id):
        agent_sse_reconnects.inc()

    async def limited_event_stream():
        agent_sse_connections_active.inc()
        try:
            async for frame in stream_agent_events(
                request,
                run_id=run_id,
                user_id=current_user_id,
                initial_status=initial_status,
                conversation_id=conversation_id,
                last_event_id=normalize_last_event_id(last_event_id),
                store=agent_sse_event_store,
            ):
                try:
                    await agent_sse_connection_limiter.renew(current_user_id, connection_token)
                except Exception:
                    pass
                yield frame
        finally:
            agent_sse_connections_active.dec()
            try:
                await agent_sse_connection_limiter.release(current_user_id, connection_token)
            except Exception:
                pass

    return StreamingResponse(
        limited_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel", response_model=AgentRunResponse)
async def cancel_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = await crud_agent.get_run(db, run_id=run_id, user_id=current_user.id)
    if existing is None:
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            code=StatusCode.BUSINESS_ERROR,
            message="运行不存在",
        )
    cancelled = await crud_agent.cancel_run(db, run_id=run_id, user_id=current_user.id)
    if cancelled is None:
        raise AppException(
            status_code=status.HTTP_409_CONFLICT,
            code=StatusCode.BUSINESS_ERROR,
            message="当前运行状态不能取消",
        )
    await db.commit()
    agent_runs_cancelled.inc()
    await agent_event_publisher.publish(
        run_id=cancelled.id,
        conversation_id=cancelled.conversation_id,
        event=AgentEventType.RUN_CANCELLED,
        data={"status": "cancelled"},
    )
    return cancelled


@router.get("/profile", response_model=CareerProfileResponse)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = await crud_agent.get_profile(db, user_id=current_user.id)
    if profile is None:
        profile = await crud_agent.upsert_profile(
            db,
            user_id=current_user.id,
            obj_in=CareerProfileUpdate(),
        )
    return profile


@router.patch("/profile", response_model=CareerProfileResponse)
async def update_profile(
    obj_in: CareerProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_agent_enabled(current_user.id)
    return await crud_agent.upsert_profile(db, user_id=current_user.id, obj_in=obj_in)
