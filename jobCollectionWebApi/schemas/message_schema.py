from pydantic import BaseModel, ConfigDict, field_serializer
from typing import Optional
from datetime import datetime
from common.databases.models.message import MessageType

class MessageBase(BaseModel):
    title: Optional[str] = None
    content: str
    type: MessageType = MessageType.USER
    receiver_id: int
    #action_param: Optional[str] = None

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

    @field_serializer("id")
    def serialize_id(self, v: int) -> str:
        # Avoid JS precision loss for Snowflake IDs
        return str(v)

class Message(MessageInDBBase):
    pass
