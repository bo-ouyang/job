from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from common.databases.models.agent_conversation import AgentConversation
from common.databases.models.agent_message import AgentMessage
from common.databases.models.agent_run import AgentRun
from common.databases.models.career_profile import CareerProfile
from schemas.agent_schema import (
    AgentConversationCreate,
    AgentConversationUpdate,
    AgentMessageCreate,
    CareerProfileUpdate,
)


async def create_conversation(
    db: AsyncSession,
    *,
    user_id: int,
    obj_in: AgentConversationCreate,
) -> AgentConversation:
    conversation = AgentConversation(
        user_id=user_id,
        title=obj_in.title,
        summary=None,
    )
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def get_conversation(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
) -> Optional[AgentConversation]:
    result = await db.execute(
        select(AgentConversation).where(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_conversations(
    db: AsyncSession,
    *,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
) -> tuple[List[AgentConversation], int]:
    base_filter = AgentConversation.user_id == user_id
    total = await db.scalar(select(func.count(AgentConversation.id)).where(base_filter))
    result = await db.execute(
        select(AgentConversation)
        .where(base_filter)
        .order_by(desc(AgentConversation.updated_at), desc(AgentConversation.id))
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), int(total or 0)


async def update_conversation(
    db: AsyncSession,
    *,
    conversation: AgentConversation,
    obj_in: AgentConversationUpdate,
) -> AgentConversation:
    for field, value in obj_in.model_dump(exclude_unset=True).items():
        setattr(conversation, field, value)
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def create_message(
    db: AsyncSession,
    *,
    conversation: AgentConversation,
    user_id: int,
    obj_in: AgentMessageCreate,
    role: str = "user",
    idempotency_key: Optional[str] = None,
) -> AgentMessage:
    message = AgentMessage(
        conversation_id=conversation.id,
        user_id=user_id,
        role=role,
        message_type=obj_in.message_type,
        idempotency_key=idempotency_key,
        content=obj_in.content,
        metadata_json=obj_in.context,
    )
    db.add(message)
    conversation.updated_at = datetime.utcnow()
    db.add(conversation)
    await db.flush()
    await db.refresh(message)
    return message


async def create_runtime_message(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    role: str,
    message_type: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> AgentMessage:
    message = AgentMessage(
        conversation_id=conversation_id,
        user_id=user_id,
        role=role,
        message_type=message_type,
        content=content,
        metadata_json=metadata,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def list_messages(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    skip: int = 0,
    limit: int = 100,
) -> List[AgentMessage]:
    result = await db.execute(
        select(AgentMessage)
        .where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.user_id == user_id,
        )
        .order_by(desc(AgentMessage.created_at), desc(AgentMessage.id))
        .offset(skip)
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def get_message(
    db: AsyncSession,
    *,
    message_id: int,
    user_id: int,
) -> Optional[AgentMessage]:
    result = await db.execute(
        select(AgentMessage).where(
            AgentMessage.id == message_id,
            AgentMessage.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_message_by_idempotency_key(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    idempotency_key: str,
) -> Optional[AgentMessage]:
    result = await db.execute(
        select(AgentMessage).where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.user_id == user_id,
            AgentMessage.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def create_run(
    db: AsyncSession,
    *,
    conversation: AgentConversation,
    user_id: int,
    goal: Optional[str] = None,
    input_message_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    billing_feature_key: Optional[str] = None,
    charge_amount: float = 0.0,
) -> AgentRun:
    run = AgentRun(
        conversation_id=conversation.id,
        user_id=user_id,
        goal=goal,
        input_message_id=input_message_id,
        idempotency_key=idempotency_key,
        billing_feature_key=billing_feature_key,
        charge_amount=charge_amount,
        status="queued",
        step_count=0,
        tool_call_count=0,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def get_run(
    db: AsyncSession,
    *,
    run_id: int,
    user_id: int,
) -> Optional[AgentRun]:
    result = await db.execute(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_run_by_idempotency_key(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    idempotency_key: str,
) -> Optional[AgentRun]:
    result = await db.execute(
        select(AgentRun).where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.user_id == user_id,
            AgentRun.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def get_run_by_user_idempotency_key(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
    message_type: str,
) -> Optional[AgentRun]:
    """Resolve V2 retries before a new conversation is created."""
    result = await db.execute(
        select(AgentRun)
        .join(AgentMessage, AgentMessage.id == AgentRun.input_message_id)
        .where(
            AgentRun.user_id == user_id,
            AgentRun.idempotency_key == idempotency_key,
            AgentMessage.message_type == message_type,
        )
        .order_by(desc(AgentRun.created_at), desc(AgentRun.id))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_run(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
) -> Optional[AgentRun]:
    result = await db.execute(
        select(AgentRun)
        .where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.user_id == user_id,
        )
        .order_by(desc(AgentRun.created_at), desc(AgentRun.id))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def count_active_runs(
    db: AsyncSession,
    *,
    user_id: int,
) -> int:
    total = await db.scalar(
        select(func.count(AgentRun.id)).where(
            AgentRun.user_id == user_id,
            AgentRun.status.in_(("queued", "running", "waiting_user")),
        )
    )
    return int(total or 0)


async def get_latest_active_run(
    db: AsyncSession,
    *,
    user_id: int,
    message_type: Optional[str] = None,
    exclude_message_type: Optional[str] = None,
) -> Optional[tuple[AgentRun, str]]:
    filters = [
        AgentRun.user_id == user_id,
        AgentRun.status.in_(("queued", "running", "waiting_user")),
    ]
    if message_type is not None:
        filters.append(AgentMessage.message_type == message_type)
    if exclude_message_type is not None:
        filters.append(AgentMessage.message_type != exclude_message_type)
    result = await db.execute(
        select(AgentRun, AgentMessage.message_type)
        .join(AgentMessage, AgentMessage.id == AgentRun.input_message_id)
        .where(*filters)
        .order_by(desc(AgentRun.status_updated_at), desc(AgentRun.id))
        .limit(1)
    )
    row = result.one_or_none()
    return (row[0], row[1]) if row is not None else None


async def transition_run(
    db: AsyncSession,
    *,
    run_id: int,
    user_id: int,
    from_statuses: Sequence[str],
    to_status: str,
    values: Optional[Dict[str, Any]] = None,
    execution_token: Optional[str] = None,
    status_updated_before: Optional[datetime] = None,
) -> Optional[AgentRun]:
    update_values: Dict[str, Any] = {
        "status": to_status,
        "status_updated_at": datetime.utcnow(),
        **(values or {}),
    }
    if to_status in {"completed", "failed", "cancelled"}:
        update_values.setdefault("completed_at", datetime.utcnow())

    conditions = [
        AgentRun.id == run_id,
        AgentRun.user_id == user_id,
        AgentRun.status.in_(list(from_statuses)),
    ]
    if execution_token is not None:
        conditions.append(AgentRun.execution_token == execution_token)
    if status_updated_before is not None:
        conditions.append(AgentRun.status_updated_at < status_updated_before)
    result = await db.execute(update(AgentRun).where(*conditions).values(**update_values))
    if result.rowcount != 1:
        return None
    await db.flush()
    return await get_run(db, run_id=run_id, user_id=user_id)


async def claim_run(
    db: AsyncSession,
    *,
    run_id: int,
    user_id: int,
    execution_token: str,
    lease_seconds: int = 90,
) -> Optional[AgentRun]:
    now = datetime.utcnow()
    result = await db.execute(
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
            or_(
                AgentRun.status == "queued",
                and_(AgentRun.status == "running", AgentRun.lease_expires_at < now),
            ),
        )
        .values(
            status="running",
            execution_token=execution_token,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            started_at=func.coalesce(AgentRun.started_at, now),
            status_updated_at=now,
            current_node="load_context",
        )
    )
    if result.rowcount != 1:
        return None
    await db.flush()
    return await get_run(db, run_id=run_id, user_id=user_id)


async def lock_owned_running_run(
    db: AsyncSession,
    *,
    run_id: int,
    user_id: int,
    execution_token: str,
) -> Optional[AgentRun]:
    """Lock a running attempt's row and verify its execution-token ownership.

    Cancellation uses an UPDATE on the same row, so it must wait until this
    ``FOR UPDATE`` lock is released. The runtime only holds the lock around one
    bounded stream publish, which guarantees a subsequent ``run_cancelled``
    event cannot overtake that delta.
    """

    result = await db.execute(
        select(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
            AgentRun.status == "running",
            AgentRun.execution_token == execution_token,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_run_input_message_type(
    db: AsyncSession,
    *,
    run_id: int,
    user_id: int,
) -> Optional[str]:
    """Return the source request type without exposing its content."""
    result = await db.execute(
        select(AgentMessage.message_type)
        .join(AgentRun, AgentRun.input_message_id == AgentMessage.id)
        .where(AgentRun.id == run_id, AgentRun.user_id == user_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def is_run_owned_and_running(
    db: AsyncSession,
    *,
    run_id: int,
    user_id: int,
    execution_token: str,
) -> bool:
    """Read the current attempt ownership without loading a cached ORM entity."""

    owned_run_id = await db.scalar(
        select(AgentRun.id)
        .where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
            AgentRun.status == "running",
            AgentRun.execution_token == execution_token,
        )
        .limit(1)
    )
    return owned_run_id is not None


async def acquire_user_admission_lock(db: AsyncSession, *, user_id: int) -> None:
    await db.execute(select(func.pg_advisory_xact_lock(int(user_id))))


async def cancel_run(
    db: AsyncSession,
    *,
    run_id: int,
    user_id: int,
) -> Optional[AgentRun]:
    return await transition_run(
        db,
        run_id=run_id,
        user_id=user_id,
        from_statuses=("queued", "running", "waiting_user"),
        to_status="cancelled",
    )


async def get_profile(
    db: AsyncSession,
    *,
    user_id: int,
) -> Optional[CareerProfile]:
    result = await db.execute(
        select(CareerProfile)
        .options(
            selectinload(CareerProfile.courses),
            selectinload(CareerProfile.normalized_skills),
        )
        .where(CareerProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def upsert_profile(
    db: AsyncSession,
    *,
    user_id: int,
    obj_in: CareerProfileUpdate,
) -> CareerProfile:
    profile = await get_profile(db, user_id=user_id)
    if profile is None:
        profile = CareerProfile(user_id=user_id)
        db.add(profile)

    for field, value in obj_in.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile
