from pydantic import BaseModel, ConfigDict, field_serializer
from typing import Any, Dict, Optional
from datetime import datetime
from common.databases.models.message import MessageType

class MessageBase(BaseModel):
    title: Optional[str] = None
    content: str
    type: MessageType = MessageType.USER
    receiver_id: int
    category: Optional[str] = None
    status: Optional[str] = None
    action_type: Optional[str] = None
    action_data: Optional[Dict[str, Any]] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    dedupe_key: Optional[str] = None

class MessageCreate(MessageBase):
    pass

class MessageUpdate(BaseModel):
    is_read: bool

class MessageInDBBase(MessageBase):
    id: int
    sender_id: Optional[int]
    is_read: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id", "sender_id", "receiver_id")
    def serialize_id(self, v: Optional[int]) -> Optional[str]:
        # Avoid JS precision loss for Snowflake IDs
        return str(v) if v is not None else None

class Message(MessageInDBBase):
    pass
