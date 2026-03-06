from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func
from common.databases.models.message import Message
from jobCollectionWebApi.schemas.message_schema import MessageCreate, MessageUpdate
from .base import CRUDBase

class CRUDMessage(CRUDBase[Message, MessageCreate, MessageUpdate]):
    """消息 CRUD"""

    async def get_my_messages(
        self, db: AsyncSession, receiver_id: int, skip: int = 0, limit: int = 20
    ) -> List[Message]:
        """获取我的消息列表"""
        stmt = (
            select(Message)
            .where(Message.receiver_id == receiver_id)
            .order_by(Message.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_unread_count(self, db: AsyncSession, receiver_id: int) -> int:
        """获取未读消息数"""
        stmt = select(func.count(Message.id)).where(
            and_(Message.receiver_id == receiver_id, Message.is_read == False)
        )
        result = await db.execute(stmt)
        return result.scalar()

    async def mark_all_read(self, db: AsyncSession, receiver_id: int) -> None:
        """全部标记为已读"""
        # Note: bulk update in simple way
        # update(Message).where(...).values(is_read=True)
        from sqlalchemy import update
        stmt = (
            update(Message)
            .where(and_(Message.receiver_id == receiver_id, Message.is_read == False))
            .values(is_read=True)
        )
        await db.execute(stmt)
        await db.commit()

message = CRUDMessage(Message)
