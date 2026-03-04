from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class BaseSchema(BaseModel):
    """基础模式"""
    class Config:
        from_attributes = True

class TimestampSchema(BaseSchema):
    """包含时间戳的基础模式"""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None