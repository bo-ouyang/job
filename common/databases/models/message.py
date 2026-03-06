from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Enum, BigInteger, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base
import enum
from common.utils.snowflake import generate_id

class MessageType(str, enum.Enum):
    SYSTEM = "system"  # 系统通知
    USER = "user"      # 用户私信 (Mock HR)

class Message(Base):
    """消息/通知表"""
    __tablename__ = 'messages'
    __table_args__ = (
        Index("idx_messages_receiver_read_created", "receiver_id", "is_read", "created_at"),
        Index("idx_messages_receiver_type_created", "receiver_id", "type", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    sender_id = Column(BigInteger, ForeignKey('users.id'), nullable=True) # Null for System
    receiver_id = Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True)
    
    type = Column(Enum(MessageType), default=MessageType.SYSTEM)
    title = Column(String(100), nullable=True) # Title for system msg
    content = Column(Text, nullable=False)
    
    is_read = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    sender = relationship("User", foreign_keys=[sender_id], backref="sent_messages")
    receiver = relationship("User", foreign_keys=[receiver_id], backref="received_messages")

    def __repr__(self):
        return f"<Message(id={self.id}, to={self.receiver_id}, type={self.type})>"
