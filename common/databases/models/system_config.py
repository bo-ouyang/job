from sqlalchemy import Column, String, Text, Boolean, DateTime, BigInteger
from sqlalchemy.sql import func

from common.databases.models.base import Base
from common.utils.snowflake import generate_id


class SystemConfig(Base):
    __tablename__ = "system_configs"

    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    key = Column(String(120), unique=True, nullable=False, index=True, comment="Config key")
    value = Column(Text, nullable=True, comment="Config value")
    category = Column(String(50), default="general", index=True, comment="Config category")
    description = Column(Text, nullable=True, comment="Config description")
    is_active = Column(Boolean, default=True, comment="Is active")

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
