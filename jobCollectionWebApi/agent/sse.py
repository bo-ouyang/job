import asyncio
import json
import re
import time
from datetime import datetime
from typing import AsyncGenerator, Optional

from fastapi import Request

from common.databases.PostgresManager import db_manager
from config import settings
from crud import agent as crud_agent
from core.logger import sys_logger as logger

from .event_store import AgentEventStore, agent_event_store
from .events import (
    STREAM_CLOSING_EVENTS,
    AgentEvent,
    AgentEventType,
)


_EVENT_ID_PATTERN = re.compile(r"^\d+-\d+$")


def normalize_last_event_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip()
    return normalized if _EVENT_ID_PATTERN.fullmatch(normalized) else None


def format_sse_event(event: AgentEvent) -> str:
    payload = event.model_dump(mode="json")
    return (
        f"id: {event.event_id}\n"
        f"event: {event.event.value}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def event_type_for_status(status: str) -> Optional[AgentEventType]:
    return {
        "completed": AgentEventType.RUN_COMPLETED,
        "failed": AgentEventType.RUN_FAILED,
        "cancelled": AgentEventType.RUN_CANCELLED,
        "waiting_user": AgentEventType.CLARIFICATION_REQUIRED,
    }.get(status)


def reconciled_event(
    *,
    run_id: int,
    conversation_id: int,
    status: str,
    event_type: AgentEventType,
) -> AgentEvent:
    return AgentEvent(
        event_id="0-0",
        sequence=1,
        event=event_type,
        run_id=str(run_id),
        conversation_id=str(conversation_id),
        data={"status": status, "reconciled": True},
        created_at=datetime.utcnow(),
    )


async def load_run_status(run_id: int, user_id: int):
    async with db_manager.async_session() as db:
        return await crud_agent.get_run(db, run_id=run_id, user_id=user_id)


async def stream_agent_events(
    request: Request,
    *,
    run_id: int,
    user_id: int,
    initial_status: str,
    conversation_id: int,
    last_event_id: Optional[str] = None,
    store: AgentEventStore = agent_event_store,
) -> AsyncGenerator[str, None]:
    cursor = normalize_last_event_id(last_event_id)
    closing_event_seen = False
    try:
        replay = await store.replay(run_id, after_id=cursor)
    except Exception as exc:
        logger.warning(f"Agent SSE replay unavailable: run_id={run_id}, error={exc}")
        replay = []

    for event in replay:
        cursor = event.event_id
        yield format_sse_event(event)
        if event.event.value in STREAM_CLOSING_EVENTS:
            closing_event_seen = True
            break
    if closing_event_seen:
        return

    initial_closing_type = event_type_for_status(initial_status)
    if initial_closing_type is not None:
        yield format_sse_event(
            reconciled_event(
                run_id=run_id,
                conversation_id=conversation_id,
                status=initial_status,
                event_type=initial_closing_type,
            )
        )
        return

    heartbeat_seconds = max(3, settings.AGENT_SSE_HEARTBEAT_SECONDS)
    last_heartbeat = time.monotonic()
    cursor = cursor or "0-0"
    while not await request.is_disconnected():
        try:
            events = await store.read_new(run_id, after_id=cursor, block_ms=3000)
        except Exception as exc:
            logger.warning(f"Agent SSE read unavailable: run_id={run_id}, error={exc}")
            events = []
            await asyncio.sleep(1)

        for event in events:
            cursor = event.event_id
            yield format_sse_event(event)
            if event.event.value in STREAM_CLOSING_EVENTS:
                return

        now = time.monotonic()
        if now - last_heartbeat < heartbeat_seconds:
            continue

        yield f": heartbeat {int(time.time())}\n\n"
        last_heartbeat = now
        run = await load_run_status(run_id, user_id)
        if run is None:
            return
        closing_type = event_type_for_status(run.status)
        if closing_type is not None:
            yield format_sse_event(
                reconciled_event(
                    run_id=run.id,
                    conversation_id=run.conversation_id,
                    status=run.status,
                    event_type=closing_type,
                )
            )
            return
