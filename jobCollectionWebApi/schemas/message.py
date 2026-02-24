from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from common.databases.models.message import MessageType

class MessageBase(BaseModel):
    title: Optional[str] = None
    content: str
    type: MessageType = MessageType.USER
    receiver_id: int

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

    class Config:
        from_attributes = True

class Message(MessageInDBBase):
    pass
