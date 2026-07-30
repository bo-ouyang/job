from collections import defaultdict

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.models.agent_conversation import AgentConversation
from common.databases.models.agent_message import AgentMessage
from common.databases.models.agent_run import AgentRun
from schemas.v2.market import (
    MarketHistoryItem,
    MarketHistoryMessage,
    MarketHistoryResponse,
)


class MarketHistoryService:
    async def get_history(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        limit: int = 20,
    ) -> MarketHistoryResponse:
        market_conversation_ids = (
            select(AgentMessage.conversation_id)
            .where(
                AgentMessage.user_id == user_id,
                AgentMessage.message_type == "market_question",
            )
            .distinct()
        )
        total = await db.scalar(
            select(func.count()).select_from(market_conversation_ids.subquery())
        )
        conversation_result = await db.execute(
            select(AgentConversation)
            .where(
                AgentConversation.user_id == user_id,
                AgentConversation.id.in_(market_conversation_ids),
            )
            .order_by(desc(AgentConversation.updated_at), desc(AgentConversation.id))
            .limit(limit)
        )
        conversations = list(conversation_result.scalars().all())
        if not conversations:
            return MarketHistoryResponse(items=[], total=int(total or 0))

        conversation_ids = [conversation.id for conversation in conversations]
        message_result = await db.execute(
            select(AgentMessage)
            .where(
                AgentMessage.user_id == user_id,
                AgentMessage.conversation_id.in_(conversation_ids),
            )
            .order_by(AgentMessage.created_at, AgentMessage.id)
        )
        run_result = await db.execute(
            select(AgentRun)
            .where(
                AgentRun.user_id == user_id,
                AgentRun.conversation_id.in_(conversation_ids),
            )
            .order_by(desc(AgentRun.created_at), desc(AgentRun.id))
        )

        messages_by_conversation = defaultdict(list)
        for message in message_result.scalars().all():
            if message.role not in {"user", "assistant"}:
                continue
            messages_by_conversation[message.conversation_id].append(
                MarketHistoryMessage(
                    id=str(message.id),
                    conversation_id=str(message.conversation_id),
                    role=message.role,
                    message_type=message.message_type,
                    content=message.content,
                    created_at=message.created_at,
                )
            )

        latest_runs = {}
        for run in run_result.scalars().all():
            latest_runs.setdefault(run.conversation_id, run)

        items = []
        for conversation in conversations:
            latest_run = latest_runs.get(conversation.id)
            items.append(
                MarketHistoryItem(
                    conversation_id=str(conversation.id),
                    title=conversation.title,
                    latest_run_id=str(latest_run.id) if latest_run else None,
                    latest_run_status=latest_run.status if latest_run else None,
                    messages=messages_by_conversation[conversation.id],
                    created_at=conversation.created_at,
                    updated_at=conversation.updated_at,
                )
            )
        return MarketHistoryResponse(items=items, total=int(total or 0))


market_history_service = MarketHistoryService()
