from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from common.utils.snowflake import generate_id
from .base import Base


class AgentRun(Base):
    """A bounded execution of the Agent for one user message."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "conversation_id",
            "idempotency_key",
            name="uq_agent_run_user_conversation_idempotency",
        ),
        Index("idx_agent_run_user_status", "user_id", "status"),
        Index("idx_agent_run_conversation_status", "conversation_id", "status"),
        Index("idx_agent_run_conversation_created", "conversation_id", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    conversation_id = Column(
        BigInteger,
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    input_message_id = Column(
        BigInteger,
        ForeignKey("agent_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    idempotency_key = Column(String(100), nullable=True)
    execution_token = Column(String(64), nullable=True, index=True)
    lease_expires_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="queued", index=True)
    goal = Column(Text, nullable=True)
    current_node = Column(String(80), nullable=True)
    step_count = Column(Integer, nullable=False, default=0)
    tool_call_count = Column(Integer, nullable=False, default=0)
    state_snapshot = Column(JSONB, nullable=True)
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    billing_feature_key = Column(String(50), nullable=True)
    charge_amount = Column(Numeric(10, 2), nullable=False, default=0)
    charged_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    status_updated_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    conversation = relationship("AgentConversation", back_populates="runs")
