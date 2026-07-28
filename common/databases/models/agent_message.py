from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from common.utils.snowflake import generate_id
from .base import Base


class AgentMessage(Base):
    """A user, assistant, tool, or system message in a conversation."""

    __tablename__ = "agent_messages"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "conversation_id",
            "idempotency_key",
            name="uq_agent_message_user_conversation_idempotency",
        ),
        Index("idx_agent_msg_conversation_created", "conversation_id", "created_at", "id"),
        Index("idx_agent_msg_user_created", "user_id", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    conversation_id = Column(
        BigInteger,
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    message_type = Column(String(30), nullable=False, default="text")
    idempotency_key = Column(String(100), nullable=True)
    content = Column(Text, nullable=False)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    conversation = relationship("AgentConversation", back_populates="messages")
