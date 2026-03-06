from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, BigInteger, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base
from common.utils.snowflake import generate_id

class AdminLog(Base):
    __tablename__ = "admin_logs"
    __table_args__ = (
        Index("idx_admin_logs_user_action_created", "user_id", "action", "created_at"),
        Index("idx_admin_logs_model_object", "model_name", "object_id"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    username = Column(String(100), nullable=True)  # Snapshot
    action = Column(String(50), nullable=False)   # CREATE, EDIT, DELETE
    model_name = Column(String(50), nullable=False) # Table/Resource name
    object_id = Column(String(50), nullable=True)   # Affected ID
    details = Column(Text, nullable=True) 
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", backref="admin_logs")

    def __repr__(self):
        return f"<AdminLog(action='{self.action}', model='{self.model_name}', user='{self.username}')>"
