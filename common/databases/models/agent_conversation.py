from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from common.utils.snowflake import generate_id
from .base import Base


class AgentConversation(Base):
    """A user's durable career-planning conversation."""

    __tablename__ = "agent_conversations"
    __table_args__ = (
        Index("idx_agent_conv_user_status_updated", "user_id", "status", "updated_at"),
        Index("idx_agent_conv_user_created", "user_id", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="新的职业规划")
    status = Column(String(20), nullable=False, default="active", index=True)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    messages = relationship(
        "AgentMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AgentMessage.created_at",
    )
    runs = relationship(
        "AgentRun",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AgentRun.created_at",
    )
